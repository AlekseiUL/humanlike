"""Deterministic, rights-aware creative planning primitives."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from .models import Mode, RouteDecision

MAX_CREATIVE_REQUEST_CHARS: Final = 64 * 1024
MAX_CREATIVE_CONTEXT_CHARS: Final = 16 * 1024
FOUNDATION_MANIFEST_SHA256: Final = (
    "ed74e0dbc07b0f3dc665f3d5e801bc3c30ca1d477ae513f9b5cebba16e2d37d2"
)
_MAX_ID: Final = 128
_MAX_APPROACH: Final = 512
_MAX_DESCRIPTION: Final = 512
_MAX_OWNER: Final = 256
_MAX_MANIFEST_BYTES: Final = 16 * 1024
_MAX_PACK_FILE_BYTES: Final = 64 * 1024
_MAX_JSON_DEPTH: Final = 8
_MAX_JSON_NODES: Final = 512
_MAX_PACK_RECORDS: Final = 16
_FORBIDDEN_BIDI = frozenset({"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})
_HEX = frozenset("0123456789abcdef")
_SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_PACK_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_RUBRIC_IDS: Final = (
    "task_fit",
    "mechanism_shift",
    "specificity",
    "coherence",
    "preference_fit",
)
_ANTI_PATTERN_IDS: Final = frozenset(
    {"generic_template", "repeated_shape", "punchline_tail", "ornamental_novelty"}
)
_PACK_FILES: Final = ("rubric.json", "anti-patterns.json")
_ALLOWED_BASES: Final = frozenset({"original", "authorized", "internal_original"})
_ALLOWED_LICENSES: Final = frozenset({"All-Rights-Reserved", "Apache-2.0", "MIT", "CC0-1.0"})


class CreativeMechanism(StrEnum):
    """Five approach-level mechanisms for divergent ideation."""

    INVERSION = "inversion"
    DISTANT_ANALOGY = "distant_analogy"
    CONSTRAINT_SHIFT = "constraint_shift"
    TENSION_FIRST = "tension_first"
    CONCRETE_COUNTEREXAMPLE = "concrete_counterexample"


def _text(value: object, field: str, limit: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    for character in normalized:
        category = unicodedata.category(character)
        if (
            category in {"Cf", "Cs", "Zl", "Zp"}
            or unicodedata.bidirectional(character) in _FORBIDDEN_BIDI
        ):
            raise ValueError(
                f"{field} contains an unsafe format, line separator, or bidi character"
            )
        if category == "Cc" and not (multiline and character in {"\n", "\t"}):
            raise ValueError(f"{field} contains an unsafe control character")
    canonical = normalized.strip()
    if not canonical:
        raise ValueError(f"{field} must not be empty")
    if len(canonical) > limit:
        raise ValueError(f"{field} exceeds its size limit")
    return canonical


def _mechanism(value: object) -> CreativeMechanism:
    if isinstance(value, CreativeMechanism):
        return value
    if isinstance(value, str):
        try:
            return CreativeMechanism(value)
        except ValueError as error:
            raise ValueError("mechanism is not supported") from error
    raise TypeError("mechanism must be CreativeMechanism")


def _sha256(value: object, field_name: str) -> str:
    digest = _text(value, field_name, 64)
    if len(digest) != 64 or any(character not in _HEX for character in digest):
        raise ValueError(f"{field_name} must be lowercase SHA-256 hexadecimal")
    return digest


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CreativeStrategy:
    """One trusted, approach-level divergence strategy."""

    strategy_id: str
    mechanism: CreativeMechanism
    approach: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _text(self.strategy_id, "strategy_id", _MAX_ID))
        object.__setattr__(self, "mechanism", _mechanism(self.mechanism))
        object.__setattr__(self, "approach", _text(self.approach, "approach", _MAX_APPROACH))


@dataclass(frozen=True, slots=True)
class CreativeDirective:
    """A strategy bound to one privacy-safe request fingerprint."""

    strategy_id: str
    mechanism: CreativeMechanism
    approach: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        strategy = CreativeStrategy(self.strategy_id, self.mechanism, self.approach)
        object.__setattr__(self, "strategy_id", strategy.strategy_id)
        object.__setattr__(self, "mechanism", strategy.mechanism)
        object.__setattr__(self, "approach", strategy.approach)
        fingerprint = _text(self.request_fingerprint, "request_fingerprint", 64)
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError("request_fingerprint must be lowercase SHA-256 hexadecimal")
        object.__setattr__(self, "request_fingerprint", fingerprint)


_STRATEGIES: Final = (
    CreativeStrategy(
        "mechanism.inversion",
        CreativeMechanism.INVERSION,
        "Reverse the default premise and derive a concept whose causal structure works from the "
        "opposite assumption.",
    ),
    CreativeStrategy(
        "mechanism.distant_analogy",
        CreativeMechanism.DISTANT_ANALOGY,
        "Map the problem to a remote domain, then transfer relationships and dynamics rather than "
        "surface vocabulary.",
    ),
    CreativeStrategy(
        "mechanism.constraint_shift",
        CreativeMechanism.CONSTRAINT_SHIFT,
        "Change one governing constraint such as time, scale, medium, audience, or resources, then "
        "derive what becomes newly possible.",
    ),
    CreativeStrategy(
        "mechanism.tension_first",
        CreativeMechanism.TENSION_FIRST,
        "Begin with the strongest conflict between goals and build an idea that keeps both sides "
        "productively visible.",
    ),
    CreativeStrategy(
        "mechanism.concrete_counterexample",
        CreativeMechanism.CONCRETE_COUNTEREXAMPLE,
        "Construct a specific case where the obvious solution fails, then derive an alternative "
        "that succeeds in that case.",
    ),
)


def _trusted_directives(request_fingerprint: str) -> tuple[CreativeDirective, ...]:
    return tuple(
        CreativeDirective(
            strategy.strategy_id,
            strategy.mechanism,
            strategy.approach,
            request_fingerprint,
        )
        for strategy in _STRATEGIES
    )


@dataclass(frozen=True, slots=True)
class RightsDeclaration:
    """Machine-checkable permission metadata for one creative record."""

    eligible: bool
    basis: str
    owner: str
    license: str
    use_scope: str
    redistribution_allowed: bool
    provenance_sha256: str

    def __post_init__(self) -> None:
        if type(self.eligible) is not bool or not self.eligible:
            raise ValueError("rights eligible must be true")
        if type(self.redistribution_allowed) is not bool:
            raise ValueError("rights redistribution_allowed must be a boolean")
        basis = _text(self.basis, "rights basis", 32)
        owner = _text(self.owner, "rights owner", _MAX_OWNER)
        license_name = _text(self.license, "rights license", 64)
        scope = _text(self.use_scope, "rights use_scope", 64)
        if basis not in _ALLOWED_BASES:
            raise ValueError("rights basis is not eligible")
        if license_name not in _ALLOWED_LICENSES:
            raise ValueError("rights license is not recognized")
        if scope != "creative_runtime":
            raise ValueError("rights use scope is not eligible")
        internal_rights = basis == "internal_original"
        if internal_rights != (license_name == "All-Rights-Reserved"):
            raise ValueError("rights basis and license are incompatible")
        if self.redistribution_allowed == internal_rights:
            raise ValueError("rights redistribution flag is incompatible")
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "license", license_name)
        object.__setattr__(self, "use_scope", scope)
        object.__setattr__(
            self,
            "provenance_sha256",
            _sha256(self.provenance_sha256, "rights provenance_sha256"),
        )

    def to_data(self) -> dict[str, object]:
        """Return stable rights metadata for validation and fingerprinting."""

        return {
            "basis": self.basis,
            "eligible": self.eligible,
            "license": self.license,
            "owner": self.owner,
            "provenance_sha256": self.provenance_sha256,
            "redistribution_allowed": self.redistribution_allowed,
            "use_scope": self.use_scope,
        }


@dataclass(frozen=True, slots=True)
class CreativeRecord:
    """One bounded, rights-eligible rubric or anti-pattern datum."""

    record_id: str
    description: str
    rights: RightsDeclaration

    def __post_init__(self) -> None:
        record_id = _text(self.record_id, "record_id", _MAX_ID)
        description = _text(self.description, "description", _MAX_DESCRIPTION)
        if not isinstance(self.rights, RightsDeclaration):
            raise TypeError("rights must be RightsDeclaration")
        payload = {"description": description, "id": record_id}
        expected = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
        if self.rights.provenance_sha256 != expected:
            raise ValueError("rights provenance digest does not match record semantics")
        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "description", description)

    def to_data(self) -> dict[str, str]:
        """Return the untrusted runtime data without converting it into instructions."""

        return {"description": self.description, "id": self.record_id}

    def _semantic_data(self) -> dict[str, object]:
        return self.to_data() | {"rights": self.rights.to_data()}


@dataclass(frozen=True, slots=True)
class FoundationPack:
    """Validated creative data with a semantic, deterministic fingerprint."""

    pack_id: str
    pack_version: str
    runtime_api: int
    rubric: tuple[CreativeRecord, ...]
    anti_patterns: tuple[CreativeRecord, ...]
    file_digests: tuple[tuple[str, str], ...]
    fingerprint: str = field(init=False)

    @classmethod
    def load(
        cls,
        path: os.PathLike[str] | str,
        *,
        allowed_root: os.PathLike[str] | str,
        expected_manifest_digest: str,
    ) -> FoundationPack:
        """Load a pack against a caller-owned manifest trust anchor."""

        return load_foundation_pack(
            path,
            allowed_root=allowed_root,
            expected_manifest_digest=expected_manifest_digest,
        )

    def __post_init__(self) -> None:
        pack_id = _text(self.pack_id, "pack_id", 64)
        version = _text(self.pack_version, "pack_version", 32)
        if _PACK_ID.fullmatch(pack_id) is None:
            raise ValueError("pack_id has an invalid format")
        if _SEMVER.fullmatch(version) is None:
            raise ValueError("pack version must be semantic x.y.z")
        if isinstance(self.runtime_api, bool) or self.runtime_api != 1:
            raise ValueError("runtime API is not compatible")
        if not isinstance(self.rubric, tuple) or not isinstance(self.anti_patterns, tuple):
            raise TypeError("pack records must be tuples")
        if len(self.rubric) != len(_RUBRIC_IDS) or not 1 <= len(self.anti_patterns) <= len(
            _ANTI_PATTERN_IDS
        ):
            raise ValueError("pack record count is outside the limit")
        all_records = self.rubric + self.anti_patterns
        if any(not isinstance(record, CreativeRecord) for record in all_records):
            raise TypeError("pack records must be CreativeRecord values")
        if tuple(record.record_id for record in self.rubric) != _RUBRIC_IDS:
            raise ValueError("rubric contains duplicate or unknown ids")
        if not 1 <= len(self.anti_patterns) <= _MAX_PACK_RECORDS:
            raise ValueError("anti-pattern record count is outside the limit")
        anti_ids = tuple(record.record_id for record in self.anti_patterns)
        if len(set(anti_ids)) != len(anti_ids) or not set(anti_ids) <= _ANTI_PATTERN_IDS:
            raise ValueError("anti-patterns contain duplicate or unknown ids")
        if not isinstance(self.file_digests, tuple):
            raise TypeError("file_digests must be a tuple")
        if len(self.file_digests) != len(_PACK_FILES):
            raise ValueError("file_digests count is outside the limit")
        if tuple(name for name, _ in self.file_digests) != _PACK_FILES:
            raise ValueError("file_digests must cover the exact foundation pack files")
        digests = tuple(
            (name, _sha256(digest, "file digest")) for name, digest in self.file_digests
        )
        semantic = {
            "anti_patterns": [record._semantic_data() for record in self.anti_patterns],
            "pack_id": pack_id,
            "pack_version": version,
            "rubric": [record._semantic_data() for record in self.rubric],
            "runtime_api": self.runtime_api,
        }
        object.__setattr__(self, "pack_id", pack_id)
        object.__setattr__(self, "pack_version", version)
        object.__setattr__(self, "file_digests", digests)
        object.__setattr__(
            self, "fingerprint", hashlib.sha256(_canonical_json_bytes(semantic)).hexdigest()
        )


_SELECTION_CONTRACT: Final = (
    "hard_constraints_valid",
    "task_fit",
    "clarity",
    "novelty",
    "preference_optional",
    "stable_candidate_id",
)


@dataclass(frozen=True, slots=True)
class CreativePlan:
    """Bounded divergent directives and an explicit convergent contract."""

    active: bool
    mode: Mode
    directives: tuple[CreativeDirective, ...]
    rubric: tuple[CreativeRecord, ...]
    anti_patterns: tuple[CreativeRecord, ...]
    candidate_count: int
    selection_contract: tuple[str, ...]
    request_fingerprint: str
    pack_fingerprint: str | None = None
    context_limit: int = 8 * 1024

    def __post_init__(self) -> None:
        if type(self.active) is not bool:
            raise TypeError("active must be a boolean")
        if not isinstance(self.mode, Mode):
            raise TypeError("mode must be Mode")
        if not isinstance(self.directives, tuple):
            raise TypeError("directives must be a tuple")
        if len(self.directives) > len(CreativeMechanism):
            raise ValueError("directive count is outside the limit")
        if any(not isinstance(directive, CreativeDirective) for directive in self.directives):
            raise TypeError("directives must be CreativeDirective values")
        if not isinstance(self.rubric, tuple) or not isinstance(self.anti_patterns, tuple):
            raise TypeError("creative records must be tuples")
        if len(self.rubric) > len(_RUBRIC_IDS) or len(self.anti_patterns) > len(_ANTI_PATTERN_IDS):
            raise ValueError("creative record count is outside the limit")
        if any(
            not isinstance(record, CreativeRecord) for record in self.rubric + self.anti_patterns
        ):
            raise TypeError("creative records must be CreativeRecord values")
        if isinstance(self.candidate_count, bool) or not isinstance(self.candidate_count, int):
            raise TypeError("candidate_count must be an integer")
        if not 0 <= self.candidate_count <= 16:
            raise ValueError("candidate_count must be between 0 and 16")
        if not isinstance(self.selection_contract, tuple):
            raise TypeError("selection_contract must be a tuple")
        for value in self.selection_contract:
            _text(value, "selection_contract", _MAX_ID)
        request_fingerprint = _sha256(self.request_fingerprint, "request_fingerprint")
        object.__setattr__(self, "request_fingerprint", request_fingerprint)
        if self.pack_fingerprint is not None:
            fingerprint = _sha256(self.pack_fingerprint, "pack_fingerprint")
            object.__setattr__(self, "pack_fingerprint", fingerprint)
        if isinstance(self.context_limit, bool) or not isinstance(self.context_limit, int):
            raise TypeError("context_limit must be an integer")
        if not 512 <= self.context_limit <= MAX_CREATIVE_CONTEXT_CHARS:
            raise ValueError("context_limit is outside the supported range")
        if self.active:
            if self.mode is not Mode.CREATIVE:
                raise ValueError("active creative plan requires creative mode")
            if self.directives != _trusted_directives(request_fingerprint):
                raise ValueError("active creative plan requires the five trusted directives")
            if self.selection_contract != _SELECTION_CONTRACT:
                raise ValueError("active creative plan requires the fixed selection contract")
            if self.candidate_count < 1:
                raise ValueError("active creative plan requires response candidates")
        elif (
            self.directives
            or self.rubric
            or self.anti_patterns
            or self.candidate_count
            or self.selection_contract
            or self.pack_fingerprint is not None
        ):
            raise ValueError("inactive creative plan must not retrieve or direct creative work")
        if len(self.render_context()) > self.context_limit:
            raise ValueError("creative context exceeds context_limit")

    def render_context(self) -> str:
        """Render trusted mechanics and untrusted pack records in separate stable blocks."""

        if not self.active:
            return ""
        directives = [
            {
                "approach": directive.approach,
                "mechanism": directive.mechanism.value,
                "strategy_id": directive.strategy_id,
            }
            for directive in self.directives
        ]
        records = {
            "anti_patterns": [record.to_data() for record in self.anti_patterns],
            "rubric": [record.to_data() for record in self.rubric],
        }
        return "\n".join(
            (
                "TRUSTED_CREATIVE_MECHANISM_DIRECTIVES_JSON:",
                json.dumps(directives, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "UNTRUSTED_CREATIVE_PACK_DATA_JSON:",
                json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "END_UNTRUSTED_CREATIVE_PACK_DATA",
                "CONVERGENT_SELECTION_CONTRACT_JSON:",
                json.dumps(self.selection_contract, separators=(",", ":")),
                "END_CREATIVE_STUDIO_CONTEXT",
            )
        )


def _metric(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be finite and between 0 and 1")
    return result


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Explicit measurable fields for one generated response candidate."""

    candidate_id: str
    hard_constraints_valid: bool
    task_fit: float
    clarity: float
    novelty: float
    preference: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id", _MAX_ID))
        if type(self.hard_constraints_valid) is not bool:
            raise TypeError("hard_constraints_valid must be a boolean")
        for field_name in ("task_fit", "clarity", "novelty"):
            object.__setattr__(self, field_name, _metric(getattr(self, field_name), field_name))
        if self.preference is not None:
            object.__setattr__(self, "preference", _metric(self.preference, "preference"))


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    """Inspectable ranking outcome without hidden model reasoning."""

    selected_id: str
    ranked_ids: tuple[str, ...]
    decision_basis: tuple[str, ...]

    def __post_init__(self) -> None:
        selected = _text(self.selected_id, "selected_id", _MAX_ID)
        if not isinstance(self.ranked_ids, tuple) or not self.ranked_ids:
            raise ValueError("ranked_ids must be a non-empty tuple")
        if len(self.ranked_ids) > 16:
            raise ValueError("ranked_ids exceeds the candidate limit")
        ranked = tuple(_text(value, "ranked_ids", _MAX_ID) for value in self.ranked_ids)
        if len(set(ranked)) != len(ranked):
            raise ValueError("ranked_ids must be unique")
        if ranked[0] != selected:
            raise ValueError("selected_id must be the first ranked candidate")
        if not isinstance(self.decision_basis, tuple) or not self.decision_basis:
            raise ValueError("decision_basis must be a non-empty tuple")
        basis = tuple(_text(value, "decision_basis", _MAX_ID) for value in self.decision_basis)
        if basis != _SELECTION_CONTRACT:
            raise ValueError("decision_basis must use the fixed selection contract")
        object.__setattr__(self, "selected_id", selected)
        object.__setattr__(self, "ranked_ids", ranked)
        object.__setattr__(self, "decision_basis", basis)


class NoValidCandidateError(ValueError):
    """Raised when convergence has no hard-constraint-valid candidate."""


def select_candidate(scores: tuple[CandidateScore, ...]) -> CandidateSelection:
    """Rank candidates by validity, fit, clarity, novelty, preference, then stable id."""

    if not isinstance(scores, tuple) or not scores:
        raise ValueError("scores must be a non-empty tuple")
    if len(scores) > 16:
        raise ValueError("scores exceeds the candidate limit")
    if any(not isinstance(score, CandidateScore) for score in scores):
        raise TypeError("scores must contain CandidateScore values")
    identifiers = tuple(score.candidate_id for score in scores)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("candidate ids must be unique")
    valid_scores = tuple(score for score in scores if score.hard_constraints_valid)
    if not valid_scores:
        raise NoValidCandidateError("no valid candidate satisfies the hard constraints")
    ranked = tuple(
        sorted(
            valid_scores,
            key=lambda score: (
                -int(score.hard_constraints_valid),
                -score.task_fit,
                -score.clarity,
                -score.novelty,
                -(score.preference if score.preference is not None else 0.0),
                score.candidate_id,
            ),
        )
    )
    return CandidateSelection(
        selected_id=ranked[0].candidate_id,
        ranked_ids=tuple(score.candidate_id for score in ranked),
        decision_basis=_SELECTION_CONTRACT,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_number(_: str) -> object:
    raise ValueError("JSON non-finite or floating-point numbers are not allowed")


def _validate_json_tree(value: object, *, depth: int = 0, count: list[int] | None = None) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > _MAX_JSON_NODES:
        raise ValueError("JSON node limit exceeded")
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    if value is None or type(value) in {bool, int}:
        return
    if isinstance(value, str):
        for character in value:
            category = unicodedata.category(character)
            if (
                category in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                or unicodedata.bidirectional(character) in _FORBIDDEN_BIDI
            ):
                raise ValueError(
                    "JSON string contains an unsafe control, line separator, or bidi character"
                )
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_tree(item, depth=depth + 1, count=count)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_json_tree(key, depth=depth + 1, count=count)
            _validate_json_tree(item, depth=depth + 1, count=count)
        return
    raise ValueError("JSON contains an unsupported value type")


def _strict_json(raw: bytes, label: str) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from error
    _validate_json_tree(value)
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON root must be an object")
    return value


def _exact_fields(value: object, fields: frozenset[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} has missing or unknown fields")
    return cast(dict[str, object], value)


def _close_after_failure(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except BaseException:
        pass


def _open_absolute_directory(path: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.path.sep, flags)
    try:
        for part in Path(path).parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            try:
                os.close(descriptor)
            except BaseException:
                _close_after_failure(next_descriptor)
                raise
            descriptor = next_descriptor
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValueError("allowed root is not a directory")
        return descriptor
    except BaseException:
        _close_after_failure(descriptor)
        raise


def _open_pack_directory(path: os.PathLike[str] | str, allowed_root: os.PathLike[str] | str) -> int:
    raw_root_path = os.fspath(allowed_root)
    raw_pack_path = os.fspath(path)
    if not isinstance(raw_root_path, str) or not isinstance(raw_pack_path, str):
        raise TypeError("pack path and allowed root must be text paths")
    if "\x00" in raw_root_path or "\x00" in raw_pack_path:
        raise ValueError("pack path and allowed root must not contain NUL")
    root_path = os.path.abspath(raw_root_path)
    if ".." in Path(raw_pack_path).parts:
        raise ValueError("pack path contains traversal")
    pack_path = os.path.abspath(
        raw_pack_path if os.path.isabs(raw_pack_path) else os.path.join(root_path, raw_pack_path)
    )
    try:
        if os.path.commonpath((root_path, pack_path)) != root_path:
            raise ValueError("pack path is outside allowed root")
    except ValueError as error:
        raise ValueError("pack path is outside allowed root") from error
    relative = os.path.relpath(pack_path, root_path)
    parts = () if relative == "." else Path(relative).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("pack path contains traversal")
    descriptor: int | None = None
    try:
        descriptor = _open_absolute_directory(root_path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        for part in parts:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            try:
                os.close(descriptor)
            except BaseException:
                _close_after_failure(next_descriptor)
                raise
            descriptor = next_descriptor
        return descriptor
    except BaseException as error:
        if descriptor is not None:
            _close_after_failure(descriptor)
        if isinstance(error, OSError):
            raise ValueError("pack path is missing, a symlink, or not a directory") from error
        raise


def _read_regular_file(directory_fd: int, name: str, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as error:
        raise ValueError(
            f"unable to open regular pack file {name}; symlinks are forbidden"
        ) from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError(f"pack file {name} must be a single-link regular file")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError(f"pack file {name} changed while opening")
        if opened.st_size < 1 or opened.st_size > limit:
            raise ValueError(f"pack file {name} exceeds its size limit")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise ValueError(f"pack file {name} changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError(f"pack file {name} exceeds its declared size")
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(
            getattr(opened, field) != getattr(after_fd, field) for field in stable_fields
        ) or any(getattr(opened, field) != getattr(after_path, field) for field in stable_fields):
            raise ValueError(f"pack file {name} changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _manifest(raw: bytes) -> tuple[str, str, dict[str, tuple[int, str]]]:
    data = _exact_fields(
        _strict_json(raw, "manifest"),
        frozenset({"schema", "pack_id", "pack_version", "runtime_api", "rights_policy", "files"}),
        "manifest",
    )
    if data["schema"] != "foundation-pack/v1":
        raise ValueError("manifest schema is not compatible")
    pack_id = _text(data["pack_id"], "manifest pack_id", 64)
    version = _text(data["pack_version"], "manifest pack_version", 32)
    if _PACK_ID.fullmatch(pack_id) is None:
        raise ValueError("manifest pack_id is invalid")
    if _SEMVER.fullmatch(version) is None:
        raise ValueError("manifest version is not semantic x.y.z")
    if data["runtime_api"] != 1 or type(data["runtime_api"]) is not int:
        raise ValueError("manifest runtime API is not compatible")
    if data["rights_policy"] != "creative-rights/v1":
        raise ValueError("manifest rights policy is not compatible")
    files = _exact_fields(data["files"], frozenset(_PACK_FILES), "manifest files")
    descriptors: dict[str, tuple[int, str]] = {}
    for name in _PACK_FILES:
        descriptor = _exact_fields(
            files[name],
            frozenset({"bytes", "sha256"}),
            f"manifest file {name}",
        )
        byte_count = descriptor["bytes"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
            raise ValueError("manifest file bytes must be a positive integer")
        if byte_count > _MAX_PACK_FILE_BYTES:
            raise ValueError("manifest file size exceeds limit")
        descriptors[name] = (byte_count, _sha256(descriptor["sha256"], "manifest digest"))
    return pack_id, version, descriptors


def _record_from_json(value: object, *, allowed_ids: frozenset[str], label: str) -> CreativeRecord:
    data = _exact_fields(value, frozenset({"id", "description", "rights"}), label)
    record_id = _text(data["id"], f"{label} id", _MAX_ID)
    if record_id not in allowed_ids:
        raise ValueError(f"{label} contains an unknown id")
    description = _text(data["description"], f"{label} description", _MAX_DESCRIPTION)
    rights_data = _exact_fields(
        data["rights"],
        frozenset(
            {
                "eligible",
                "basis",
                "owner",
                "license",
                "use_scope",
                "redistribution_allowed",
                "provenance_sha256",
            }
        ),
        f"{label} rights",
    )
    rights = RightsDeclaration(**rights_data)
    return CreativeRecord(record_id, description, rights)


def _records(
    raw: bytes, *, schema: str, allowed_ids: frozenset[str], label: str
) -> tuple[CreativeRecord, ...]:
    data = _exact_fields(_strict_json(raw, label), frozenset({"schema", "records"}), label)
    if data["schema"] != schema:
        raise ValueError(f"{label} schema is not compatible")
    values = data["records"]
    if not isinstance(values, list) or not 1 <= len(values) <= _MAX_PACK_RECORDS:
        raise ValueError(f"{label} record count is outside the limit")
    records = tuple(
        _record_from_json(value, allowed_ids=allowed_ids, label=f"{label} record")
        for value in values
    )
    identifiers = tuple(record.record_id for record in records)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{label} contains duplicate ids")
    return records


def plan(
    route_or_mode: RouteDecision | Mode,
    request: str,
    *,
    pack: FoundationPack | None = None,
    context_limit: int = 8 * 1024,
) -> CreativePlan:
    """Create a deterministic plan only when the selected mode is creative."""

    canonical_request = _text(
        request,
        "request",
        MAX_CREATIVE_REQUEST_CHARS,
        multiline=True,
    )
    request_fingerprint = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    if isinstance(route_or_mode, RouteDecision):
        mode = route_or_mode.mode
        candidate_count = route_or_mode.candidate_count
    elif isinstance(route_or_mode, Mode):
        mode = route_or_mode
        candidate_count = 5
    else:
        raise TypeError("route_or_mode must be RouteDecision or Mode")
    if mode is not Mode.CREATIVE:
        return CreativePlan(
            active=False,
            mode=mode,
            directives=(),
            rubric=(),
            anti_patterns=(),
            candidate_count=0,
            selection_contract=(),
            request_fingerprint=request_fingerprint,
            context_limit=context_limit,
        )
    if pack is not None and not isinstance(pack, FoundationPack):
        raise TypeError("pack must be FoundationPack")
    directives = _trusted_directives(request_fingerprint)
    return CreativePlan(
        active=True,
        mode=mode,
        directives=directives,
        rubric=pack.rubric if pack is not None else (),
        anti_patterns=pack.anti_patterns if pack is not None else (),
        candidate_count=candidate_count,
        selection_contract=_SELECTION_CONTRACT,
        request_fingerprint=request_fingerprint,
        pack_fingerprint=pack.fingerprint if pack is not None else None,
        context_limit=context_limit,
    )


def load_foundation_pack(
    path: os.PathLike[str] | str,
    *,
    allowed_root: os.PathLike[str] | str,
    expected_manifest_digest: str,
) -> FoundationPack:
    """Load a pack only when its bytes match an external manifest trust anchor."""

    pinned_manifest = _sha256(expected_manifest_digest, "expected manifest digest")
    directory_fd = _open_pack_directory(path, allowed_root)
    try:
        manifest_raw = _read_regular_file(directory_fd, "manifest.json", _MAX_MANIFEST_BYTES)
        if hashlib.sha256(manifest_raw).hexdigest() != pinned_manifest:
            raise ValueError("manifest digest does not match the expected trust anchor")
        pack_id, version, descriptors = _manifest(manifest_raw)
        raw_files = {
            name: _read_regular_file(directory_fd, name, _MAX_PACK_FILE_BYTES)
            for name in _PACK_FILES
        }
    finally:
        os.close(directory_fd)
    for name, raw in raw_files.items():
        declared_bytes, declared_digest = descriptors[name]
        if len(raw) != declared_bytes:
            raise ValueError(f"pack file {name} bytes do not match manifest")
        if hashlib.sha256(raw).hexdigest() != declared_digest:
            raise ValueError(f"pack file {name} digest does not match manifest")
    rubric = _records(
        raw_files["rubric.json"],
        schema="creative-rubric/v1",
        allowed_ids=frozenset(_RUBRIC_IDS),
        label="rubric",
    )
    anti_patterns = _records(
        raw_files["anti-patterns.json"],
        schema="creative-anti-patterns/v1",
        allowed_ids=_ANTI_PATTERN_IDS,
        label="anti-patterns",
    )
    return FoundationPack(
        pack_id=pack_id,
        pack_version=version,
        runtime_api=1,
        rubric=rubric,
        anti_patterns=anti_patterns,
        file_digests=tuple(
            (name, hashlib.sha256(raw_files[name]).hexdigest()) for name in _PACK_FILES
        ),
    )


def load_bundled_foundation(
    path: os.PathLike[str] | str,
    *,
    allowed_root: os.PathLike[str] | str,
) -> FoundationPack:
    """Load the bundled private Foundation pack against its code-owned digest."""

    return FoundationPack.load(
        path,
        allowed_root=allowed_root,
        expected_manifest_digest=FOUNDATION_MANIFEST_SHA256,
    )


__all__ = [
    "CandidateScore",
    "CandidateSelection",
    "CreativeDirective",
    "CreativeMechanism",
    "CreativePlan",
    "CreativeRecord",
    "CreativeStrategy",
    "FOUNDATION_MANIFEST_SHA256",
    "FoundationPack",
    "NoValidCandidateError",
    "RightsDeclaration",
    "load_foundation_pack",
    "load_bundled_foundation",
    "plan",
    "select_candidate",
]
