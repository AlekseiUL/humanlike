"""Adversarial, migration and real concurrent revocation checks on synthetic stores."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from humanlike_agent.memory import (
    Evidence,
    MemoryKind,
    MemoryRecord,
    RecallQuery,
    SQLiteMemoryLedger,
)
from humanlike_agent.personal import Candidate, HumanEvent, PersonalMemory

pytestmark = pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def setup_memory(path):
    ledger = SQLiteMemoryLedger(path)
    events = {}
    memory = PersonalMemory(
        ledger,
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        authorize=lambda *_: True,
        resolve=events.get,
    )

    def event(n, text="Remember my preference: tone = concise", **kw):
        e = HumanEvent(str(n), "owner", "profile", "chat", n, NOW, text, **kw)
        events[e.event_id] = e
        return e.event_id

    return ledger, memory, events, event


def test_additive_migration_backward_core_and_plaintext_erasure(tmp_path):
    path = tmp_path / "legacy.sqlite"
    ledger, memory, _, event = setup_memory(path)
    old = MemoryRecord(
        "legacy",
        "profile",
        MemoryKind.FACT,
        "legacy",
        "synthetic",
        1.0,
        NOW,
        NOW,
        Evidence("fixture", hashlib.sha256(b"fixture").hexdigest(), NOW),
    )
    ledger.remember(old)
    original_columns = ledger.schema_columns()
    before = path.read_bytes()
    assert memory.inspect() == ()
    assert path.read_bytes() == before  # reads do not migrate storage
    memory.enable()
    rid = memory.capture(event(1, "Remember my interest: hobby = glass harmonica")).record_id
    assert ledger.schema_columns() == original_columns
    assert ledger.recall(RecallQuery("profile", NOW))[0].record == old
    memory.disable()
    assert memory.recall("hobby") == ()
    assert memory.inspect()[0].record.value == "glass harmonica"
    assert memory.forget(rid)
    assert b"glass harmonica" not in path.read_bytes()
    assert b"hobby" not in path.read_bytes()
    assert not memory.inspect()
    memory.enable()
    assert memory.capture("1").status == "replayed"
    assert ledger.quick_check() == "ok"
    ledger.close()


@pytest.mark.parametrize("action", ["forget", "disable"])
def test_concurrent_second_instance_revokes_inflight(tmp_path, action):
    path = tmp_path / "race.sqlite"
    ledger, m, events, event = setup_memory(path)
    m.enable()
    rid = m.capture(event(1)).record_id
    ref = event(2)
    started, release = Event(), Event()

    def delayed(candidate):
        started.set()
        assert release.wait(5)
        return candidate.candidate

    with SQLiteMemoryLedger(path) as other_ledger:
        other = PersonalMemory(
            other_ledger,
            owner_id="owner",
            profile_id="profile",
            session_id="chat",
            authorize=lambda *_: True,
            resolve=events.get,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(m.capture, ref, extractor=delayed)
            assert started.wait(5)
            if action == "forget":
                assert other.forget(rid)
            else:
                other.disable()
            release.set()
            assert future.result(timeout=5).status == "revoked"
        other.enable()
        assert other.capture(ref).status == "replayed"
    ledger.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_id", "other"),
        ("session_id", "other"),
        ("owner_id", "other"),
        ("origin", "internal"),
        ("origin", "tool"),
        ("origin", "heartbeat"),
        ("asserted_by_owner", False),
        ("no_save", True),
    ],
)
def test_metadata_fences_do_not_call_extractor(tmp_path, field, value):
    ledger, m, events, event = setup_memory(tmp_path / "m.sqlite")
    m.enable()
    ref = event(1)
    events[ref] = replace(events[ref], **{field: value})

    def forbidden(_):
        pytest.fail("extractor must not run")

    assert m.capture(ref, extractor=forbidden).status == "denied"
    assert m.inspect() == ()
    ledger.close()


def test_stale_timestamp_wrong_target_scope_and_future(tmp_path):
    ledger, m, events, event = setup_memory(tmp_path / "m.sqlite")
    m.enable()
    rid = m.capture(event(1)).record_id
    ref = event(2, "Change my preference: tone = detailed", target_id=rid, condition="teaching")
    assert m.capture(ref).status == "invalid_target"
    ref = event(3, "Correct my preference: tone = detailed", target_id=rid)
    events[ref] = replace(events[ref], observed_at=NOW - timedelta(days=1))
    assert m.correct(ref).status == "stale"
    ref = event(4)
    events[ref] = replace(events[ref], observed_at=datetime.now(UTC) + timedelta(days=1))
    assert m.capture(ref).status == "denied"
    assert (
        m.capture(event(5, "Confirm my preference: tone = detailed", target_id=rid)).status
        == "invalid"
    )
    assert (
        m.capture(event(6, "Correct my preference: tone = neutral", target_id=rid)).status
        == "stored"
    )
    assert m.recall("tone")[0].record.value == "neutral"
    ledger.close()


def test_full_group_stays_forgettable_and_inspection_pages(tmp_path):
    ledger, m, _, event = setup_memory(tmp_path / "m.sqlite")
    m.enable()
    rid = None
    for n in range(1, 257):
        result = m.capture(event(n))
        assert result.status == "stored"
        rid = rid or result.record_id
    assert m.capture(event(257)).status == "group_full"
    page = m.inspect(limit=50)
    assert len(page) == 50
    assert m.inspect(after=page[-1].sequence)[0].sequence == 51
    assert m.forget(rid)
    assert not m.inspect()
    ledger.close()


def test_extractor_schema_and_storage_failure_no_fake_success(tmp_path, monkeypatch):
    ledger, m, _, event = setup_memory(tmp_path / "m.sqlite")
    m.enable()
    assert m.capture(event(1), extractor=lambda _: {"value": "fake"}).status == "invalid"
    with pytest.raises(ValueError):
        Candidate("remember", "psychology", "trait", "invented")
    ref = event(2)

    def broken(_):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(ledger, "_persist_snapshot", broken)
    with pytest.raises(OSError):
        m.capture(ref)
    assert not m.inspect()
    ledger.close()


def test_profile_wide_scope_requires_explicit_host_choice(tmp_path):
    ledger, m, events, event = setup_memory(tmp_path / "m.sqlite")
    m.enable()
    m.capture(event(1))
    global_memory = PersonalMemory(
        ledger,
        owner_id="owner",
        profile_id="profile",
        session_id=None,
        authorize=lambda *_: True,
        resolve=events.get,
    )
    assert not global_memory.inspect()
    global_memory.enable()
    global_memory.capture(event(2, "Remember my goal: study = learn geometry"))
    assert global_memory.recall("study")
    assert not m.recall("study")
    ledger.close()
