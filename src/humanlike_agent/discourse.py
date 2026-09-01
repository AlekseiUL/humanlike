"""Deterministic, metadata-only discourse-pattern controls."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from .models import Mode, SocialMove

_DISCOURSE_REASON_CODES = frozenset({"discourse.mode_default", "discourse.repetition_rotated"})


class DiscourseTactic(StrEnum):
    """Inspectable response-shape tactics, never generated prose."""

    CONNECT = "connect"
    VALIDATE = "validate"
    PARAPHRASE = "paraphrase"
    LISTEN = "listen"
    DIRECT_ANSWER = "direct_answer"
    CLARIFY = "clarify"
    SPECIFIC_ACKNOWLEDGE = "specific_acknowledge"
    CORRECT = "correct"
    CONCRETE_STEP = "concrete_step"
    BRIEF_BANTER = "brief_banter"
    JOKE = "joke"
    CHALLENGE = "challenge"
    SAFETY_FRAME = "safety_frame"


_HIGH_STAKES_FORBIDDEN = frozenset(
    {DiscourseTactic.JOKE, DiscourseTactic.BRIEF_BANTER, DiscourseTactic.CHALLENGE}
)


@dataclass(frozen=True, slots=True)
class DiscourseDecision:
    """Bounded metadata describing a recommended response shape."""

    mode: Mode
    tactics: tuple[DiscourseTactic, ...]
    response_budget: int
    rotation_applied: bool = False
    reason_codes: tuple[str, ...] = ("discourse.mode_default",)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, Mode):
            raise TypeError("mode must be Mode")
        if not isinstance(self.tactics, tuple) or not 1 <= len(self.tactics) <= 4:
            raise ValueError("tactics must be a tuple of one to four items")
        if any(not isinstance(tactic, DiscourseTactic) for tactic in self.tactics):
            raise TypeError("tactics must contain DiscourseTactic values")
        if isinstance(self.response_budget, bool) or not isinstance(self.response_budget, int):
            raise TypeError("response_budget must be an integer")
        if not 1 <= self.response_budget <= 8_000:
            raise ValueError("response_budget is outside the supported range")
        if type(self.rotation_applied) is not bool:
            raise TypeError("rotation_applied must be a boolean")
        if not isinstance(self.reason_codes, tuple) or any(
            not isinstance(code, str) or not code for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be a tuple of non-empty strings")
        if (
            len(set(self.reason_codes)) != len(self.reason_codes)
            or not set(self.reason_codes) <= _DISCOURSE_REASON_CODES
        ):
            raise ValueError("reason_codes must be code-owned discourse metadata")
        if self.mode is Mode.HIGH_STAKES and _HIGH_STAKES_FORBIDDEN & set(self.tactics):
            raise ValueError("high-stakes tactics contain a forbidden social move")
        if self.mode is Mode.HIGH_STAKES and self.tactics[0] is not DiscourseTactic.SAFETY_FRAME:
            raise ValueError("high-stakes tactics must start with a safety frame")
        if self.mode is Mode.REPAIR and self.tactics[:2] != (
            DiscourseTactic.SPECIFIC_ACKNOWLEDGE,
            DiscourseTactic.CORRECT,
        ):
            raise ValueError("repair tactics must start with specific acknowledge and correct")
        expected_reason = (
            "discourse.repetition_rotated" if self.rotation_applied else "discourse.mode_default"
        )
        if self.reason_codes != (expected_reason,):
            raise ValueError("rotation flag and reason code do not match")
        if self.rotation_applied and (
            self.mode is not Mode.SUPPORT or self.tactics != (DiscourseTactic.LISTEN,)
        ):
            raise ValueError("rotation requires the code-owned support alternative")
        if not self.rotation_applied:
            if self.mode is Mode.SUPPORT:
                valid_shape = self.tactics == (
                    DiscourseTactic.VALIDATE,
                    DiscourseTactic.LISTEN,
                )
            elif self.mode is Mode.SOCIAL:
                social_shapes = {(DiscourseTactic.DIRECT_ANSWER,)}
                social_shapes.add(
                    (DiscourseTactic.BRIEF_BANTER,)
                    if self.response_budget < 180
                    else (DiscourseTactic.CONNECT, DiscourseTactic.BRIEF_BANTER)
                )
                valid_shape = self.tactics in social_shapes
            elif self.mode in {Mode.REPAIR, Mode.HIGH_STAKES}:
                valid_shape = True
            else:
                valid_shape = self.tactics == (DiscourseTactic.DIRECT_ANSWER,)
            if not valid_shape:
                raise ValueError("tactic shape is incompatible with mode or response budget")


@dataclass(frozen=True, slots=True)
class DiscourseSnapshot:
    """Bounded tactic history and aggregate counts only."""

    history: tuple[tuple[DiscourseTactic, ...], ...]
    counts: tuple[tuple[DiscourseTactic, int], ...]
    total_observations: int
    history_limit: int
    repetition_threshold: int

    def __post_init__(self) -> None:
        if isinstance(self.history_limit, bool) or not isinstance(self.history_limit, int):
            raise TypeError("history_limit must be an integer")
        if not 1 <= self.history_limit <= 32:
            raise ValueError("history_limit must be between 1 and 32")
        if isinstance(self.repetition_threshold, bool) or not isinstance(
            self.repetition_threshold, int
        ):
            raise TypeError("repetition_threshold must be an integer")
        if not 1 <= self.repetition_threshold <= self.history_limit:
            raise ValueError("repetition_threshold is outside history_limit")
        if not isinstance(self.history, tuple) or len(self.history) > self.history_limit:
            raise ValueError("history exceeds history_limit")
        for chain in self.history:
            if not isinstance(chain, tuple) or not 1 <= len(chain) <= 4:
                raise ValueError("history chains must contain one to four tactics")
            if any(not isinstance(tactic, DiscourseTactic) for tactic in chain):
                raise TypeError("history chains must contain DiscourseTactic values")
        if not isinstance(self.counts, tuple):
            raise TypeError("counts must be a tuple")
        for item in self.counts:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], DiscourseTactic)
                or isinstance(item[1], bool)
                or not isinstance(item[1], int)
                or item[1] < 1
            ):
                raise TypeError("counts must contain tactic and positive integer pairs")
        expected = Counter(tactic for chain in self.history for tactic in chain)
        expected_counts = tuple(
            (tactic, expected[tactic]) for tactic in DiscourseTactic if expected[tactic]
        )
        if self.counts != expected_counts:
            raise ValueError("counts do not match bounded history")
        if (
            isinstance(self.total_observations, bool)
            or not isinstance(self.total_observations, int)
            or self.total_observations < len(self.history)
        ):
            raise ValueError("total_observations must be non-negative")


def _is_prefix_related(
    left: tuple[DiscourseTactic, ...],
    right: tuple[DiscourseTactic, ...],
) -> bool:
    shared = min(len(left), len(right))
    return left[:shared] == right[:shared]


class DiscourseGuard:
    """Track bounded tactic metadata and rotate repetitive response openings."""

    def __init__(self, history_limit: int = 16, repetition_threshold: int = 3) -> None:
        if isinstance(history_limit, bool) or not isinstance(history_limit, int):
            raise TypeError("history_limit must be an integer")
        if not 1 <= history_limit <= 32:
            raise ValueError("history_limit must be between 1 and 32")
        if isinstance(repetition_threshold, bool) or not isinstance(repetition_threshold, int):
            raise TypeError("repetition_threshold must be an integer")
        if not 2 <= repetition_threshold <= history_limit:
            raise ValueError("repetition_threshold must be between 2 and history_limit")
        self._history_limit = history_limit
        self._repetition_threshold = repetition_threshold
        self._history: deque[tuple[DiscourseTactic, ...]] = deque(maxlen=history_limit)
        self._total_observations = 0
        self._lock = RLock()

    def observe(self, tactics: tuple[DiscourseTactic, ...]) -> None:
        """Record only a bounded tactic chain, never response text."""

        if not isinstance(tactics, tuple) or not 1 <= len(tactics) <= 4:
            raise ValueError("tactics must be a tuple of one to four items")
        if any(not isinstance(tactic, DiscourseTactic) for tactic in tactics):
            raise TypeError("tactics must contain DiscourseTactic values")
        with self._lock:
            self._history.append(tactics)
            self._total_observations += 1

    def snapshot(self) -> DiscourseSnapshot:
        """Return an immutable metadata-only view of bounded history."""

        with self._lock:
            history = tuple(self._history)
            counts = Counter(tactic for chain in history for tactic in chain)
            total = self._total_observations
        return DiscourseSnapshot(
            history=history,
            counts=tuple((tactic, counts[tactic]) for tactic in DiscourseTactic if counts[tactic]),
            total_observations=total,
            history_limit=self._history_limit,
            repetition_threshold=self._repetition_threshold,
        )

    def reset(self) -> None:
        """Clear bounded tactic metadata."""

        with self._lock:
            self._history.clear()
            self._total_observations = 0

    def recommend(
        self,
        mode: Mode,
        *,
        social_move: SocialMove = SocialMove.ANSWER,
        response_budget: int = 400,
    ) -> DiscourseDecision:
        """Return a deterministic tactic recommendation from mode-level metadata."""

        if not isinstance(mode, Mode):
            raise TypeError("mode must be Mode")
        if not isinstance(social_move, SocialMove):
            raise TypeError("social_move must be SocialMove")
        if mode is Mode.SUPPORT:
            base = (DiscourseTactic.VALIDATE, DiscourseTactic.LISTEN)
        elif mode is Mode.REPAIR:
            base = (
                DiscourseTactic.SPECIFIC_ACKNOWLEDGE,
                DiscourseTactic.CORRECT,
            )
        elif mode is Mode.HIGH_STAKES:
            base = (
                DiscourseTactic.SAFETY_FRAME,
                DiscourseTactic.DIRECT_ANSWER,
            )
        elif mode is Mode.SOCIAL and social_move is SocialMove.CONNECT:
            base = (
                (DiscourseTactic.BRIEF_BANTER,)
                if response_budget < 180
                else (DiscourseTactic.CONNECT, DiscourseTactic.BRIEF_BANTER)
            )
        else:
            base = (DiscourseTactic.DIRECT_ANSWER,)
        with self._lock:
            recent = tuple(self._history)[-self._repetition_threshold :]
            repeated = len(recent) == self._repetition_threshold and all(
                _is_prefix_related(chain, base) for chain in recent
            )
        if mode is Mode.SUPPORT and repeated:
            return DiscourseDecision(
                mode=mode,
                tactics=(DiscourseTactic.LISTEN,),
                response_budget=response_budget,
                rotation_applied=True,
                reason_codes=("discourse.repetition_rotated",),
            )
        return DiscourseDecision(
            mode=mode,
            tactics=base,
            response_budget=response_budget,
            reason_codes=("discourse.mode_default",),
        )


__all__ = [
    "DiscourseDecision",
    "DiscourseGuard",
    "DiscourseSnapshot",
    "DiscourseTactic",
]
