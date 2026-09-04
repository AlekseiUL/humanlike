import hashlib
import multiprocessing
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from humanlike_agent.memory import (
    Evidence,
    MemoryKind,
    MemoryRecord,
    RecallHit,
    RecallQuery,
    SQLiteMemoryLedger,
)

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="persistent SQLite memory is currently POSIX-only"
)

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_DIGEST = hashlib.sha256(b"synthetic evidence").hexdigest()
_CRASH_EXIT = 73


def _evidence(**overrides: Any) -> Evidence:
    values = {
        "source_kind": "explicit_user_statement",
        "digest": _DIGEST,
        "observed_at": _NOW,
        "source_id": "turn-1",
    }
    return Evidence(**(values | overrides))


def _record(record_id: str = "record-1", **overrides: Any) -> MemoryRecord:
    values = {
        "record_id": record_id,
        "profile_id": "profile-1",
        "session_id": None,
        "kind": MemoryKind.PREFERENCE,
        "key": "drink",
        "value": "green tea",
        "confidence": 0.9,
        "created_at": _NOW,
        "valid_from": _NOW - timedelta(days=1),
        "valid_until": None,
        "evidence": _evidence(),
        "supersedes": (),
        "tags": ("beverage",),
    }
    return MemoryRecord(**(values | overrides))


def _query(**overrides: Any) -> RecallQuery:
    values = {
        "profile_id": "profile-1",
        "session_id": None,
        "at": _NOW,
        "key": "drink",
        "terms": (),
        "kinds": (),
        "limit": 10,
    }
    return RecallQuery(**(values | overrides))


def _directory_digest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        os.fspath(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _process_write(path: str, index: int) -> None:
    SQLiteMemoryLedger(path).remember(
        _record(f"process-{index:02d}", key=f"process-key-{index:02d}")
    )


def _crash_before_snapshot_replace(path: str, marker: str) -> None:
    real_replace = os.replace
    prefix = f".{Path(path).name}.tmp-"
    pattern = re.compile(rf"{re.escape(prefix)}[0-9a-f]{{24}}\Z")

    def crash_replace(source: object, target: object, **kwargs: object) -> None:
        if pattern.fullmatch(os.fspath(source)):
            os._exit(_CRASH_EXIT)
        real_replace(source, target, **kwargs)

    os.replace = crash_replace  # type: ignore[assignment]
    SQLiteMemoryLedger(path).remember(_record("crash-record", key="crash-key", value=marker))
    os._exit(_CRASH_EXIT + 1)


def _leave_crash_orphan(path: Path, marker: str) -> Path:
    context = multiprocessing.get_context("fork")
    process = context.Process(
        target=_crash_before_snapshot_replace,
        args=(os.fspath(path), marker),
    )
    process.start()
    process.join(timeout=15)
    assert process.exitcode == _CRASH_EXIT
    pattern = re.compile(rf"\.{re.escape(path.name)}\.tmp-[0-9a-f]{{24}}\Z")
    candidates = [entry for entry in path.parent.iterdir() if pattern.fullmatch(entry.name)]
    assert len(candidates) == 1
    assert marker.encode() in candidates[0].read_bytes()
    return candidates[0]


def test_memory_contracts_are_frozen_typed_and_contain_no_raw_transcript() -> None:
    evidence = _evidence()
    record = _record()
    query = _query()
    hit = RecallHit(record=record, why_recalled=("exact_key",))

    assert [kind.value for kind in MemoryKind] == [
        "fact",
        "preference",
        "event",
        "boundary",
        "rule",
        "promise",
    ]
    forbidden = {"raw", "transcript", "prompt", "user_message", "assistant_response"}
    assert not forbidden.intersection(field.name for field in fields(Evidence))
    assert not forbidden.intersection(field.name for field in fields(MemoryRecord))
    for contract in (evidence, record, query, hit):
        with pytest.raises(FrozenInstanceError):
            setattr(contract, fields(contract)[0].name, None)


def test_direct_constructors_canonicalize_nfc_digest_tags_and_timezones() -> None:
    offset = timezone(timedelta(hours=4))
    record = _record(
        key="cafe\u0301",
        value="the\u0301",
        created_at=_NOW.astimezone(offset),
        evidence=_evidence(digest=_DIGEST.upper(), observed_at=_NOW.astimezone(offset)),
        tags=("zeta", "cafe\u0301"),
    )

    assert record.key == "café"
    assert record.value == "thé"
    assert record.created_at.tzinfo is UTC
    assert record.evidence.digest == _DIGEST
    assert record.evidence.observed_at.tzinfo is UTC
    assert record.tags == ("café", "zeta")


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: _evidence(digest="not-a-digest"), "digest"),
        (lambda: _evidence(source_kind="bad\x00kind"), "control"),
        (lambda: _evidence(observed_at=datetime(2026, 1, 1)), "timezone"),
        (lambda: _record(confidence=float("nan")), "confidence"),
        (lambda: _record(confidence=1.1), "confidence"),
        (lambda: _record(key="bad\u202ekey"), "control"),
        (lambda: _record(key="bad-key\n"), "control"),
        (lambda: _record(value={"nested": "not atomic"}), "atom"),
        (lambda: _record(valid_until=_NOW - timedelta(days=2)), "valid"),
        (lambda: _record(tags=tuple(f"tag-{index}" for index in range(17))), "tags"),
        (
            lambda: _record(supersedes=tuple(f"id-{index}" for index in range(33))),
            "supersedes",
        ),
        (lambda: _query(at=datetime(2026, 1, 1)), "timezone"),
        (lambda: _query(limit=0), "limit"),
        (lambda: _query(limit=51), "limit"),
        (lambda: _query(terms=tuple(f"term-{index}" for index in range(9))), "terms"),
    ],
)
def test_direct_constructors_reject_unsafe_or_unbounded_values(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        factory()


def test_no_save_and_absent_reads_create_no_parent_database_or_sidecars(tmp_path: Path) -> None:
    state_root = tmp_path / "missing" / "state"
    ledger = SQLiteMemoryLedger(state_root / "memory.db")

    assert ledger.remember(_record(), no_save=True) is False
    assert ledger.delete("record-1", "profile-1", no_save=True) is False
    assert ledger.recall(_query()) == ()
    assert ledger.conflicts("profile-1", "drink", at=_NOW) == ()
    assert ledger.schema_columns() == {}
    assert ledger.quick_check() == "absent"
    assert not state_root.exists()


def test_remember_creates_private_schema_and_exact_recall_reason(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)

    assert ledger.remember(_record()) is True
    hits = ledger.recall(_query(kinds=(MemoryKind.PREFERENCE,)))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    lock_path = next(
        candidate for candidate in tmp_path.iterdir() if candidate.name.endswith(".lock")
    )
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert len(hits) == 1
    assert hits[0].record == _record()
    assert hits[0].why_recalled[0] == "exact_key"
    assert "kind:preference" in hits[0].why_recalled
    assert any(reason.startswith("recency:") for reason in hits[0].why_recalled)
    assert ledger.quick_check() == "ok"

    columns = ledger.schema_columns()
    assert set(columns) == {"memory_records", "memory_supersessions", "memory_terms"}
    forbidden = ("raw", "transcript", "prompt", "user_message", "assistant_response")
    assert not any(
        token in column for names in columns.values() for column in names for token in forbidden
    )


def test_existing_database_without_private_permissions_and_lock_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.db"
    path.write_bytes(b"")
    path.chmod(0o644)

    with pytest.raises(ValueError, match="0600|lock"):
        SQLiteMemoryLedger(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_existing_private_database_without_sibling_lock_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    path.write_bytes(b"not opened")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="sibling lock"):
        SQLiteMemoryLedger(path)


def test_no_save_delete_remember_and_reads_do_not_change_existing_database_bytes(
    tmp_path: Path,
) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record())
    before = _directory_digest(tmp_path)

    assert ledger.remember(_record("never-written"), no_save=True) is False
    assert ledger.delete("record-1", "profile-1", no_save=True) is False
    assert ledger.recall(_query())
    assert ledger.schema_columns()
    assert ledger.quick_check() == "ok"

    assert _directory_digest(tmp_path) == before


def test_read_uses_verified_snapshot_during_path_aba(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "memory.db"
    decoy_path = tmp_path / "decoy.db"
    SQLiteMemoryLedger(path).remember(_record(value="original"))
    SQLiteMemoryLedger(decoy_path).remember(_record(value="decoy"))
    ledger = SQLiteMemoryLedger(path)
    real_open = os.open
    swapped = False

    def aba_open(target: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if target != path.name or swapped:
            return real_open(target, flags, *args, **kwargs)
        swapped = True
        held_path = tmp_path / "held-original.db"
        os.replace(path, held_path)
        os.replace(decoy_path, path)
        try:
            descriptor = real_open(target, flags, *args, **kwargs)
        finally:
            os.replace(path, decoy_path)
            os.replace(held_path, path)
        return descriptor

    monkeypatch.setattr(os, "open", aba_open)

    with pytest.raises(ValueError, match="changed during secure open"):
        ledger.recall(_query())


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory permissions are required")
def test_wal_mode_read_requires_no_directory_write_or_sidecars(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record())
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    finally:
        connection.close()
    before = _directory_digest(tmp_path)

    tmp_path.chmod(0o555)
    try:
        hits = ledger.recall(_query())
    finally:
        tmp_path.chmod(0o755)

    assert [hit.record.record_id for hit in hits] == ["record-1"]
    assert _directory_digest(tmp_path) == before


def test_recall_isolates_profiles_and_session_scoped_records(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    records = (
        _record("profile-global"),
        _record("session-a", session_id="session-a", value="oolong"),
        _record("session-b", session_id="session-b", value="coffee"),
        _record("other-profile", profile_id="profile-2", value="water"),
    )
    for record in records:
        ledger.remember(record)

    no_session = ledger.recall(_query())
    session_a = ledger.recall(_query(session_id="session-a"))
    other_profile = ledger.recall(_query(profile_id="profile-2"))

    assert [hit.record.record_id for hit in no_session] == ["profile-global"]
    assert {hit.record.record_id for hit in session_a} == {"profile-global", "session-a"}
    assert [hit.record.record_id for hit in other_profile] == ["other-profile"]


def test_recall_validity_interval_excludes_exact_expiry_boundary(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record(valid_until=_NOW))

    assert ledger.recall(_query(at=_NOW - timedelta(microseconds=1)))
    assert ledger.recall(_query(at=_NOW)) == ()


def test_lexical_recall_is_deterministic_bounded_and_explained(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record("older", key="breakfast", value="green tea", created_at=_NOW))
    ledger.remember(
        _record(
            "newer",
            key="afternoon",
            value="green tea with lemon",
            created_at=_NOW + timedelta(seconds=1),
        )
    )
    ledger.remember(_record("irrelevant", key="music", value="jazz"))
    query = _query(key=None, terms=("TEA",), limit=1)

    first = ledger.recall(query)

    assert first == ledger.recall(query)
    assert [hit.record.record_id for hit in first] == ["newer"]
    assert "term:tea" in first[0].why_recalled


def test_supersession_atomically_hides_the_old_active_record(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record("old", value="coffee"))
    newer = _record("new", value="tea", supersedes=("old",), created_at=_NOW + timedelta(seconds=1))

    assert ledger.remember(newer) is True

    hits = ledger.recall(_query())
    assert [hit.record.record_id for hit in hits] == ["new"]


def test_supersession_starts_at_successor_validity_and_never_resurrects_old(
    tmp_path: Path,
) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(
        _record(
            "old",
            value="coffee",
            created_at=_NOW - timedelta(days=2),
            valid_from=_NOW - timedelta(days=3),
        )
    )
    ledger.remember(
        _record(
            "new",
            value="tea",
            created_at=_NOW,
            valid_from=_NOW,
            valid_until=_NOW + timedelta(days=1),
            supersedes=("old",),
        )
    )

    before = ledger.recall(_query(at=_NOW - timedelta(microseconds=1)))
    active = ledger.recall(_query(at=_NOW))
    after_expiry = ledger.recall(_query(at=_NOW + timedelta(days=1)))

    assert [hit.record.record_id for hit in before] == ["old"]
    assert [hit.record.record_id for hit in active] == ["new"]
    assert after_expiry == ()


def test_deleting_superseder_does_not_resurrect_stale_target(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record("old", value="coffee"))
    ledger.remember(_record("new", value="tea", supersedes=("old",)))

    assert ledger.delete("new", "profile-1") is True

    assert ledger.recall(_query()) == ()


@pytest.mark.parametrize("target", ["missing", "cross-profile"])
def test_invalid_supersession_rolls_back_without_partial_insert(
    tmp_path: Path,
    target: str,
) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    if target == "cross-profile":
        ledger.remember(_record(target, profile_id="profile-2"))

    with pytest.raises(ValueError, match="supersed"):
        ledger.remember(_record("new", supersedes=(target,)))

    assert ledger.recall(_query(key=None, terms=(), kinds=())) == ()


def test_conflicts_return_one_active_record_per_distinct_canonical_value_and_session(
    tmp_path: Path,
) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record("same-old", value="cafe\u0301", created_at=_NOW))
    ledger.remember(_record("same-new", value="café", created_at=_NOW + timedelta(seconds=1)))
    ledger.remember(_record("session-conflict", value="tea", session_id="session-a"))

    assert ledger.conflicts("profile-1", "drink", at=_NOW + timedelta(seconds=2)) == ()
    conflicts = ledger.conflicts(
        "profile-1",
        "drink",
        at=_NOW + timedelta(seconds=2),
        session_id="session-a",
    )

    assert {hit.record.value for hit in conflicts} == {"café", "tea"}
    assert all("conflict:distinct_value" in hit.why_recalled for hit in conflicts)


def test_conflict_detection_considers_values_beyond_recall_result_cap(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    for index in range(51):
        ledger.remember(
            _record(
                f"conflict-{index:02d}",
                value="coffee" if index == 0 else "tea",
                created_at=_NOW + timedelta(seconds=index),
            )
        )

    conflicts = ledger.conflicts("profile-1", "drink", at=_NOW + timedelta(minutes=2))

    assert {hit.record.value for hit in conflicts} == {"coffee", "tea"}


def test_recall_is_sql_bounded_without_per_record_selects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    for index in range(60):
        ledger.remember(_record(f"bounded-{index:02d}", key=f"key-{index:02d}"))
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(database: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(database, *args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)

    hits = ledger.recall(_query(key=None, terms=(), limit=2))
    selects = [statement for statement in statements if "SELECT" in statement.upper()]

    assert len(hits) == 2
    assert len(selects) <= 3
    assert any("LIMIT 2" in statement.upper() for statement in selects)


def test_indexed_recall_stays_bounded_with_ten_thousand_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("bulk-00000", key="bulk key 00000"))
    connection = sqlite3.connect(path)
    try:
        rows = [
            (f"bulk-{index:05d}", f"bulk key {index:05d}", f"bulk key {index:05d}")
            for index in range(1, 10_000)
        ]
        connection.executemany(
            """
            INSERT INTO memory_records (
                record_id, profile_id, session_id, kind, memory_key, key_fold,
                value_json, confidence, created_at, valid_from, valid_until,
                evidence_source_kind, evidence_digest, evidence_observed_at,
                evidence_source_id, tags_json, supersedes_json, semantic_digest, deleted_at
            )
            SELECT ?, profile_id, session_id, kind, ?, ?,
                   value_json, confidence, created_at, valid_from, valid_until,
                   evidence_source_kind, evidence_digest, evidence_observed_at,
                   evidence_source_id, tags_json, supersedes_json, semantic_digest, NULL
            FROM memory_records WHERE record_id = 'bulk-00000'
            """,
            rows,
        )
        connection.executemany(
            """
            INSERT INTO memory_terms (record_id, profile_id, term)
            VALUES (?, 'profile-1', 'bulk')
            """,
            ((record_id,) for record_id, _key, _folded in rows),
        )
        connection.commit()
    finally:
        connection.close()
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(database: object, *args: object, **kwargs: object) -> sqlite3.Connection:
        traced = real_connect(database, *args, **kwargs)
        traced.set_trace_callback(statements.append)
        return traced

    monkeypatch.setattr(sqlite3, "connect", traced_connect)

    started = time.monotonic()
    hits = ledger.recall(_query(key=None, terms=("bulk",), limit=1))
    elapsed = time.monotonic() - started
    selects = [statement for statement in statements if "SELECT" in statement.upper()]

    assert len(hits) == 1
    assert len(selects) <= 3
    assert any("LIMIT 1" in statement.upper() for statement in selects)
    assert elapsed < 2.0


def test_recall_materializes_record_and_supersession_from_one_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("old", value="coffee"))
    ledger.remember(_record("new", value="tea", supersedes=("old",)))
    original_row_to_record = SQLiteMemoryLedger._row_to_record
    interleaved = False

    def interleaving_row_to_record(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> MemoryRecord:
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            SQLiteMemoryLedger(path).delete("old", "profile-1")
        return original_row_to_record(connection, row)

    monkeypatch.setattr(
        SQLiteMemoryLedger,
        "_row_to_record",
        staticmethod(interleaving_row_to_record),
    )

    hits = ledger.recall(_query())

    assert [hit.record.supersedes for hit in hits] == [("old",)]


def test_duplicate_id_is_idempotent_only_for_semantically_identical_record(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")

    assert ledger.remember(_record("duplicate")) is True
    assert ledger.remember(_record("duplicate", value="green te\u0061")) is False
    with pytest.raises(ValueError, match="record_id"):
        ledger.remember(_record("duplicate", value="coffee"))

    assert len(ledger.recall(_query())) == 1


@pytest.mark.parametrize("changed_value", [True, 1.0])
def test_duplicate_id_preserves_atomic_value_type(tmp_path: Path, changed_value: object) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record("typed-value", value=1))

    with pytest.raises(ValueError, match="record_id"):
        ledger.remember(_record("typed-value", value=changed_value))


def test_sql_injection_shaped_values_remain_data(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    profile = "p' OR 1=1 --"
    key = "x'); DROP TABLE memory_records; --"
    value = "Robert'); DELETE FROM memory_records; --"
    ledger.remember(_record(profile_id=profile, key=key, value=value))

    hits = ledger.recall(_query(profile_id=profile, key=key))

    assert [hit.record.value for hit in hits] == [value]
    assert "memory_records" in ledger.schema_columns()


def test_delete_is_profile_scoped_and_no_save_is_strict_noop(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record())

    assert ledger.delete("record-1", "wrong-profile") is False
    assert ledger.delete("record-1", "profile-1", no_save=True) is False
    assert ledger.recall(_query())
    assert ledger.delete("record-1", "profile-1") is True
    assert ledger.recall(_query()) == ()


def test_delete_removes_plaintext_value_from_current_ledger_files(tmp_path: Path) -> None:
    marker = "DELETE_ME_PLAINTEXT_" + ("z" * 512)
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    ledger.remember(_record(value=marker))
    marker_bytes = marker.encode()

    assert any(marker_bytes in path.read_bytes() for path in tmp_path.iterdir() if path.is_file())

    assert ledger.delete("record-1", "profile-1") is True

    assert not any(
        marker_bytes in path.read_bytes() for path in tmp_path.iterdir() if path.is_file()
    )


def test_delete_tombstone_prevents_record_id_reuse(tmp_path: Path) -> None:
    ledger = SQLiteMemoryLedger(tmp_path / "memory.db")
    original = _record("deleted-id", value="sensitive")
    ledger.remember(original)
    ledger.delete("deleted-id", "profile-1")

    assert ledger.remember(original) is False
    with pytest.raises(ValueError, match="record_id"):
        ledger.remember(_record("deleted-id", value="different"))


def test_permitted_write_cleans_fsynced_crash_orphan(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    marker = "ORPHAN_WRITE_SECRET_" + ("w" * 256)
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    orphan = _leave_crash_orphan(path, marker)
    held_orphan = os.open(orphan, os.O_RDONLY)

    try:
        assert ledger.remember(_record("after-crash", key="after-crash")) is True
        assert os.read(held_orphan, 1) == b""
    finally:
        os.close(held_orphan)

    assert not orphan.exists()
    assert not any(
        marker.encode() in entry.read_bytes() for entry in tmp_path.iterdir() if entry.is_file()
    )


def test_permitted_write_rejects_lock_path_aba_after_exclusive_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    lock_path = tmp_path / ".memory.db.lock"
    held_lock = tmp_path / "held-lock"
    original_acquire = SQLiteMemoryLedger._acquire_flock
    swapped = False

    def swap_after_acquire(descriptor: int, *, exclusive: bool) -> None:
        nonlocal swapped
        original_acquire(descriptor, exclusive=exclusive)
        if exclusive and not swapped:
            swapped = True
            os.replace(lock_path, held_lock)
            lock_path.write_bytes(b"")
            lock_path.chmod(0o600)

    monkeypatch.setattr(
        SQLiteMemoryLedger,
        "_acquire_flock",
        staticmethod(swap_after_acquire),
    )
    before = path.read_bytes()

    with pytest.raises(ValueError, match="lock.*changed"):
        ledger.remember(_record("must-not-write", key="must-not-write"))

    assert path.read_bytes() == before


def test_permitted_delete_cleans_fsynced_crash_orphan(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    marker = "ORPHAN_DELETE_SECRET_" + ("d" * 256)
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    orphan = _leave_crash_orphan(path, marker)

    assert ledger.delete("base", "profile-1") is True

    assert not orphan.exists()
    assert not any(
        marker.encode() in entry.read_bytes() for entry in tmp_path.iterdir() if entry.is_file()
    )


@pytest.mark.parametrize(
    "artifact_kind",
    ["symlink", "fifo", "unsafe-file", "hardlink"],
)
def test_permitted_mutation_fails_closed_on_suspicious_matching_temp(
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    artifact = tmp_path / f".{path.name}.tmp-{'0' * 24}"
    user_file = tmp_path / "user-owned.txt"
    user_file.write_text("must survive")
    user_file.chmod(0o600)
    if artifact_kind == "symlink":
        artifact.symlink_to(user_file)
    elif artifact_kind == "fifo":
        os.mkfifo(artifact, 0o600)
    elif artifact_kind == "hardlink":
        os.link(user_file, artifact)
    elif artifact_kind == "unsafe-file":
        artifact.write_text("not a ledger image")
        artifact.chmod(0o644)
    artifact_details = artifact.lstat()
    before = _directory_digest(tmp_path)

    with pytest.raises(ValueError):
        ledger.remember(_record("must-not-write", key="must-not-write"))

    after_details = artifact.lstat()
    assert (after_details.st_dev, after_details.st_ino, after_details.st_mode) == (
        artifact_details.st_dev,
        artifact_details.st_ino,
        artifact_details.st_mode,
    )
    assert user_file.read_text() == "must survive"
    assert _directory_digest(tmp_path) == before


@pytest.mark.parametrize("contents", [b"", b"partial crash bytes"])
def test_permitted_write_cleans_incomplete_exact_name_orphan(
    tmp_path: Path,
    contents: bytes,
) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    orphan = tmp_path / f".{path.name}.tmp-{'1' * 24}"
    orphan.write_bytes(contents)
    orphan.chmod(0o600)

    assert ledger.remember(_record("after-incomplete", key="after-incomplete")) is True

    assert not orphan.exists()


def test_permitted_write_ignores_temp_namespace_near_misses(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    prefix = f".{path.name}.tmp-"
    names = (
        prefix + ("a" * 23),
        prefix + ("a" * 25),
        prefix + ("g" * 24),
        prefix + ("a" * 24) + ".extra",
        ".another.db.tmp-" + ("a" * 24),
    )
    artifacts = [tmp_path / name for name in names]
    for artifact in artifacts:
        artifact.write_text(f"user file: {artifact.name}")
        artifact.chmod(0o600)
    before = {artifact: artifact.read_bytes() for artifact in artifacts}

    assert ledger.remember(_record("after-near-miss", key="after-near-miss")) is True

    assert {artifact: artifact.read_bytes() for artifact in artifacts} == before


def test_reads_and_no_save_operations_do_not_clean_crash_orphan(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    marker = "ORPHAN_ZERO_WRITE_" + ("n" * 256)
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record("base"))
    orphan = _leave_crash_orphan(path, marker)
    before = _directory_digest(tmp_path)

    assert ledger.recall(_query())
    assert ledger.remember(_record("no-save"), no_save=True) is False
    assert ledger.delete("base", "profile-1", no_save=True) is False

    assert orphan.exists()
    assert _directory_digest(tmp_path) == before


def test_multiple_instances_and_threaded_writers_complete_without_lost_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.db"

    def write(index: int) -> bool:
        return SQLiteMemoryLedger(path).remember(
            _record(f"record-{index:02d}", key=f"key-{index:02d}")
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(write, range(18)))

    hits = SQLiteMemoryLedger(path).recall(_query(key=None, terms=(), limit=50))
    assert all(results)
    assert len(hits) == 18


@pytest.mark.skipif(os.name != "posix", reason="POSIX flock is required")
def test_multiple_process_writers_complete_without_lost_records(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=_process_write, args=(os.fspath(path), index)) for index in range(8)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)

    assert all(process.exitcode == 0 for process in processes)
    assert len(SQLiteMemoryLedger(path).recall(_query(key=None, terms=(), limit=50))) == 8


def test_corrupt_and_oversized_images_fail_closed(tmp_path: Path) -> None:
    corrupt_path = tmp_path / "corrupt.db"
    corrupt = SQLiteMemoryLedger(corrupt_path)
    corrupt.remember(_record())
    corrupt_path.write_bytes(b"not a SQLite image")

    with pytest.raises(ValueError, match="corrupt"):
        corrupt.recall(_query())

    oversized_path = tmp_path / "oversized.db"
    oversized = SQLiteMemoryLedger(oversized_path)
    oversized.remember(_record())
    with oversized_path.open("r+b") as image:
        image.truncate((64 * 1_024 * 1_024) + 1)

    with pytest.raises(ValueError, match="size limit"):
        oversized.recall(_query())


def test_hardlinked_image_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    ledger = SQLiteMemoryLedger(path)
    ledger.remember(_record())
    os.link(path, tmp_path / "alias.db")

    with pytest.raises(ValueError, match="hardlink"):
        ledger.recall(_query())


def test_ledger_rejects_symlink_nonregular_and_closed_use(tmp_path: Path) -> None:
    target = tmp_path / "target.db"
    target.write_bytes(b"")
    symlink = tmp_path / "linked.db"
    symlink.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        SQLiteMemoryLedger(symlink)
    with pytest.raises(ValueError, match="regular"):
        SQLiteMemoryLedger(tmp_path)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SQLiteMemoryLedger(linked_parent / "nested.db")

    ledger = SQLiteMemoryLedger(tmp_path / "closed.db")
    ledger.close()
    with pytest.raises(RuntimeError, match="closed"):
        ledger.recall(_query())
