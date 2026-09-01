"""Evidence-aware, privacy-minimal SQLite memory storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Final

try:
    import fcntl
except ImportError:  # pragma: no cover - the backend is explicitly POSIX-only
    fcntl = None  # type: ignore[assignment]

_MAX_ID: Final = 128
_MAX_SOURCE_KIND: Final = 64
_MAX_KEY: Final = 256
_MAX_VALUE: Final = 4_096
_MAX_TAG: Final = 64
_MAX_TAGS: Final = 16
_MAX_SUPERSEDES: Final = 32
_MAX_TERMS: Final = 8
_MAX_RECALL: Final = 50
_MAX_RECORD_TERMS: Final = 128
_MAX_IMAGE_BYTES: Final = 64 * 1_024 * 1_024
_MAX_ORPHAN_TEMPS: Final = 64
_LOCK_TIMEOUT_SECONDS: Final = 30.0
_HEX_DIGEST = re.compile(r"[0-9a-fA-F]{64}\Z")
_TEMP_SUFFIX = re.compile(r"[0-9a-f]{24}\Z")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_FORBIDDEN_BIDI = frozenset({"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})
_TABLES: Final = ("memory_records", "memory_supersessions", "memory_terms")
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}


class MemoryKind(StrEnum):
    """A small, portable taxonomy for durable memory atoms."""

    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    BOUNDARY = "boundary"
    RULE = "rule"
    PROMISE = "promise"


def _canonical_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        or unicodedata.bidirectional(character) in _FORBIDDEN_BIDI
        for character in normalized
    ):
        raise ValueError(f"{field} contains a forbidden control, format, or bidi character")
    canonical = normalized.strip()
    if not canonical:
        raise ValueError(f"{field} must not be empty")
    if len(canonical) > limit:
        raise ValueError(f"{field} exceeds its size limit")
    return canonical


def _optional_text(value: object, field: str, limit: int) -> str | None:
    if value is None:
        return None
    return _canonical_text(value, field, limit)


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must have a timezone")
    return value.astimezone(UTC)


def _atom(value: object) -> str | int | float | bool:
    if isinstance(value, str):
        return _canonical_text(value, "value atom", _MAX_VALUE)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > (2**63 - 1):
            raise ValueError("value atom integer is out of bounds")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("value atom float must be finite")
        return 0.0 if value == 0 else value
    raise TypeError("value atom must be a string, integer, finite float, or boolean")


def _string_tuple(
    values: object,
    field: str,
    *,
    item_limit: int,
    count_limit: int,
    case_insensitive: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{field} must be a tuple or list")
    if len(values) > count_limit:
        raise ValueError(f"{field} exceeds its maximum count")
    canonical = [_canonical_text(value, field, item_limit) for value in values]
    by_identity: dict[str, str] = {}
    for value in canonical:
        identity = value.casefold() if case_insensitive else value
        by_identity.setdefault(identity, value)
    return tuple(by_identity[key] for key in sorted(by_identity))


def _kind(value: object) -> MemoryKind:
    if isinstance(value, MemoryKind):
        return value
    if isinstance(value, str):
        try:
            return MemoryKind(value)
        except ValueError as error:
            raise ValueError("kind is not a supported memory kind") from error
    raise TypeError("kind must be a MemoryKind")


def _kinds(values: object) -> tuple[MemoryKind, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError("kinds must be a tuple or list")
    if len(values) > len(MemoryKind):
        raise ValueError("kinds exceeds its maximum count")
    return tuple(sorted({_kind(value) for value in values}, key=lambda item: item.value))


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("confidence must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError("confidence must be finite and between 0 and 1")
    return result


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Digest-only provenance for one memory atom; it never stores turn text."""

    source_kind: str
    digest: str
    observed_at: datetime
    source_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_kind",
            _canonical_text(self.source_kind, "source_kind", _MAX_SOURCE_KIND),
        )
        if not isinstance(self.digest, str) or _HEX_DIGEST.fullmatch(self.digest) is None:
            raise ValueError("digest must be a 64-character SHA-256 hexadecimal digest")
        object.__setattr__(self, "digest", self.digest.lower())
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at timezone"))
        object.__setattr__(
            self,
            "source_id",
            _optional_text(self.source_id, "source_id", _MAX_ID),
        )


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One atomic, bounded memory value and its provenance."""

    record_id: str
    profile_id: str
    kind: MemoryKind
    key: str
    value: str | int | float | bool
    confidence: float
    created_at: datetime
    valid_from: datetime
    evidence: Evidence
    session_id: str | None = None
    valid_until: datetime | None = None
    supersedes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _canonical_text(self.record_id, "record_id", _MAX_ID))
        object.__setattr__(
            self,
            "profile_id",
            _canonical_text(self.profile_id, "profile_id", _MAX_ID),
        )
        object.__setattr__(
            self,
            "session_id",
            _optional_text(self.session_id, "session_id", _MAX_ID),
        )
        object.__setattr__(self, "kind", _kind(self.kind))
        object.__setattr__(self, "key", _canonical_text(self.key, "key", _MAX_KEY))
        object.__setattr__(self, "value", _atom(self.value))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at timezone"))
        object.__setattr__(self, "valid_from", _utc(self.valid_from, "valid_from timezone"))
        if self.valid_until is not None:
            object.__setattr__(
                self,
                "valid_until",
                _utc(self.valid_until, "valid_until timezone"),
            )
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        if not isinstance(self.evidence, Evidence):
            raise TypeError("evidence must be Evidence")
        object.__setattr__(
            self,
            "supersedes",
            _string_tuple(
                self.supersedes,
                "supersedes",
                item_limit=_MAX_ID,
                count_limit=_MAX_SUPERSEDES,
            ),
        )
        if self.record_id in self.supersedes:
            raise ValueError("supersedes cannot contain the record itself")
        object.__setattr__(
            self,
            "tags",
            _string_tuple(
                self.tags,
                "tags",
                item_limit=_MAX_TAG,
                count_limit=_MAX_TAGS,
                case_insensitive=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class RecallQuery:
    """A bounded, profile-isolated request for active memories."""

    profile_id: str
    at: datetime
    session_id: str | None = None
    key: str | None = None
    terms: tuple[str, ...] = ()
    kinds: tuple[MemoryKind, ...] = ()
    limit: int = 10

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "profile_id",
            _canonical_text(self.profile_id, "profile_id", _MAX_ID),
        )
        object.__setattr__(
            self,
            "session_id",
            _optional_text(self.session_id, "session_id", _MAX_ID),
        )
        object.__setattr__(self, "at", _utc(self.at, "at timezone"))
        object.__setattr__(self, "key", _optional_text(self.key, "key", _MAX_KEY))
        object.__setattr__(
            self,
            "terms",
            _string_tuple(
                self.terms,
                "terms",
                item_limit=_MAX_TAG,
                count_limit=_MAX_TERMS,
                case_insensitive=True,
            ),
        )
        object.__setattr__(self, "kinds", _kinds(self.kinds))
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= self.limit <= _MAX_RECALL:
            raise ValueError(f"limit must be between 1 and {_MAX_RECALL}")


@dataclass(frozen=True, slots=True)
class RecallHit:
    """A recalled atom plus concise, inspectable selection reasons."""

    record: MemoryRecord
    why_recalled: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.record, MemoryRecord):
            raise TypeError("record must be a MemoryRecord")
        reasons = _string_tuple(
            self.why_recalled,
            "why_recalled",
            item_limit=_MAX_KEY,
            count_limit=16,
        )
        if not reasons:
            raise ValueError("why_recalled must not be empty")
        object.__setattr__(self, "why_recalled", reasons)


_CREATE_STATEMENTS: Final = (
    """
    CREATE TABLE IF NOT EXISTS memory_records (
        record_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        session_id TEXT,
        kind TEXT,
        memory_key TEXT,
        key_fold TEXT,
        value_json TEXT,
        confidence REAL,
        created_at TEXT,
        valid_from TEXT,
        valid_until TEXT,
        evidence_source_kind TEXT,
        evidence_digest TEXT,
        evidence_observed_at TEXT,
        evidence_source_id TEXT,
        tags_json TEXT,
        supersedes_json TEXT,
        semantic_digest TEXT NOT NULL,
        deleted_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_supersessions (
        target_id TEXT PRIMARY KEY,
        superseder_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        session_id TEXT,
        effective_from TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_terms (
        record_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        term TEXT NOT NULL,
        PRIMARY KEY (record_id, term),
        FOREIGN KEY (record_id) REFERENCES memory_records(record_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_profile_key
    ON memory_records(profile_id, key_fold, created_at DESC, record_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_profile_recall
    ON memory_records(profile_id, session_id, valid_from, valid_until, created_at DESC, record_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_term_lookup
    ON memory_terms(profile_id, term, record_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_superseder
    ON memory_supersessions(superseder_id)
    """,
)

_RECORD_COLUMN_NAMES: Final = (
    "record_id",
    "profile_id",
    "session_id",
    "kind",
    "memory_key",
    "key_fold",
    "value_json",
    "confidence",
    "created_at",
    "valid_from",
    "valid_until",
    "evidence_source_kind",
    "evidence_digest",
    "evidence_observed_at",
    "evidence_source_id",
    "tags_json",
    "supersedes_json",
    "semantic_digest",
    "deleted_at",
)
_RECORD_COLUMNS: Final = ", ".join(_RECORD_COLUMN_NAMES)


@dataclass(slots=True)
class _WriteSnapshot:
    connection: sqlite3.Connection
    directory_fd: int


def _local_lock(path: Path) -> threading.RLock:
    key = os.fspath(path)
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


def _entry_flags(*, writable: bool = False, directory: bool = False) -> int:
    flags = os.O_RDWR if writable else os.O_RDONLY
    for name in ("O_CLOEXEC", "O_NONBLOCK", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    return flags


class SQLiteMemoryLedger:
    """POSIX/local SQLite-image ledger with verified snapshots and atomic replacement."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        if os.name != "posix" or fcntl is None:
            raise NotImplementedError(
                "SQLiteMemoryLedger currently requires a POSIX local filesystem"
            )
        self._path = Path(os.path.abspath(os.fspath(path)))
        if not self._path.name:
            raise ValueError("memory database path must name a file")
        self._name = self._path.name
        self._lock_name = f".{self._name}.lock"
        self._closed = False
        self._validate_storage_if_present()

    @property
    def path(self) -> Path:
        """Return the lexical absolute database-image path without touching storage."""

        return self._path

    def close(self) -> None:
        """Prevent future use; no persistent SQLite connection is held."""

        self._closed = True

    def __enter__(self) -> SQLiteMemoryLedger:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("memory ledger is closed")

    def _open_parent(self, *, create: bool) -> int | None:
        directory_fd = os.open(os.sep, _entry_flags(directory=True))
        try:
            for component in self._path.parent.parts[1:]:
                try:
                    details = os.stat(component, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    if not create:
                        os.close(directory_fd)
                        return None
                    try:
                        os.mkdir(component, 0o700, dir_fd=directory_fd)
                    except FileExistsError:
                        pass
                    details = os.stat(component, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(details.st_mode):
                    raise ValueError("memory database parent must not be a symlink")
                if not stat.S_ISDIR(details.st_mode):
                    raise ValueError("memory database parent must be a directory")
                next_fd = os.open(
                    component,
                    _entry_flags(directory=True),
                    dir_fd=directory_fd,
                )
                opened = os.fstat(next_fd)
                if (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino):
                    os.close(next_fd)
                    raise ValueError("memory database parent changed during secure open")
                os.close(directory_fd)
                directory_fd = next_fd
            parent = os.fstat(directory_fd)
            mode = stat.S_IMODE(parent.st_mode)
            if parent.st_uid != os.geteuid() or mode & 0o022:
                raise ValueError("memory database state directory must not be group/other writable")
            if create and mode != 0o700:
                raise ValueError("writable memory database state directory must use mode 0700")
            return directory_fd
        except Exception:
            os.close(directory_fd)
            raise

    @staticmethod
    def _entry_details(directory_fd: int, name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _open_regular(
        self,
        directory_fd: int,
        name: str,
        *,
        writable: bool,
        allow_absent: bool,
    ) -> int | None:
        details = self._entry_details(directory_fd, name)
        if details is None:
            if allow_absent:
                return None
            raise ValueError(f"required ledger file is absent: {name}")
        if stat.S_ISLNK(details.st_mode):
            raise ValueError("memory database path must not be a symlink")
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("memory database path must be a regular file")
        if details.st_nlink != 1:
            raise ValueError("memory database and lock files must not be hardlinked")
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o600:
            raise ValueError("memory database and lock permissions must be owner-only mode 0600")
        descriptor = os.open(name, _entry_flags(writable=writable), dir_fd=directory_fd)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError("memory database path must be a regular file")
            if opened.st_nlink != 1:
                raise ValueError("memory database and lock files must not be hardlinked")
            if opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o600:
                raise ValueError("memory database and lock permissions changed during secure open")
            if (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino):
                raise ValueError("memory database entry changed during secure open")
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def _create_or_open_lock(self, directory_fd: int) -> int:
        descriptor = self._open_regular(
            directory_fd,
            self._lock_name,
            writable=True,
            allow_absent=True,
        )
        if descriptor is not None:
            return descriptor
        flags = _entry_flags(writable=True) | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self._lock_name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            existing = self._open_regular(
                directory_fd,
                self._lock_name,
                writable=True,
                allow_absent=False,
            )
            assert existing is not None
            return existing
        try:
            os.fchmod(descriptor, 0o600)
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _acquire_flock(descriptor: int, *, exclusive: bool) -> None:
        assert fcntl is not None
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for the memory ledger lock") from None
                time.sleep(0.01)

    @staticmethod
    def _release_flock(descriptor: int) -> None:
        assert fcntl is not None
        fcntl.flock(descriptor, fcntl.LOCK_UN)

    def _validate_storage_if_present(self) -> None:
        self._read_image_bytes()

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        before = os.fstat(descriptor)
        if before.st_nlink != 1:
            raise ValueError("memory database image must not be hardlinked")
        if before.st_size <= 0:
            raise ValueError("memory database image is empty or corrupt")
        if before.st_size > _MAX_IMAGE_BYTES:
            raise ValueError("memory database image exceeds the bounded size limit")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1_048_576))
            if not chunk:
                raise ValueError("memory database image changed during snapshot read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size, after.st_nlink) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_nlink,
        ):
            raise ValueError("memory database image changed during snapshot read")
        return b"".join(chunks)

    def _read_image_bytes(self) -> bytes | None:
        directory_fd = self._open_parent(create=False)
        if directory_fd is None:
            return None
        local = _local_lock(self._path)
        local.acquire()
        lock_fd: int | None = None
        image_fd: int | None = None
        flocked = False
        try:
            image_details = self._entry_details(directory_fd, self._name)
            if image_details is None:
                return None
            if stat.S_ISLNK(image_details.st_mode):
                raise ValueError("memory database path must not be a symlink")
            if not stat.S_ISREG(image_details.st_mode):
                raise ValueError("memory database path must be a regular file")
            if self._entry_details(directory_fd, self._lock_name) is None:
                raise ValueError("existing memory database requires its verified sibling lock")
            lock_fd = self._open_regular(
                directory_fd,
                self._lock_name,
                writable=False,
                allow_absent=False,
            )
            assert lock_fd is not None
            self._acquire_flock(lock_fd, exclusive=False)
            flocked = True
            self._verify_private_entry(
                directory_fd,
                self._lock_name,
                lock_fd,
                "memory database lock changed during secure acquisition",
            )
            self._reject_sidecars(directory_fd)
            image_fd = self._open_regular(
                directory_fd,
                self._name,
                writable=False,
                allow_absent=False,
            )
            assert image_fd is not None
            return self._read_descriptor(image_fd)
        finally:
            if image_fd is not None:
                os.close(image_fd)
            if lock_fd is not None:
                if flocked:
                    self._release_flock(lock_fd)
                os.close(lock_fd)
            local.release()
            os.close(directory_fd)

    def _reject_sidecars(self, directory_fd: int) -> None:
        for suffix in ("-wal", "-shm", "-journal"):
            if self._entry_details(directory_fd, f"{self._name}{suffix}") is not None:
                raise ValueError("memory database has an unsupported live SQLite sidecar")

    @staticmethod
    def _memory_connection(image: bytes | None, *, writable: bool) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:", isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            if image is not None:
                connection.deserialize(_normalize_sqlite_header(image))
            connection.execute("PRAGMA journal_mode=MEMORY")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
            if image is not None:
                result = tuple(row[0] for row in connection.execute("PRAGMA quick_check"))
                if result != ("ok",):
                    raise ValueError("memory database image failed quick_check")
                if not SQLiteMemoryLedger._has_schema(connection):
                    raise ValueError("memory database image has no supported ledger schema")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != 1:
                    raise ValueError("memory database image has an unsupported schema version")
            if not writable:
                connection.execute("PRAGMA query_only=ON")
            return connection
        except sqlite3.DatabaseError as error:
            connection.close()
            raise ValueError("memory database image is corrupt") from error
        except Exception:
            connection.close()
            raise

    def _read_connection(self) -> sqlite3.Connection | None:
        image = self._read_image_bytes()
        if image is None:
            return None
        return self._memory_connection(image, writable=False)

    @contextmanager
    def _write_snapshot(self) -> Iterator[_WriteSnapshot]:
        directory_fd = self._open_parent(create=True)
        assert directory_fd is not None
        local = _local_lock(self._path)
        local.acquire()
        lock_fd: int | None = None
        image_fd: int | None = None
        connection: sqlite3.Connection | None = None
        flocked = False
        try:
            image_exists = self._entry_details(directory_fd, self._name) is not None
            lock_exists = self._entry_details(directory_fd, self._lock_name) is not None
            if image_exists and not lock_exists:
                raise ValueError("existing memory database requires its verified sibling lock")
            lock_fd = self._create_or_open_lock(directory_fd)
            self._acquire_flock(lock_fd, exclusive=True)
            flocked = True
            self._verify_private_entry(
                directory_fd,
                self._lock_name,
                lock_fd,
                "memory database lock changed during secure acquisition",
            )
            self._reject_sidecars(directory_fd)
            image_fd = self._open_regular(
                directory_fd,
                self._name,
                writable=False,
                allow_absent=True,
            )
            image = self._read_descriptor(image_fd) if image_fd is not None else None
            connection = self._memory_connection(image, writable=True)
            self._cleanup_orphan_temps(directory_fd)
            yield _WriteSnapshot(connection=connection, directory_fd=directory_fd)
        finally:
            if connection is not None:
                connection.close()
            if image_fd is not None:
                os.close(image_fd)
            if lock_fd is not None:
                if flocked:
                    self._release_flock(lock_fd)
                os.close(lock_fd)
            local.release()
            os.close(directory_fd)

    def _cleanup_orphan_temps(self, directory_fd: int) -> None:
        """Scrub verified orphan images while the caller holds the exclusive ledger lock."""

        prefix = f".{self._name}.tmp-"
        names = sorted(
            name
            for name in os.listdir(directory_fd)
            if name.startswith(prefix) and _TEMP_SUFFIX.fullmatch(name.removeprefix(prefix))
        )
        if len(names) > _MAX_ORPHAN_TEMPS:
            raise ValueError("memory database has too many orphan snapshot images")
        verified: list[tuple[str, int]] = []
        try:
            for name in names:
                descriptor = self._open_regular(
                    directory_fd,
                    name,
                    writable=True,
                    allow_absent=False,
                )
                assert descriptor is not None
                verified.append((name, descriptor))
            for name, descriptor in verified:
                self._verify_orphan_entry(directory_fd, name, descriptor)
            for name, descriptor in verified:
                self._verify_orphan_entry(directory_fd, name, descriptor)
                self._scrub_descriptor(descriptor)
                self._verify_orphan_entry(directory_fd, name, descriptor)
                os.unlink(name, dir_fd=directory_fd)
                os.fsync(directory_fd)
        finally:
            for _name, descriptor in verified:
                os.close(descriptor)

    @staticmethod
    def _verify_orphan_entry(directory_fd: int, name: str, descriptor: int) -> None:
        SQLiteMemoryLedger._verify_private_entry(
            directory_fd,
            name,
            descriptor,
            "orphan snapshot changed during secure cleanup",
        )

    @staticmethod
    def _verify_private_entry(
        directory_fd: int,
        name: str,
        descriptor: int,
        error_message: str,
    ) -> None:
        current = SQLiteMemoryLedger._entry_details(directory_fd, name)
        opened = os.fstat(descriptor)
        if (
            current is None
            or not stat.S_ISREG(current.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or current.st_uid != os.geteuid()
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(current.st_mode) != 0o600
            or stat.S_IMODE(opened.st_mode) != 0o600
            or current.st_nlink != 1
            or opened.st_nlink != 1
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise ValueError(error_message)

    @staticmethod
    def _scrub_descriptor(descriptor: int) -> None:
        """Best-effort logical scrub; storage media and snapshots remain out of scope."""

        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)

    def _persist_snapshot(self, snapshot: _WriteSnapshot) -> None:
        result = tuple(row[0] for row in snapshot.connection.execute("PRAGMA quick_check"))
        if result != ("ok",):
            raise ValueError("memory database transaction failed quick_check")
        image = snapshot.connection.serialize()
        if len(image) > _MAX_IMAGE_BYTES:
            raise ValueError("memory database image exceeds the bounded size limit")
        temp_name = f".{self._name}.tmp-{secrets.token_hex(12)}"
        flags = _entry_flags(writable=True) | os.O_CREAT | os.O_EXCL
        descriptor: int | None = None
        try:
            descriptor = os.open(temp_name, flags, 0o600, dir_fd=snapshot.directory_fd)
            os.fchmod(descriptor, 0o600)
            view = memoryview(image)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("failed to write the memory database snapshot")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(
                temp_name,
                self._name,
                src_dir_fd=snapshot.directory_fd,
                dst_dir_fd=snapshot.directory_fd,
            )
            os.fsync(snapshot.directory_fd)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temp_name, dir_fd=snapshot.directory_fd)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _has_schema(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("memory_records",),
        ).fetchone()
        return row is not None

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        for statement in _CREATE_STATEMENTS:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")

    @staticmethod
    def _active_at(row: sqlite3.Row, at: datetime) -> bool:
        instant = _time_text(at)
        return row["valid_from"] <= instant and (
            row["valid_until"] is None or instant < row["valid_until"]
        )

    def remember(self, record: MemoryRecord, *, no_save: bool = False) -> bool:
        """Atomically store one record, or do nothing at all when ``no_save`` is true."""

        self._ensure_open()
        if no_save:
            return False
        if not isinstance(record, MemoryRecord):
            raise TypeError("record must be a MemoryRecord")
        with self._write_snapshot() as snapshot:
            connection = snapshot.connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._ensure_schema(connection)
                duplicate = connection.execute(
                    f"SELECT {_RECORD_COLUMNS} FROM memory_records WHERE record_id = ?",
                    (record.record_id,),
                ).fetchone()
                if duplicate is not None:
                    if duplicate["deleted_at"] is not None:
                        if duplicate["semantic_digest"] == _semantic_digest(record):
                            connection.rollback()
                            return False
                        raise ValueError("record_id belongs to a deleted memory record")
                    existing = self._row_to_record(connection, duplicate)
                    if existing == record and type(existing.value) is type(record.value):
                        connection.rollback()
                        return False
                    raise ValueError("record_id already identifies a different memory record")
                if record.supersedes:
                    self._validate_supersessions(connection, record)
                self._insert_record(connection, record)
                connection.commit()
                self._persist_snapshot(snapshot)
                return True
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

    @staticmethod
    def _insert_record(connection: sqlite3.Connection, record: MemoryRecord) -> None:
        placeholders = ", ".join("?" for _ in _RECORD_COLUMN_NAMES)
        connection.execute(
            f"INSERT INTO memory_records ({_RECORD_COLUMNS}) VALUES ({placeholders})",
            (
                record.record_id,
                record.profile_id,
                record.session_id,
                record.kind.value,
                record.key,
                _fold(record.key),
                _value_json(record.value),
                record.confidence,
                _time_text(record.created_at),
                _time_text(record.valid_from),
                _time_text(record.valid_until) if record.valid_until else None,
                record.evidence.source_kind,
                record.evidence.digest,
                _time_text(record.evidence.observed_at),
                record.evidence.source_id,
                json.dumps(record.tags, ensure_ascii=False, separators=(",", ":")),
                json.dumps(record.supersedes, ensure_ascii=False, separators=(",", ":")),
                _semantic_digest(record),
                None,
            ),
        )
        terms = _record_terms(record)
        connection.executemany(
            "INSERT INTO memory_terms (record_id, profile_id, term) VALUES (?, ?, ?)",
            ((record.record_id, record.profile_id, term) for term in terms),
        )
        connection.executemany(
            """
            INSERT INTO memory_supersessions
                (target_id, superseder_id, profile_id, session_id, effective_from)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    target_id,
                    record.record_id,
                    record.profile_id,
                    record.session_id,
                    _time_text(record.valid_from),
                )
                for target_id in record.supersedes
            ),
        )

    @staticmethod
    def _validate_supersessions(connection: sqlite3.Connection, record: MemoryRecord) -> None:
        if not (
            record.valid_from <= record.created_at
            and (record.valid_until is None or record.created_at < record.valid_until)
        ):
            raise ValueError("superseding record must be active when created")
        placeholders = ",".join("?" for _ in record.supersedes)
        targets = connection.execute(
            f"""
            SELECT r.record_id, r.profile_id, r.session_id, r.valid_from, r.valid_until,
                   s.target_id AS already_superseded
            FROM memory_records AS r
            LEFT JOIN memory_supersessions AS s ON s.target_id = r.record_id
            WHERE r.deleted_at IS NULL AND r.record_id IN ({placeholders})
            """,
            record.supersedes,
        ).fetchall()
        if len(targets) != len(record.supersedes):
            raise ValueError("superseded target is missing")
        for target in targets:
            if target["profile_id"] != record.profile_id:
                raise ValueError("superseded target belongs to another profile")
            if target["session_id"] != record.session_id:
                raise ValueError("superseded target belongs to another session scope")
            if target["already_superseded"] is not None:
                raise ValueError("superseded target is already superseded")
            if not SQLiteMemoryLedger._active_at(target, record.created_at):
                raise ValueError("superseded target is not active")

    def recall(self, query: RecallQuery) -> tuple[RecallHit, ...]:
        """Return SQL-bounded active hits from one verified database snapshot."""

        self._ensure_open()
        if not isinstance(query, RecallQuery):
            raise TypeError("query must be a RecallQuery")
        connection = self._read_connection()
        if connection is None:
            return ()
        try:
            rows = self._visible_rows(connection, query)
            hits = []
            for row in rows:
                record = self._row_to_record(connection, row)
                reasons: list[str] = []
                if row["exact_rank"]:
                    reasons.append("exact_key")
                reasons.extend(f"term:{term}" for term in _matched_terms(record, query.terms))
                reasons.extend(
                    (f"kind:{record.kind.value}", f"recency:{_time_text(record.created_at)}")
                )
                hits.append(RecallHit(record=record, why_recalled=tuple(reasons)))
            return tuple(hits)
        finally:
            connection.close()

    @staticmethod
    def _visible_rows(
        connection: sqlite3.Connection,
        query: RecallQuery,
    ) -> list[sqlite3.Row]:
        parameters: dict[str, object] = {
            "profile_id": query.profile_id,
            "at": _time_text(query.at),
            "limit": query.limit,
        }
        conditions = [
            "r.profile_id = :profile_id",
            "r.deleted_at IS NULL",
            "r.valid_from <= :at",
            "(r.valid_until IS NULL OR :at < r.valid_until)",
            """
            NOT EXISTS (
                SELECT 1 FROM memory_supersessions AS s
                WHERE s.target_id = r.record_id AND s.effective_from <= :at
            )
            """,
        ]
        if query.session_id is None:
            conditions.append("r.session_id IS NULL")
        else:
            conditions.append("(r.session_id IS NULL OR r.session_id = :session_id)")
            parameters["session_id"] = query.session_id
        if query.kinds:
            kind_names = []
            for index, kind in enumerate(query.kinds):
                name = f"kind_{index}"
                kind_names.append(f":{name}")
                parameters[name] = kind.value
            conditions.append(f"r.kind IN ({', '.join(kind_names)})")
        exact_expression = "0"
        selectors = []
        if query.key is not None:
            parameters["key_fold"] = _fold(query.key)
            exact_expression = "CASE WHEN r.key_fold = :key_fold THEN 1 ELSE 0 END"
            selectors.append("r.key_fold = :key_fold")
        query_terms = tuple(_normalize_term(term) for term in query.terms)
        if query_terms:
            term_names = []
            for index, term in enumerate(query_terms):
                name = f"term_{index}"
                term_names.append(f":{name}")
                parameters[name] = term
            term_cte = f"""
                term_matches AS (
                    SELECT record_id, COUNT(*) AS term_rank
                    FROM memory_terms
                    WHERE profile_id = :profile_id AND term IN ({", ".join(term_names)})
                    GROUP BY record_id
                )
            """
            term_join = "LEFT JOIN term_matches AS tm ON tm.record_id = r.record_id"
            term_expression = "COALESCE(tm.term_rank, 0)"
            selectors.append("tm.term_rank > 0")
        else:
            term_cte = "term_matches AS (SELECT NULL AS record_id, 0 AS term_rank WHERE 0)"
            term_join = "LEFT JOIN term_matches AS tm ON 0"
            term_expression = "0"
        if selectors:
            conditions.append(f"({' OR '.join(selectors)})")
        selected_columns = ", ".join(f"r.{name}" for name in _RECORD_COLUMN_NAMES)
        return connection.execute(
            f"""
            WITH {term_cte}
            SELECT {selected_columns},
                   {exact_expression} AS exact_rank,
                   {term_expression} AS term_rank
            FROM memory_records AS r
            {term_join}
            WHERE {" AND ".join(conditions)}
            ORDER BY exact_rank DESC, term_rank DESC, r.created_at DESC, r.record_id ASC
            LIMIT :limit
            """,
            parameters,
        ).fetchall()

    @staticmethod
    def _row_to_record(_connection: sqlite3.Connection, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            record_id=row["record_id"],
            profile_id=row["profile_id"],
            session_id=row["session_id"],
            kind=MemoryKind(row["kind"]),
            key=row["memory_key"],
            value=json.loads(row["value_json"]),
            confidence=row["confidence"],
            created_at=_parse_time(row["created_at"]),
            valid_from=_parse_time(row["valid_from"]),
            valid_until=_parse_time(row["valid_until"]) if row["valid_until"] else None,
            evidence=Evidence(
                source_kind=row["evidence_source_kind"],
                digest=row["evidence_digest"],
                observed_at=_parse_time(row["evidence_observed_at"]),
                source_id=row["evidence_source_id"],
            ),
            supersedes=tuple(json.loads(row["supersedes_json"])),
            tags=tuple(json.loads(row["tags_json"])),
        )

    def conflicts(
        self,
        profile_id: str,
        key: str,
        *,
        at: datetime,
        session_id: str | None = None,
    ) -> tuple[RecallHit, ...]:
        """Return bounded representatives when visible canonical values disagree."""

        self._ensure_open()
        query = RecallQuery(
            profile_id=profile_id,
            session_id=session_id,
            at=at,
            key=key,
            limit=_MAX_RECALL,
        )
        connection = self._read_connection()
        if connection is None:
            return ()
        try:
            conditions = [
                "r.profile_id = :profile_id",
                "r.deleted_at IS NULL",
                "r.key_fold = :key_fold",
                "r.valid_from <= :at",
                "(r.valid_until IS NULL OR :at < r.valid_until)",
                """
                NOT EXISTS (
                    SELECT 1 FROM memory_supersessions AS s
                    WHERE s.target_id = r.record_id AND s.effective_from <= :at
                )
                """,
            ]
            parameters: dict[str, object] = {
                "profile_id": query.profile_id,
                "key_fold": _fold(key),
                "at": _time_text(query.at),
                "limit": _MAX_RECALL,
            }
            if query.session_id is None:
                conditions.append("r.session_id IS NULL")
            else:
                conditions.append("(r.session_id IS NULL OR r.session_id = :session_id)")
                parameters["session_id"] = query.session_id
            selected_columns = ", ".join(f"r.{name}" for name in _RECORD_COLUMN_NAMES)
            ranked_columns = ", ".join(_RECORD_COLUMN_NAMES)
            rows = connection.execute(
                f"""
                WITH ranked AS (
                    SELECT {selected_columns},
                           ROW_NUMBER() OVER (
                               PARTITION BY r.value_json
                               ORDER BY r.created_at DESC, r.record_id ASC
                           ) AS value_rank
                    FROM memory_records AS r
                    WHERE {" AND ".join(conditions)}
                )
                SELECT {ranked_columns}
                FROM ranked
                WHERE value_rank = 1
                  AND (SELECT COUNT(*) FROM ranked WHERE value_rank = 1) > 1
                ORDER BY created_at DESC, record_id ASC
                LIMIT :limit
                """,
                parameters,
            ).fetchall()
            return tuple(
                RecallHit(
                    record=(record := self._row_to_record(connection, row)),
                    why_recalled=(
                        "exact_key",
                        f"kind:{record.kind.value}",
                        f"recency:{_time_text(record.created_at)}",
                        "conflict:distinct_value",
                    ),
                )
                for row in rows
            )
        finally:
            connection.close()

    def delete(self, record_id: str, profile_id: str, *, no_save: bool = False) -> bool:
        """Delete one record and rebuild the current image to remove its plaintext."""

        self._ensure_open()
        if no_save:
            return False
        canonical_id = _canonical_text(record_id, "record_id", _MAX_ID)
        canonical_profile = _canonical_text(profile_id, "profile_id", _MAX_ID)
        with self._write_snapshot() as snapshot:
            connection = snapshot.connection
            try:
                if not self._has_schema(connection):
                    return False
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM memory_terms WHERE record_id = ? AND profile_id = ?",
                    (canonical_id, canonical_profile),
                )
                cursor = connection.execute(
                    """
                    UPDATE memory_records
                    SET kind = NULL,
                        memory_key = NULL,
                        key_fold = NULL,
                        value_json = NULL,
                        confidence = NULL,
                        created_at = NULL,
                        valid_from = NULL,
                        valid_until = NULL,
                        evidence_source_kind = NULL,
                        evidence_digest = NULL,
                        evidence_observed_at = NULL,
                        evidence_source_id = NULL,
                        tags_json = NULL,
                        supersedes_json = NULL,
                        deleted_at = ?
                    WHERE record_id = ? AND profile_id = ? AND deleted_at IS NULL
                    """,
                    (_time_text(datetime.now(UTC)), canonical_id, canonical_profile),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    return False
                connection.commit()
                connection.execute("VACUUM")
                self._persist_snapshot(snapshot)
                return True
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

    def schema_columns(self) -> dict[str, tuple[str, ...]]:
        """Inspect ledger-owned column names without creating or changing storage."""

        self._ensure_open()
        connection = self._read_connection()
        if connection is None:
            return {}
        try:
            placeholders = ", ".join("?" for _ in _TABLES)
            present = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    f"WHERE type = 'table' AND name IN ({placeholders})",
                    _TABLES,
                ).fetchall()
            }
            columns = {}
            for table in _TABLES:
                if table in present:
                    columns[table] = tuple(
                        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
                    )
            return columns
        finally:
            connection.close()

    def quick_check(self) -> str:
        """Check one verified snapshot, or report an absent database image."""

        self._ensure_open()
        connection = self._read_connection()
        if connection is None:
            return "absent"
        try:
            return "; ".join(str(row[0]) for row in connection.execute("PRAGMA quick_check"))
        finally:
            connection.close()


def _value_json(value: str | int | float | bool) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _semantic_digest(record: MemoryRecord) -> str:
    payload = {
        "record_id": record.record_id,
        "profile_id": record.profile_id,
        "session_id": record.session_id,
        "kind": record.kind.value,
        "key": record.key,
        "value": record.value,
        "confidence": record.confidence,
        "created_at": _time_text(record.created_at),
        "valid_from": _time_text(record.valid_from),
        "valid_until": _time_text(record.valid_until) if record.valid_until else None,
        "evidence": {
            "source_kind": record.evidence.source_kind,
            "digest": record.evidence.digest,
            "observed_at": _time_text(record.evidence.observed_at),
            "source_id": record.evidence.source_id,
        },
        "supersedes": record.supersedes,
        "tags": record.tags,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _normalize_term(value: str) -> str:
    return " ".join(_fold(value).split())


def _record_terms(record: MemoryRecord) -> tuple[str, ...]:
    terms: set[str] = set()
    for value in (record.key, str(record.value), *record.tags):
        normalized = _normalize_term(value)
        if normalized and len(normalized) <= _MAX_TAG:
            terms.add(normalized)
        words = [word for word in _WORD.findall(normalized) if len(word) <= _MAX_TAG]
        for width in range(1, 4):
            for index in range(len(words) - width + 1):
                phrase = " ".join(words[index : index + width])
                if len(phrase) <= _MAX_TAG:
                    terms.add(phrase)
    return tuple(sorted(terms))[:_MAX_RECORD_TERMS]


def _normalize_sqlite_header(image: bytes) -> bytes:
    if len(image) < 100 or image[:16] != b"SQLite format 3\x00":
        raise ValueError("memory database image is corrupt")
    read_version, write_version = image[18], image[19]
    if (read_version, write_version) == (1, 1):
        return image
    if (read_version, write_version) != (2, 2):
        raise ValueError("memory database image has an inconsistent journal header")
    normalized = bytearray(image)
    normalized[18] = 1
    normalized[19] = 1
    return bytes(normalized)


def _matched_terms(record: MemoryRecord, terms: tuple[str, ...]) -> tuple[str, ...]:
    if not terms:
        return ()
    searchable = _normalize_term(" ".join((record.key, str(record.value), *record.tags)))
    normalized = tuple(_normalize_term(term) for term in terms)
    return tuple(term for term in normalized if term in searchable)


__all__ = [
    "Evidence",
    "MemoryKind",
    "MemoryRecord",
    "RecallHit",
    "RecallQuery",
    "SQLiteMemoryLedger",
]
