"""Immutable contracts shared by the Humanlike runtime and host adapters."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import StrEnum
from math import isfinite
from typing import Any


class Mode(StrEnum):
    """Primary cognitive mode selected for a turn."""

    SOCIAL = "social"
    SUPPORT = "support"
    TASK = "task"
    RESEARCH = "research"
    CREATIVE = "creative"
    REPAIR = "repair"
    HIGH_STAKES = "high_stakes"
    META_TRUTH = "meta_truth"
    REFLECTIVE = "reflective"


class SocialMove(StrEnum):
    """Social action the response should perform."""

    CONNECT = "connect"
    ACKNOWLEDGE = "acknowledge"
    LISTEN = "listen"
    ANSWER = "answer"
    ASK = "ask"
    CHALLENGE = "challenge"
    REVISE = "revise"
    CREATE = "create"
    ACT = "act"
    REFUSE = "refuse"
    WAIT = "wait"


class MemoryScope(StrEnum):
    """Durable-memory permission inferred for a turn or session."""

    DEFAULT = "default"
    ITEM_NO_SAVE = "item_no_save"
    SESSION_NO_SAVE = "session_no_save"


def _json_safe(value: Any) -> Any:
    """Convert contract values to structures accepted by ``json.dumps``."""

    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_safe(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON-safe floats must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported contract value: {type(value).__name__}")


class _JsonSafeContract:
    """Provide uniform JSON-safe serialization for frozen contracts."""

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-safe mapping of public contract fields."""

        return {field.name: _json_safe(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class TurnInput(_JsonSafeContract):
    """Minimal host input required to prepare one turn."""

    text: str = ""
    turn_id: str = ""
    session_id: str = ""
    locale: str = "und"
    elapsed_seconds: float | None = None
    memory_scope: MemoryScope = MemoryScope.DEFAULT


@dataclass(frozen=True, slots=True)
class RouteDecision(_JsonSafeContract):
    """Deterministic routing result for response preparation."""

    mode: Mode = Mode.TASK
    social_move: SocialMove = SocialMove.ANSWER
    response_budget: int = 400
    candidate_count: int = 1
    constraints: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    confidence: float = 0.0
    memory_scope: MemoryScope = MemoryScope.DEFAULT
    requires_tools: bool = False
    strict_truth: bool = False


@dataclass(frozen=True, slots=True)
class ContextFragment(_JsonSafeContract):
    """One bounded context block; tail blocks render after priority-ranked blocks."""

    fragment_id: str = ""
    content: str = ""
    source: str = ""
    priority: int = 0
    hard: bool = False
    tail: bool = False
    truncatable: bool = True

    def __post_init__(self) -> None:
        if type(self.truncatable) is not bool:
            raise TypeError("truncatable must be a boolean")


def _rank_fragments(
    fragments: tuple[ContextFragment, ...],
) -> list[tuple[int, ContextFragment]]:
    ranked = [(index, fragment) for index, fragment in enumerate(fragments) if fragment.content]
    return sorted(ranked, key=lambda item: (item[1].tail, -item[1].priority, item[0]))


def _join_fragments(fragments: list[tuple[int, ContextFragment]]) -> str:
    ranked = sorted(
        fragments,
        key=lambda item: (item[1].tail, -item[1].priority, item[0]),
    )
    return "\n\n".join(fragment.content for _, fragment in ranked)


@dataclass(frozen=True, slots=True)
class TurnPlan(_JsonSafeContract):
    """Bounded behavioral plan returned to an agent host."""

    turn_id: str = ""
    session_id: str = ""
    route: RouteDecision = RouteDecision()
    fragments: tuple[ContextFragment, ...] = ()
    context_limit: int = 4_000
    memory_scope: MemoryScope = MemoryScope.DEFAULT

    @classmethod
    def safe_default(cls, turn_id: str, session_id: str) -> TurnPlan:
        """Return a conservative plan with no retrieved context."""

        return cls(turn_id=turn_id, session_id=session_id)

    def selected_fragments(self) -> tuple[ContextFragment, ...]:
        """Return the exact bounded fragment selection in render order."""

        if self.context_limit < 0:
            raise ValueError("context_limit must be non-negative")

        ranked = _rank_fragments(self.fragments)
        selected = [(index, fragment) for index, fragment in ranked if fragment.hard]
        hard_context = _join_fragments(selected)
        if len(hard_context) > self.context_limit:
            raise ValueError("hard context fragments exceed context_limit")

        for index, fragment in (item for item in ranked if not item[1].hard):
            full_candidate = _join_fragments([*selected, (index, fragment)])
            if len(full_candidate) <= self.context_limit:
                selected.append((index, fragment))
                continue
            if not fragment.truncatable:
                continue

            low = 0
            high = len(fragment.content)
            while low < high:
                middle = (low + high + 1) // 2
                shortened = replace(fragment, content=fragment.content[:middle])
                if len(_join_fragments([*selected, (index, shortened)])) <= self.context_limit:
                    low = middle
                else:
                    high = middle - 1
            if low:
                selected.append((index, replace(fragment, content=fragment.content[:low])))
            break

        ordered = sorted(selected, key=lambda item: (item[1].tail, -item[1].priority, item[0]))
        return tuple(fragment for _, fragment in ordered)

    def render_context(self) -> str:
        """Render context by priority without dropping any hard fragment."""

        return "\n\n".join(fragment.content for fragment in self.selected_fragments())


@dataclass(frozen=True, slots=True)
class TurnOutcome(_JsonSafeContract):
    """Metadata reported by a host after producing a response."""

    turn_id: str = ""
    session_id: str = ""
    success: bool = False
    response_chars: int = 0
    tactic_ids: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BehaviorReceipt(_JsonSafeContract):
    """Privacy-safe behavioral metadata; raw turn text is intentionally absent."""

    turn_id: str = ""
    session_id: str = ""
    mode: Mode = Mode.TASK
    social_move: SocialMove = SocialMove.ANSWER
    memory_scope: MemoryScope = MemoryScope.DEFAULT
    context_chars: int = 0
    fragment_ids: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    tactic_ids: tuple[str, ...] = ()
    memory_read_count: int = 0
    memory_write_count: int = 0
    tool_names: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()
    turn_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class SessionRef(_JsonSafeContract):
    """Opaque reference to host-owned session state."""

    session_id: str = ""
    user_id: str | None = None
    locale: str = "und"
    started_at: str | None = None
