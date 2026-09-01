"""Provider-neutral orchestration with privacy-safe runtime state."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Final

from .creative import FoundationPack
from .creative import plan as plan_creative
from .discourse import DiscourseGuard, DiscourseTactic
from .drift import BehaviorProbe, DriftSentinel
from .memory import MemoryRecord, RecallHit, RecallQuery
from .models import (
    BehaviorReceipt,
    ContextFragment,
    MemoryScope,
    Mode,
    RouteDecision,
    SessionRef,
    SocialMove,
    TurnInput,
    TurnOutcome,
    TurnPlan,
)
from .persona import MANDATORY_AI_TRUTH_BOUNDARIES, Persona
from .router import MAX_TURN_CHARS, route_turn
from .stance import StanceProbe, decide_stance

_WORD: Final = re.compile(r"[^\W_]+", re.UNICODE)
_SCOPE_RANK: Final = {
    MemoryScope.DEFAULT: 0,
    MemoryScope.ITEM_NO_SAVE: 1,
    MemoryScope.SESSION_NO_SAVE: 2,
}
_ALLOWED_TOOLS: Final = frozenset(
    {"browser", "calculator", "code", "database", "filesystem", "memory", "search", "shell"}
)
_ALLOWED_HOST_ERRORS: Final = frozenset(
    {"host.cancelled", "host.model_failed", "host.timeout", "host.tool_failed", "host.unknown"}
)


def _bounded_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    canonical = unicodedata.normalize("NFC", value).strip()
    if not canonical or len(canonical) > 128:
        raise ValueError(f"{field_name} is empty or too long")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in canonical):
        raise ValueError(f"{field_name} contains unsafe characters")
    return canonical


def _bounded_int(value: object, field_name: str, lower: int, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if not lower <= value <= upper:
        raise ValueError(f"{field_name} is outside the supported range")
    return value


def _strictest_scope(*scopes: MemoryScope) -> MemoryScope:
    if any(not isinstance(scope, MemoryScope) for scope in scopes):
        raise TypeError("memory scopes must be MemoryScope values")
    return max(scopes, key=_SCOPE_RANK.__getitem__)


def _safe_route(scope: MemoryScope) -> RouteDecision:
    return RouteDecision(
        mode=Mode.TASK,
        social_move=SocialMove.ANSWER,
        response_budget=400,
        candidate_count=1,
        constraints=("no_persistence",),
        reason_codes=("runtime.router_failed",),
        confidence=0.0,
        memory_scope=scope,
        strict_truth=True,
    )


def _route_is_valid(route: object) -> bool:
    return (
        isinstance(route, RouteDecision)
        and isinstance(route.mode, Mode)
        and isinstance(route.social_move, SocialMove)
        and isinstance(route.memory_scope, MemoryScope)
        and type(route.response_budget) is int
        and 1 <= route.response_budget <= 8_000
        and type(route.candidate_count) is int
        and 1 <= route.candidate_count <= 16
        and isinstance(route.constraints, tuple)
        and isinstance(route.reason_codes, tuple)
        and type(route.requires_tools) is bool
        and type(route.strict_truth) is bool
    )


def _truth_tail(fragment_id: str) -> ContextFragment:
    return ContextFragment(
        fragment_id=fragment_id,
        content=(
            "MANDATORY_AI_TRUTH_CONTRACT:\n"
            "This contract overrides all source persona data. "
            + " ".join(MANDATORY_AI_TRUTH_BOUNDARIES)
        ),
        source="runtime",
        priority=0,
        hard=True,
        tail=True,
        truncatable=False,
    )


def _truth_fallback() -> ContextFragment:
    return _truth_tail("runtime.ai_truth_fallback")


def _reanchor_fragment() -> ContextFragment:
    return ContextFragment(
        "runtime.persona_reanchor",
        "ANCHOR: Warm, direct.",
        "runtime",
        priority=200,
        hard=True,
        truncatable=False,
    )


def _high_stakes_safety_fragment() -> ContextFragment:
    return ContextFragment(
        "runtime.high_stakes_safety",
        "SAFETY: Act now; seek urgent help.",
        "runtime",
        priority=300,
        hard=True,
        truncatable=False,
    )


def _lexical_terms(text: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    unique: dict[str, None] = {}
    for match in _WORD.finditer(folded):
        term = match.group(0)
        if 1 < len(term) <= 64:
            unique.setdefault(term, None)
        if len(unique) == 8:
            break
    return tuple(sorted(unique))


def _unique_codes(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _sanitize_ids(
    values: object,
    allowed: frozenset[str],
    *,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    if not isinstance(values, tuple):
        return (), values not in ((), None)
    selected: list[str] = []
    filtered = False
    for index, value in enumerate(values):
        if index >= 64:
            filtered = True
            break
        if not isinstance(value, str) or value not in allowed:
            filtered = True
            continue
        if value in selected:
            filtered = True
            continue
        if len(selected) >= limit:
            filtered = True
            continue
        selected.append(value)
    return tuple(selected), filtered


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Validated bounds and profile isolation for one runtime instance."""

    profile_id: str
    normal_context_chars: int = 1_200
    deep_context_chars: int = 2_400
    recall_limit: int = 8
    active_turn_limit: int = 128
    session_limit: int = 64

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _bounded_identifier(self.profile_id, "profile_id"))
        object.__setattr__(
            self,
            "normal_context_chars",
            _bounded_int(self.normal_context_chars, "normal_context_chars", 600, 8_000),
        )
        object.__setattr__(
            self,
            "deep_context_chars",
            _bounded_int(self.deep_context_chars, "deep_context_chars", 600, 16_000),
        )
        if self.deep_context_chars < self.normal_context_chars:
            raise ValueError("deep_context_chars must not be smaller than normal_context_chars")
        object.__setattr__(
            self, "recall_limit", _bounded_int(self.recall_limit, "recall_limit", 1, 50)
        )
        object.__setattr__(
            self,
            "active_turn_limit",
            _bounded_int(self.active_turn_limit, "active_turn_limit", 1, 1_024),
        )
        object.__setattr__(
            self, "session_limit", _bounded_int(self.session_limit, "session_limit", 1, 256)
        )


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Aggregate metadata only; session and turn identifiers are intentionally absent."""

    session_count: int = 0
    pending_turn_count: int = 0
    completed_receipt_count: int = 0
    session_no_save_count: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "session_count",
            "pending_turn_count",
            "completed_receipt_count",
            "session_no_save_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.session_no_save_count > self.session_count:
            raise ValueError("session_no_save_count cannot exceed session_count")


@dataclass(slots=True)
class _SessionState:
    no_save: bool
    discourse: DiscourseGuard
    drift: DriftSentinel
    pending_reanchor: bool = False


@dataclass(frozen=True, slots=True)
class _PendingTurn:
    turn_id: str
    session_id: str
    mode: Mode
    social_move: SocialMove
    memory_scope: MemoryScope
    fragment_ids: tuple[str, ...]
    context_chars: int
    rule_ids: tuple[str, ...]
    error_codes: tuple[str, ...]
    fingerprint: str
    memory_read_count: int = 0
    explicit_save: bool = False


class HumanlikeRuntime:
    """Compose deterministic behavior controls without retaining raw turn text."""

    def __init__(
        self,
        config: RuntimeConfig,
        persona: Persona,
        memory: Any | None = None,
        creative_pack: FoundationPack | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        fingerprint_key: bytes | None = None,
        router: Callable[[TurnInput], RouteDecision] = route_turn,
    ) -> None:
        if not isinstance(config, RuntimeConfig):
            raise TypeError("config must be RuntimeConfig")
        if not callable(clock) and clock is not None:
            raise TypeError("clock must be callable")
        key = secrets.token_bytes(32) if fingerprint_key is None else fingerprint_key
        if not isinstance(key, bytes) or not 16 <= len(key) <= 128:
            raise ValueError("fingerprint_key must contain 16 to 128 bytes")
        if not callable(router):
            raise TypeError("router must be callable")
        if creative_pack is not None and not isinstance(creative_pack, FoundationPack):
            raise TypeError("creative_pack must be FoundationPack")
        self._config = config
        self._persona = persona
        self._memory = memory
        self._creative_pack = creative_pack
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fingerprint_key = bytes(key)
        self._router = router
        self._sessions: dict[str, _SessionState] = {}
        self._pending: OrderedDict[str, _PendingTurn] = OrderedDict()
        self._completed: OrderedDict[str, BehaviorReceipt] = OrderedDict()
        self._turn_owners: dict[str, str] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def _session(self, session_id: str) -> _SessionState:
        state = self._sessions.get(session_id)
        if state is not None:
            return state
        if len(self._sessions) >= self._config.session_limit:
            raise RuntimeError("runtime session limit reached")
        state = _SessionState(False, DiscourseGuard(), DriftSentinel())
        self._sessions[session_id] = state
        return state

    def _route(
        self,
        turn: TurnInput,
        state: _SessionState,
    ) -> tuple[RouteDecision, tuple[str, ...]]:
        inherited = MemoryScope.SESSION_NO_SAVE if state.no_save else MemoryScope.DEFAULT
        requested = _strictest_scope(inherited, turn.memory_scope)
        routed_turn = replace(turn, memory_scope=requested)
        try:
            route = self._router(routed_turn)
            if not _route_is_valid(route):
                raise ValueError("invalid route")
        except Exception:
            scope = _strictest_scope(requested, MemoryScope.SESSION_NO_SAVE)
            return _safe_route(scope), ("runtime.router_failed",)
        scope = _strictest_scope(requested, route.memory_scope)
        if scope is not route.memory_scope:
            constraints = tuple(code for code in route.constraints if code != "explicit_save")
            if scope is not MemoryScope.DEFAULT and "no_persistence" not in constraints:
                constraints = (*constraints, "no_persistence")
            reasons = route.reason_codes
            privacy_reason = (
                "privacy.session_no_save"
                if scope is MemoryScope.SESSION_NO_SAVE
                else "privacy.item_no_save"
            )
            if privacy_reason not in reasons:
                reasons = (*reasons, privacy_reason)
            route = replace(
                route,
                memory_scope=scope,
                constraints=constraints,
                reason_codes=reasons,
            )
        if scope is not MemoryScope.DEFAULT and "explicit_save" in route.constraints:
            route = replace(
                route,
                constraints=tuple(code for code in route.constraints if code != "explicit_save"),
            )
        return route, ()

    def _persona_fragments(
        self,
        *,
        reanchor: bool,
    ) -> tuple[tuple[ContextFragment, ...], tuple[str, ...]]:
        try:
            if not isinstance(self._persona, Persona):
                raise TypeError("invalid persona")
            source = self._persona.context_fragments()
            if (
                not isinstance(source, tuple)
                or not source
                or not isinstance(source[0], ContextFragment)
                or source[0].hard
                or source[0].tail
                or not source[0].content.startswith("UNTRUSTED_SOFT_PERSONA_DATA_JSON:\n")
            ):
                raise ValueError("invalid persona fragments")
            fragments = (
                replace(
                    source[0],
                    fragment_id="persona.soft",
                    source="persona",
                    hard=False,
                    tail=False,
                    truncatable=False,
                ),
                _truth_tail("persona.ai_truth"),
            )
            if reanchor:
                fragments = (_reanchor_fragment(), *fragments)
            return fragments, ()
        except Exception:
            fallback = (_truth_fallback(),)
            if reanchor:
                fallback = (_reanchor_fragment(), *fallback)
            return fallback, ("runtime.persona_failed",)

    def _memory_fragment(
        self,
        turn: TurnInput,
        route: RouteDecision,
        now: datetime,
    ) -> tuple[ContextFragment | None, int, tuple[str, ...]]:
        if (
            self._memory is None
            or route.memory_scope is not MemoryScope.DEFAULT
            or route.mode is Mode.HIGH_STAKES
        ):
            return None, 0, ()
        terms = _lexical_terms(turn.text)
        if not terms:
            return None, 0, ()
        try:
            query = RecallQuery(
                profile_id=self._config.profile_id,
                session_id=turn.session_id,
                at=now,
                terms=terms,
                limit=self._config.recall_limit,
            )
            hits = self._memory.recall(query)
            if (
                not isinstance(hits, tuple)
                or len(hits) > self._config.recall_limit
                or any(not isinstance(hit, RecallHit) for hit in hits)
            ):
                raise TypeError("invalid recall result")
            safe_hits = tuple(
                hit
                for hit in hits[: self._config.recall_limit]
                if hit.record.profile_id == self._config.profile_id
                and hit.record.session_id in (None, turn.session_id)
            )
            if not safe_hits:
                return None, 0, ()
            atoms = [
                {
                    "confidence": hit.record.confidence,
                    "key": hit.record.key,
                    "kind": hit.record.kind.value,
                    "value": hit.record.value,
                    "why_recalled": list(hit.why_recalled),
                }
                for hit in safe_hits
            ]
            content = (
                "UNTRUSTED_MEMORY_ATOMS_JSON_START\n"
                + json.dumps(atoms, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                + "\nEND_UNTRUSTED_MEMORY_ATOMS_JSON"
            )
            return (
                ContextFragment(
                    "runtime.memory_atoms",
                    content,
                    "memory",
                    priority=600,
                    truncatable=False,
                ),
                len(safe_hits),
                (),
            )
        except Exception:
            return None, 0, ("runtime.memory_recall_failed",)

    def _creative_fragments(
        self,
        turn: TurnInput,
        route: RouteDecision,
    ) -> tuple[tuple[ContextFragment, ...], tuple[str, ...]]:
        if route.mode is not Mode.CREATIVE:
            return (), ()
        try:
            creative = plan_creative(
                route,
                turn.text,
                pack=self._creative_pack,
                context_limit=16_000,
            )
            trusted_data = {
                "candidate_count": creative.candidate_count,
                "directives": [
                    {
                        "approach": directive.approach,
                        "mechanism": directive.mechanism.value,
                    }
                    for directive in creative.directives
                ],
                "selection_contract": creative.selection_contract,
            }
            fragments = [
                ContextFragment(
                    "runtime.creative_studio",
                    "TRUSTED_CREATIVE_MECHANISM_DIRECTIVES_JSON:\n"
                    + json.dumps(trusted_data, sort_keys=True, separators=(",", ":"))
                    + "\nEND_TRUSTED_CREATIVE_STUDIO_JSON",
                    "creative",
                    priority=700,
                    truncatable=False,
                )
            ]
            if creative.rubric and creative.anti_patterns:
                pack_data = {
                    "anti_patterns": [creative.anti_patterns[0].to_data()],
                    "rubric": [creative.rubric[0].to_data()],
                }
                fragments.append(
                    ContextFragment(
                        "runtime.creative_pack",
                        "UNTRUSTED_CREATIVE_PACK_DATA_JSON_START\n"
                        + json.dumps(
                            pack_data,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\nEND_UNTRUSTED_CREATIVE_PACK_DATA_JSON",
                        "creative",
                        priority=650,
                        truncatable=False,
                    )
                )
            return tuple(fragments), ()
        except Exception:
            return (), ("runtime.creative_failed",)

    @staticmethod
    def _stance_fragments(
        probe: StanceProbe | None,
        mode: Mode,
    ) -> tuple[tuple[ContextFragment, ...], tuple[str, ...]]:
        if probe is None:
            return (), ()
        try:
            if not isinstance(probe, StanceProbe):
                raise TypeError("invalid stance probe")
            decision = decide_stance(replace(probe, mode=mode))
            data = {
                "action": decision.action.value,
                "guidance": decision.guidance,
                "reason_codes": decision.reason_codes,
                "requires_verification": decision.requires_verification,
            }
            fragments = [
                ContextFragment(
                    "runtime.stance",
                    "TRUSTED_STANCE_GUIDANCE_JSON:\n"
                    + json.dumps(data, sort_keys=True, separators=(",", ":")),
                    "runtime",
                    priority=800,
                    truncatable=False,
                )
            ]
            if mode is Mode.HIGH_STAKES:
                compact = {
                    "accept_correction": "STANCE: Accept correction.",
                    "clarify": "STANCE: Clarify.",
                    "hold": "STANCE: Hold.",
                    "verify": "STANCE: Verify.",
                }[decision.action.value]
                fragments.append(
                    ContextFragment(
                        "runtime.high_stakes_stance",
                        compact,
                        "runtime",
                        priority=250,
                        hard=True,
                        truncatable=False,
                    )
                )
            return tuple(fragments), ()
        except Exception:
            return (), ("runtime.stance_failed",)

    def prepare(self, turn: TurnInput, *, stance_probe: StanceProbe | None = None) -> TurnPlan:
        """Prepare one bounded plan while retaining metadata only."""

        if not isinstance(turn, TurnInput):
            raise TypeError("turn must be TurnInput")
        turn_id = _bounded_identifier(turn.turn_id, "turn_id")
        session_id = _bounded_identifier(turn.session_id, "session_id")
        if not isinstance(turn.text, str):
            raise TypeError("turn text must be a string")
        if len(turn.text) > MAX_TURN_CHARS:
            raise ValueError("turn text exceeds the runtime input limit")
        if not isinstance(turn.memory_scope, MemoryScope):
            raise TypeError("turn memory_scope must be MemoryScope")
        with self._lock:
            if turn_id in self._turn_owners:
                raise ValueError("turn_id is already active or completed")
            if len(self._pending) >= self._config.active_turn_limit:
                raise RuntimeError("runtime active turn limit reached")
            state = self._session(session_id)
            canonical_turn = replace(turn, turn_id=turn_id, session_id=session_id)
            route, route_errors = self._route(canonical_turn, state)
            if route.memory_scope is MemoryScope.SESSION_NO_SAVE:
                state.no_save = True
            now = self._now()
            errors: list[str] = list(route_errors)

            route_policy = {
                "candidate_count": route.candidate_count,
                "mode": route.mode.value,
                "requires_tools": route.requires_tools,
                "response_budget": route.response_budget,
                "social_move": route.social_move.value,
                "strict_truth": route.strict_truth,
            }
            fragments: list[ContextFragment] = [
                ContextFragment(
                    "runtime.route_policy",
                    "TRUSTED_ROUTE_POLICY_JSON:\n"
                    + json.dumps(route_policy, sort_keys=True, separators=(",", ":")),
                    "runtime",
                    priority=1_000,
                    truncatable=False,
                )
            ]
            if route.mode is Mode.HIGH_STAKES:
                fragments.append(_high_stakes_safety_fragment())
            try:
                discourse = state.discourse.recommend(
                    route.mode,
                    social_move=route.social_move,
                    response_budget=route.response_budget,
                )
                fragments.append(
                    ContextFragment(
                        "runtime.discourse",
                        "TRUSTED_DISCOURSE_TACTICS_JSON:\n"
                        + json.dumps([tactic.value for tactic in discourse.tactics]),
                        "runtime",
                        priority=900,
                        truncatable=False,
                    )
                )
            except Exception:
                errors.append("runtime.discourse_failed")

            if route.memory_scope is not MemoryScope.DEFAULT:
                target = (
                    "this session"
                    if route.memory_scope is MemoryScope.SESSION_NO_SAVE
                    else "this turn"
                )
                fragments.append(
                    ContextFragment(
                        "runtime.no_persistence",
                        "MANDATORY_NO_PERSISTENCE_POLICY:\n"
                        f"Do not save, write, or persist information from {target}.",
                        "runtime",
                        priority=100,
                        hard=True,
                        tail=True,
                        truncatable=False,
                    )
                )

            memory_fragment, memory_count, memory_errors = self._memory_fragment(
                canonical_turn,
                route,
                now,
            )
            if memory_fragment is not None:
                fragments.append(memory_fragment)
            errors.extend(memory_errors)
            creative_fragments, creative_errors = self._creative_fragments(canonical_turn, route)
            fragments.extend(creative_fragments)
            errors.extend(creative_errors)
            stance_fragments, stance_errors = self._stance_fragments(stance_probe, route.mode)
            fragments.extend(stance_fragments)
            errors.extend(stance_errors)

            persona_fragments, persona_errors = self._persona_fragments(
                reanchor=state.pending_reanchor
            )
            fragments.extend(persona_fragments)
            errors.extend(persona_errors)

            deep_modes = {Mode.TASK, Mode.RESEARCH, Mode.CREATIVE, Mode.REFLECTIVE}
            context_limit = (
                self._config.deep_context_chars
                if route.mode in deep_modes
                else self._config.normal_context_chars
            )
            plan = TurnPlan(
                turn_id=turn_id,
                session_id=session_id,
                route=route,
                fragments=tuple(fragments),
                context_limit=context_limit,
                memory_scope=route.memory_scope,
            )
            selected = plan.selected_fragments()
            rendered = plan.render_context()
            if any(fragment.fragment_id == "runtime.persona_reanchor" for fragment in selected):
                state.pending_reanchor = False
            fingerprint = (
                "hmac-sha256:"
                + hmac.new(
                    self._fingerprint_key,
                    "\0".join((self._config.profile_id, session_id, turn_id, turn.text)).encode(
                        "utf-8"
                    ),
                    hashlib.sha256,
                ).hexdigest()
            )
            rule_ids = ["runtime.route_policy", "runtime.ai_truth"]
            if route.memory_scope is not MemoryScope.DEFAULT:
                rule_ids.append("runtime.no_persistence")
            if any(fragment.fragment_id == "runtime.persona_reanchor" for fragment in selected):
                rule_ids.append("runtime.drift_reanchor")
            self._pending[turn_id] = _PendingTurn(
                turn_id=turn_id,
                session_id=session_id,
                mode=route.mode,
                social_move=route.social_move,
                memory_scope=route.memory_scope,
                fragment_ids=tuple(fragment.fragment_id for fragment in selected),
                context_chars=len(rendered),
                rule_ids=tuple(rule_ids),
                error_codes=_unique_codes(errors),
                fingerprint=fingerprint,
                memory_read_count=memory_count,
                explicit_save=(
                    route.memory_scope is MemoryScope.DEFAULT
                    and "explicit_save" in route.constraints
                ),
            )
            self._turn_owners[turn_id] = session_id
            return plan

    def _write_memories(
        self,
        pending: _PendingTurn,
        state: _SessionState,
        outcome: TurnOutcome,
        memory_records: object,
        *,
        blocked: bool,
    ) -> tuple[int, tuple[str, ...]]:
        allowed = (
            outcome.success is True
            and not blocked
            and self._memory is not None
            and pending.explicit_save
            and pending.memory_scope is MemoryScope.DEFAULT
            and not state.no_save
            and not pending.error_codes
        )
        if not allowed:
            return 0, ()
        if (
            not isinstance(memory_records, tuple)
            or len(memory_records) > 50
            or any(not isinstance(record, MemoryRecord) for record in memory_records)
            or any(
                record.profile_id != self._config.profile_id
                or record.session_id != pending.session_id
                for record in memory_records
            )
        ):
            return 0, ("runtime.memory_write_rejected",)
        count = 0
        errors: list[str] = []
        for record in memory_records:
            try:
                if self._memory.remember(record, no_save=False):
                    count += 1
            except Exception:
                errors.append("runtime.memory_write_failed")
        return count, _unique_codes(errors)

    def observe(
        self,
        outcome: TurnOutcome,
        *,
        memory_records: tuple[MemoryRecord, ...] = (),
        behavior_probe: BehaviorProbe | None = None,
    ) -> BehaviorReceipt:
        """Consume trusted host metadata and return an idempotent privacy-safe receipt."""

        if not isinstance(outcome, TurnOutcome):
            raise TypeError("outcome must be TurnOutcome")
        turn_id = _bounded_identifier(outcome.turn_id, "turn_id")
        session_id = _bounded_identifier(outcome.session_id, "session_id")
        with self._lock:
            completed = self._completed.get(turn_id)
            if completed is not None:
                if completed.session_id != session_id:
                    raise ValueError("turn_id belongs to another session")
                return completed
            pending = self._pending.get(turn_id)
            if pending is None:
                raise ValueError("turn outcome does not match a prepared turn")
            if pending.session_id != session_id:
                raise ValueError("turn outcome belongs to another session")
            state = self._sessions[session_id]

            tactic_values = frozenset(tactic.value for tactic in DiscourseTactic)
            safe_tactics, tactics_filtered = _sanitize_ids(
                outcome.tactic_ids,
                tactic_values,
                limit=4,
            )
            safe_tools, tools_filtered = _sanitize_ids(
                outcome.tool_names,
                _ALLOWED_TOOLS,
                limit=8,
            )
            safe_host_errors, errors_filtered = _sanitize_ids(
                outcome.error_codes,
                _ALLOWED_HOST_ERRORS,
                limit=8,
            )

            rule_ids = list(pending.rule_ids)
            observe_component_errors: list[str] = []
            if behavior_probe is not None:
                try:
                    if not isinstance(behavior_probe, BehaviorProbe):
                        raise TypeError("invalid behavior probe")
                    drift = state.drift.evaluate(behavior_probe)
                    rule_ids.extend(drift.reason_codes)
                    if drift.reanchor_requested:
                        state.pending_reanchor = True
                except Exception:
                    observe_component_errors.append("runtime.drift_failed")

            observed_tactics = tuple(DiscourseTactic(value) for value in safe_tactics)
            if observed_tactics:
                try:
                    state.discourse.observe(observed_tactics)
                except Exception:
                    observe_component_errors.append("runtime.discourse_observe_failed")

            memory_count, memory_errors = self._write_memories(
                pending,
                state,
                outcome,
                memory_records,
                blocked=bool(observe_component_errors or safe_host_errors or errors_filtered),
            )
            runtime_errors: list[str] = [
                *pending.error_codes,
                *safe_host_errors,
                *observe_component_errors,
                *memory_errors,
            ]
            if tactics_filtered or tools_filtered or errors_filtered:
                runtime_errors.append("runtime.outcome_metadata_filtered")

            receipt = BehaviorReceipt(
                turn_id=turn_id,
                session_id=session_id,
                mode=pending.mode,
                social_move=pending.social_move,
                memory_scope=pending.memory_scope,
                context_chars=pending.context_chars,
                fragment_ids=pending.fragment_ids,
                rule_ids=_unique_codes(rule_ids),
                tactic_ids=safe_tactics,
                memory_read_count=pending.memory_read_count,
                memory_write_count=memory_count,
                tool_names=safe_tools,
                error_codes=_unique_codes(runtime_errors),
                turn_fingerprint=pending.fingerprint,
            )
            del self._pending[turn_id]
            if len(self._completed) >= self._config.active_turn_limit:
                oldest_turn_id, _ = self._completed.popitem(last=False)
                self._turn_owners.pop(oldest_turn_id, None)
            self._completed[turn_id] = receipt
            return receipt

    def finalize(self, session: SessionRef) -> None:
        """Forget all ephemeral runtime metadata for one session without durable writes."""

        if not isinstance(session, SessionRef):
            raise TypeError("session must be SessionRef")
        session_id = _bounded_identifier(session.session_id, "session_id")
        with self._lock:
            self._sessions.pop(session_id, None)
            for mapping in (self._pending, self._completed):
                for turn_id in tuple(mapping):
                    if mapping[turn_id].session_id == session_id:
                        del mapping[turn_id]
                        self._turn_owners.pop(turn_id, None)

    def snapshot(self) -> RuntimeSnapshot:
        """Return bounded aggregate metadata with no identifiers or fingerprints."""

        with self._lock:
            return RuntimeSnapshot(
                session_count=len(self._sessions),
                pending_turn_count=len(self._pending),
                completed_receipt_count=len(self._completed),
                session_no_save_count=sum(state.no_save for state in self._sessions.values()),
            )


__all__ = ["HumanlikeRuntime", "RuntimeConfig", "RuntimeSnapshot"]
