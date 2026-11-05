"""Opt-in explicit personal memory over the existing ledger, without network I/O.

The host is the authority: resolve must return authenticated transport metadata,
not deserialize fields supplied by a model or message. Python callbacks are a
trusted integration boundary, not a sandbox against malicious host code.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from .memory import (
    Evidence,
    MemoryKind,
    MemoryRecord,
    SQLiteMemoryLedger,
    _canonical_text,
    _time_text,
    _utc,
)

# Only a complete, explicit command is accepted. Quotes, prose surrounding the
# command, role markers and multiline instructions are not an authority channel.
_COMMAND = re.compile(
    r"(Remember|Change|Correct|Confirm) my (preference|goal|interest): "
    r"([a-z][a-z0-9_ -]{0,63}) = ([^\r\n]{1,256})\Z",
    re.IGNORECASE,
)
_NON_DURABLE_OR_AUTHORITY = re.compile(
    r"\b(?:this (?:answer|reply|turn|task)|today|right now|temporary|"
    r"(?:ignore|disregard|override) .{0,40}(?:instructions|rules|policy)|"
    r"(?:disable|bypass) .{0,24}(?:safety|consent|authorization)|"
    r"system prompt|without consent|сегодня|сейчас|без согласия|"
    r"игнорируй .{0,32}(?:инструкции|правила))\b",
    re.IGNORECASE,
)
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS personal_policy (
        namespace TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
        epoch INTEGER NOT NULL, watermark INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS personal_events (
        namespace TEXT NOT NULL, event_hash TEXT NOT NULL, sequence INTEGER NOT NULL,
        PRIMARY KEY(namespace, event_hash))""",
    """CREATE TABLE IF NOT EXISTS personal_records (
        record_id TEXT PRIMARY KEY REFERENCES memory_records(record_id),
        namespace TEXT NOT NULL, domain TEXT NOT NULL, condition_text TEXT NOT NULL,
        relation TEXT NOT NULL, target_id TEXT, sequence INTEGER NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS personal_scope
        ON personal_records(namespace, domain, condition_text, sequence)""",
)


def _digest(*parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _label(value: str, name: str) -> str:
    return _canonical_text(value, name, 128)


@dataclass(frozen=True, slots=True, repr=False)
class HumanEvent:
    """Host-attested event; sequence is monotonic within the configured scope.

    domain/condition and target_id come from the host's explicit UI controls.
    asserted_by_owner must be false for quotes, fiction, forwarded or internal
    messages. no_save applies before any extractor is called.
    """

    event_id: str
    owner_id: str
    profile_id: str
    session_id: str
    sequence: int
    observed_at: datetime
    text: str
    origin: str = "human"
    asserted_by_owner: bool = True
    no_save: bool = False
    domain: str = "general"
    condition: str = "always"
    target_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "owner_id",
            "profile_id",
            "session_id",
            "origin",
            "domain",
            "condition",
        ):
            if _label(getattr(self, name), name) != getattr(self, name):
                raise ValueError("event labels must be canonical")
        if self.target_id is not None:
            _label(self.target_id, "target_id")
        if type(self.sequence) is not int or not 0 < self.sequence < 2**63:
            raise ValueError("sequence must be a positive signed 64-bit integer")
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        if not isinstance(self.text, str) or not 0 < len(self.text) <= 8192:
            raise ValueError("text must contain 1..8192 characters")
        if type(self.no_save) is not bool or type(self.asserted_by_owner) is not bool:
            raise TypeError("event policy flags must be booleans")


@dataclass(frozen=True, slots=True, repr=False)
class Candidate:
    """One bounded explicit proposition; extraction never grants permission."""

    operation: str
    kind: str
    key: str
    value: str

    def __post_init__(self) -> None:
        if self.operation not in {"remember", "change", "correct", "confirm"}:
            raise ValueError("unsupported candidate operation")
        if self.kind not in {"preference", "goal", "interest"}:
            raise ValueError("unsupported candidate kind")
        if _canonical_text(self.key, "key", 64) != self.key:
            raise ValueError("key must be canonical")
        if _canonical_text(self.value, "value", 256) != self.value:
            raise ValueError("value must be canonical")

    @classmethod
    def from_json(cls, text: str) -> Candidate:
        """Strict, bounded model-response decoder with no permission fields."""
        if not isinstance(text, str) or len(text) > 2048:
            raise ValueError("candidate JSON exceeds bounds")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate candidate field")
                result[key] = value
            return result

        data = json.loads(text, object_pairs_hook=unique)
        if (
            not isinstance(data, dict)
            or set(data) != {"operation", "kind", "key", "value"}
            or any(type(v) is not str for v in data.values())
        ):
            raise ValueError("invalid candidate schema")
        return cls(**data)


@dataclass(frozen=True, slots=True, repr=False)
class ExtractionRequest:
    """Provider-neutral bounded input; only the explicit command, never history.

    Return a Candidate (or Candidate.from_json on a provider response). The code
    verifies equivalence with the explicit request, so hallucinated changes fail.
    """

    text: str
    candidate: Candidate


def explicit_candidate(event: HumanEvent) -> Candidate | None:
    """Deterministic English command parser; not a natural-language model."""
    match = _COMMAND.fullmatch(event.text)
    if match is None:
        return None
    operation, kind, key, value = match.groups()
    if _NON_DURABLE_OR_AUTHORITY.search(key + " " + value):
        return None
    if key.strip().lower() in {"mood", "personality", "psychology", "system", "policy"}:
        return None
    try:
        value = _canonical_text(value, "value", 256)
    except (TypeError, ValueError):
        return None
    if any(mark in value for mark in ('"', "`", "<", ">", "{", "}")):
        return None
    return Candidate(operation.lower(), kind.lower(), key.strip().lower(), value)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    status: str
    record_id: str | None = None
    relation: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class PersonalFact:
    record: MemoryRecord
    domain: str
    condition: str
    relation: str
    target_id: str | None
    sequence: int


class PersonalMemory:
    """Synchronous capture and owner controls with durable revocation/replay fences.

    session_id is required: None is an explicit host choice for profile-wide
    memory. Use a separate instance per authorized scope. All APIs call authorize;
    never expose these callbacks or constructor arguments to untrusted tools.
    """

    def __init__(
        self,
        ledger: SQLiteMemoryLedger,
        *,
        owner_id: str,
        profile_id: str,
        session_id: str | None,
        authorize: Callable[..., bool],
        resolve: Callable[[str], HumanEvent | None],
    ) -> None:
        if not isinstance(ledger, SQLiteMemoryLedger):
            raise TypeError("ledger must be SQLiteMemoryLedger")
        if not callable(authorize) or not callable(resolve):
            raise TypeError("host authorization and resolver are required")
        self._ledger = ledger
        self._owner = _label(owner_id, "owner_id")
        self._profile = _label(profile_id, "profile_id")
        self._session = _label(session_id, "session_id") if session_id is not None else None
        self._namespace = "personal:" + _digest(self._owner, self._profile, self._session)
        self._authorize = authorize
        self._resolve = resolve

    @property
    def scope(self) -> tuple[str, str, str | None]:
        """Host binding, not authority inferred from a message."""
        return self._owner, self._profile, self._session

    def _authorized(self, operation: str) -> bool:
        try:
            return self._authorize(self._owner, self._profile, self._session, operation) is True
        except Exception:
            return False

    def _require(self, operation: str) -> None:
        if not self._authorized(operation):
            raise PermissionError("host authorization denied")

    @contextmanager
    def _transaction(self) -> Iterator:
        self._ledger._ensure_open()
        with self._ledger._write_snapshot() as snapshot:
            db = snapshot.connection
            db.execute("BEGIN IMMEDIATE")
            self._ledger._ensure_schema(db)
            for statement in _SCHEMA:
                db.execute(statement)
            try:
                yield db
                db.commit()
                db.execute("VACUUM")
                self._ledger._persist_snapshot(snapshot)
            except BaseException:
                if db.in_transaction:
                    db.rollback()
                raise

    def _policy(self, db) -> tuple[bool, int, int]:
        if (
            db is None
            or not db.execute("SELECT 1 FROM sqlite_master WHERE name='personal_policy'").fetchone()
        ):
            return False, 0, 0
        row = db.execute(
            "SELECT enabled, epoch, watermark FROM personal_policy WHERE namespace=?",
            (self._namespace,),
        ).fetchone()
        return (bool(row[0]), row[1], row[2]) if row else (False, 0, 0)

    def _current_policy(self) -> tuple[bool, int, int]:
        self._ledger._ensure_open()
        db = self._ledger._read_connection()
        try:
            return self._policy(db)
        finally:
            if db is not None:
                db.close()

    def _set_consent(self, enabled: bool) -> None:
        self._require("enable" if enabled else "disable")
        with self._transaction() as db:
            _, epoch, watermark = self._policy(db)
            db.execute(
                "INSERT OR REPLACE INTO personal_policy VALUES (?, ?, ?, ?)",
                (self._namespace, int(enabled), epoch + 1, watermark),
            )

    def enable(self) -> None:
        """Record host-authorized owner consent. Each call revokes pending work."""
        self._set_consent(True)

    def disable(self) -> None:
        """Stop capture/recall and revoke in-flight work; retain inspectable records."""
        self._set_consent(False)

    def _event(self, ref: str) -> HumanEvent | None:
        try:
            event = self._resolve(ref)
        except Exception:
            return None
        if (
            type(event) is not HumanEvent
            or event.event_id != ref
            or event.owner_id != self._owner
            or event.profile_id != self._profile
            or (self._session is not None and event.session_id != self._session)
            or event.origin != "human"
            or not event.asserted_by_owner
            or event.no_save
        ):
            return None
        if event.observed_at > datetime.now(UTC):
            return None
        return event

    def capture(
        self,
        event_id: str,
        *,
        no_save: bool = False,
        extractor: Callable[[ExtractionRequest], Candidate] | None = None,
    ) -> CaptureResult:
        """Capture one explicit atom, optionally round-tripping an untrusted proposer.

        The proposer receives only the explicit bounded command, not a full
        conversation. It may approve/return that exact schema/value, not invent
        enduring facts or change authority/scope. Failures consume the event so a
        host must issue a fresh explicit event rather than silently retry a save.
        """
        if type(no_save) is not bool:
            raise TypeError("no_save must be boolean")
        if no_save or not self._authorized("capture"):
            return CaptureResult("denied")
        ref = _label(event_id, "event_id")
        enabled, _, _ = self._current_policy()
        if not enabled:
            return CaptureResult("disabled")
        event = self._event(ref)
        if event is None:
            return CaptureResult("denied")
        proposed = explicit_candidate(event)
        if proposed is None:
            return CaptureResult("not_explicit")
        event_hash = _digest(ref)
        # Reserve before dispatch: late results and restarts cannot replay an old
        # event after forget/disable. No raw text is kept in this reservation.
        with self._transaction() as db:
            enabled, epoch, watermark = self._policy(db)
            if not enabled:
                return CaptureResult("disabled")
            if db.execute(
                "SELECT 1 FROM personal_events WHERE namespace=? AND event_hash=?",
                (self._namespace, event_hash),
            ).fetchone():
                return CaptureResult("replayed")
            if event.sequence <= watermark:
                return CaptureResult("stale")
            db.execute(
                "INSERT INTO personal_events VALUES (?, ?, ?)",
                (self._namespace, event_hash, event.sequence),
            )
            db.execute(
                "UPDATE personal_policy SET watermark=? WHERE namespace=?",
                (event.sequence, self._namespace),
            )
        try:
            candidate = (
                proposed
                if extractor is None
                else extractor(ExtractionRequest(event.text, proposed))
            )
        except Exception:
            return CaptureResult("extractor_failed")
        if type(candidate) is not Candidate or candidate != proposed:
            return CaptureResult("invalid")
        if not self._authorized("capture") or self._event(ref) != event:
            return CaptureResult("revoked")
        with self._transaction() as db:
            enabled, current_epoch, watermark = self._policy(db)
            if not enabled or current_epoch != epoch:
                return CaptureResult("revoked")
            if watermark != event.sequence:
                return CaptureResult("stale")
            return self._store(db, event, candidate)

    def _facts(self, db, *, after: int = 0, limit: int = 50) -> tuple[PersonalFact, ...]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='personal_records'").fetchone():
            return ()
        rows = db.execute(
            """SELECT r.*, p.domain, p.condition_text, p.relation,
            p.target_id, p.sequence FROM personal_records p JOIN memory_records r
            ON r.record_id=p.record_id WHERE p.namespace=? AND r.deleted_at IS NULL
            AND p.sequence>? ORDER BY p.sequence LIMIT ?""",
            (self._namespace, after, limit),
        ).fetchall()
        return tuple(
            PersonalFact(
                self._ledger._row_to_record(db, row),
                row["domain"],
                row["condition_text"],
                row["relation"],
                row["target_id"],
                row["sequence"],
            )
            for row in rows
        )

    def _group(self, db, key: str, domain: str, condition: str) -> tuple[PersonalFact, ...]:
        # Bounded and fail closed, rather than arbitrarily forgetting conflicts.
        rows = db.execute(
            """SELECT r.*, p.domain, p.condition_text, p.relation,
            p.target_id, p.sequence FROM personal_records p JOIN memory_records r
            ON r.record_id=p.record_id WHERE p.namespace=? AND p.domain=?
            AND p.condition_text=? AND r.key_fold=? AND r.deleted_at IS NULL
            ORDER BY p.sequence LIMIT 257""",
            (self._namespace, domain, condition, key.casefold()),
        ).fetchall()
        if len(rows) > 256:
            raise ValueError("memory group limit reached; inspect and forget before adding")
        return tuple(
            PersonalFact(
                self._ledger._row_to_record(db, row),
                row["domain"],
                row["condition_text"],
                row["relation"],
                row["target_id"],
                row["sequence"],
            )
            for row in rows
        )

    @staticmethod
    def _active(facts: tuple[PersonalFact, ...]) -> tuple[PersonalFact, ...]:
        replaced = {f.target_id for f in facts if f.relation in {"supersedes", "corrects"}}
        return tuple(
            f for f in facts if f.record.record_id not in replaced and f.relation != "confirms"
        )

    def _store(self, db, event: HumanEvent, candidate: Candidate) -> CaptureResult:
        facts = self._group(db, candidate.key, event.domain, event.condition)
        if len(facts) >= 256:
            return CaptureResult("group_full")
        active = self._active(facts)
        target = next((f for f in active if f.record.record_id == event.target_id), None)
        if facts and event.observed_at < max(f.record.evidence.observed_at for f in facts):
            return CaptureResult("stale")
        if candidate.operation != "remember":
            if target is None or target.record.tags != (candidate.kind,):
                return CaptureResult("invalid_target")
            if candidate.operation == "confirm" and candidate.value != target.record.value:
                return CaptureResult("invalid")
            if candidate.operation == "change" and candidate.value == target.record.value:
                return CaptureResult("invalid")
            relation = {"change": "supersedes", "correct": "corrects", "confirm": "confirms"}[
                candidate.operation
            ]
        else:
            if event.target_id is not None:
                return CaptureResult("invalid_target")
            same = next(
                (
                    f
                    for f in active
                    if f.record.value == candidate.value and f.record.tags == (candidate.kind,)
                ),
                None,
            )
            relation = "confirms" if same else "contradicts" if active else "asserts"
            target = same
        target_id = target.record.record_id if target else None
        now = max(datetime.now(UTC), event.observed_at)
        record_id = "pm:" + _digest(self._namespace, event.event_id)
        record = MemoryRecord(
            record_id,
            self._namespace,
            MemoryKind.PREFERENCE if candidate.kind == "preference" else MemoryKind.FACT,
            candidate.key,
            candidate.value,
            1.0,
            now,
            event.observed_at,
            Evidence("authorized_human", _digest(event.text), event.observed_at, event.event_id),
            session_id=self._session,
            supersedes=(target_id,) if relation in {"supersedes", "corrects"} and target_id else (),
            tags=(candidate.kind,),
        )
        if record.supersedes:
            self._ledger._validate_supersessions(db, record)
        self._ledger._insert_record(db, record)
        db.execute(
            "INSERT INTO personal_records VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record_id,
                self._namespace,
                event.domain,
                event.condition,
                relation,
                target_id,
                event.sequence,
            ),
        )
        return CaptureResult("stored", record_id, relation)

    def inspect(self, *, after: int = 0, limit: int = 50) -> tuple[PersonalFact, ...]:
        """Page all versions/relations in this scope using the last sequence cursor."""
        self._require("inspect")
        self._ledger._ensure_open()
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("invalid inspection bounds")
        db = self._ledger._read_connection()
        if db is None:
            return ()
        try:
            return self._facts(db, after=after, limit=limit)
        finally:
            db.close()

    def recall(
        self, key: str, *, domain: str = "general", condition: str = "always"
    ) -> tuple[PersonalFact, ...]:
        """Exact scoped recall; unresolved contradictory values return no confident hit."""
        self._require("recall")
        self._ledger._ensure_open()
        key, domain, condition = (
            _label(key, "key"),
            _label(domain, "domain"),
            _label(condition, "condition"),
        )
        db = self._ledger._read_connection()
        if db is None:
            return ()
        try:
            if not self._policy(db)[0]:
                return ()
            active = self._active(self._group(db, key, domain, condition))
            if len({(f.record.value, f.record.tags) for f in active}) != 1:
                return ()
            return active[:1]
        finally:
            db.close()

    def correct(self, event_id: str) -> CaptureResult:
        """Apply a fresh host-authorized 'Correct my ...' event with an explicit target."""
        event = self._event(_label(event_id, "event_id"))
        proposal = explicit_candidate(event) if event else None
        if proposal is None or proposal.operation != "correct":
            return CaptureResult("invalid")
        return self.capture(event_id)

    def forget(self, record_id: str) -> bool:
        """Erase the entire key/domain/condition lineage and revoke pending captures.

        Minimal opaque replay tombstones remain; host archives, providers, backups
        and physical media copies cannot be erased by this library.
        """
        self._require("forget")
        record_id = _label(record_id, "record_id")
        with self._transaction() as db:
            enabled, epoch, watermark = self._policy(db)
            db.execute(
                "INSERT OR REPLACE INTO personal_policy VALUES (?, ?, ?, ?)",
                (self._namespace, int(enabled), epoch + 1, watermark),
            )
            row = db.execute(
                """SELECT r.memory_key, p.domain, p.condition_text
                FROM personal_records p JOIN memory_records r ON r.record_id=p.record_id
                WHERE p.namespace=? AND p.record_id=? AND r.deleted_at IS NULL""",
                (self._namespace, record_id),
            ).fetchone()
            if row is None:
                return False
            group = self._group(db, *row)
            # Keep the core ledger's tombstone contract, without any atom plaintext.
            for fact in group:
                rid = fact.record.record_id
                db.execute("DELETE FROM memory_terms WHERE record_id=?", (rid,))
                db.execute("DELETE FROM personal_records WHERE record_id=?", (rid,))
                db.execute(
                    """UPDATE memory_records SET kind=NULL, memory_key=NULL,
                    key_fold=NULL, value_json=NULL, confidence=NULL, created_at=NULL,
                    valid_from=NULL, valid_until=NULL, evidence_source_kind=NULL,
                    evidence_digest=NULL, evidence_observed_at=NULL, evidence_source_id=NULL,
                    tags_json=NULL, supersedes_json=NULL, deleted_at=? WHERE record_id=?""",
                    (_time_text(datetime.now(UTC)), rid),
                )
            return True
