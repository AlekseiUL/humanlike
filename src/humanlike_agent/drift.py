"""Deterministic, metadata-only behavior-drift controls."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock

_ANCHOR_BUDGET = 480
_DRIFT_REASON_CODES = frozenset(
    {
        "drift.consecutive_breach",
        "drift.cooldown",
        "drift.persona_deviation",
        "drift.repetition",
        "drift.stance_violation",
        "drift.threshold_breach",
        "drift.truth_boundary_failure",
        "drift.voice_deviation",
    }
)


def _metric(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return result


class ReanchorDirective(StrEnum):
    """Code-owned re-anchor action; actual persona text is supplied elsewhere."""

    NONE = "none"
    SHORT_PERSONA_SPINE = "short_persona_spine"


@dataclass(frozen=True, slots=True)
class BehaviorProbe:
    """Normalized behavior metadata without message or response content."""

    truth_boundary_pass: bool
    persona_deviation: float
    voice_deviation: float
    repetition_score: float
    stance_violation: bool

    def __post_init__(self) -> None:
        if type(self.truth_boundary_pass) is not bool:
            raise TypeError("truth_boundary_pass must be a boolean")
        if type(self.stance_violation) is not bool:
            raise TypeError("stance_violation must be a boolean")
        for field_name in (
            "persona_deviation",
            "voice_deviation",
            "repetition_score",
        ):
            object.__setattr__(self, field_name, _metric(getattr(self, field_name), field_name))


@dataclass(frozen=True, slots=True)
class DriftDecision:
    """Inspectable score and re-anchor request without hidden reasoning."""

    score: float
    reanchor_requested: bool
    reason_codes: tuple[str, ...]
    consecutive_breaches: int
    cooldown_remaining: int
    threshold: float
    directive: ReanchorDirective = field(init=False)
    anchor_budget: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _metric(self.score, "score"))
        object.__setattr__(self, "threshold", _metric(self.threshold, "threshold"))
        if not 0.01 <= self.threshold <= 0.99:
            raise ValueError("threshold must be between 0.01 and 0.99")
        if type(self.reanchor_requested) is not bool:
            raise TypeError("reanchor_requested must be a boolean")
        if not isinstance(self.reason_codes, tuple) or any(
            not isinstance(code, str) or not code for code in self.reason_codes
        ):
            raise TypeError("reason_codes must be a tuple of non-empty strings")
        if (
            len(set(self.reason_codes)) != len(self.reason_codes)
            or not set(self.reason_codes) <= _DRIFT_REASON_CODES
        ):
            raise ValueError("reason_codes must be code-owned drift metadata")
        for field_name in ("consecutive_breaches", "cooldown_remaining"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.consecutive_breaches > 8:
            raise ValueError("consecutive_breaches is outside the supported range")
        if self.cooldown_remaining > 64:
            raise ValueError("cooldown_remaining is outside the supported range")
        if self.consecutive_breaches and (
            self.reanchor_requested or "drift.cooldown" in self.reason_codes
        ):
            raise ValueError("anchored or cooldown state cannot retain consecutive breaches")
        anchor_reasons = {
            "drift.consecutive_breach",
            "drift.truth_boundary_failure",
        }
        has_anchor_reason = bool(anchor_reasons & set(self.reason_codes))
        if self.reanchor_requested and not has_anchor_reason:
            raise ValueError("re-anchor request requires a matching reason code")
        if not self.reanchor_requested and "drift.consecutive_breach" in self.reason_codes:
            raise ValueError("consecutive breach reason requires a re-anchor request")
        if self.reanchor_requested and "drift.cooldown" in self.reason_codes:
            raise ValueError("cooldown suppresses re-anchor requests")
        if "drift.truth_boundary_failure" in self.reason_codes and self.score != 1.0:
            raise ValueError("truth-boundary failure requires the severe drift score")
        if (
            "drift.truth_boundary_failure" in self.reason_codes
            and "drift.cooldown" not in self.reason_codes
            and not self.reanchor_requested
        ):
            raise ValueError("unsuppressed truth failure requires a re-anchor request")
        threshold_reason = "drift.threshold_breach" in self.reason_codes
        if threshold_reason != (self.score >= self.threshold):
            raise ValueError("threshold reason must match the drift score")
        if self.consecutive_breaches and self.score < self.threshold:
            raise ValueError("consecutive breach count requires a current threshold breach")
        if self.reanchor_requested and self.score < self.threshold:
            raise ValueError("re-anchor score must meet the threshold")
        if (
            self.cooldown_remaining
            and not self.reanchor_requested
            and "drift.cooldown" not in self.reason_codes
        ):
            raise ValueError("suppressed drift requires the cooldown reason")
        directive = (
            ReanchorDirective.SHORT_PERSONA_SPINE
            if self.reanchor_requested
            else ReanchorDirective.NONE
        )
        object.__setattr__(self, "directive", directive)
        object.__setattr__(self, "anchor_budget", _ANCHOR_BUDGET if self.reanchor_requested else 0)


@dataclass(frozen=True, slots=True)
class DriftSnapshot:
    """Bounded scores and counters for inspection or persistence."""

    scores: tuple[float, ...]
    total_probes: int
    consecutive_breaches: int
    cooldown_remaining: int
    history_limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.scores, tuple):
            raise TypeError("scores must be a tuple")
        canonical_scores = tuple(_metric(score, "score") for score in self.scores)
        if canonical_scores != self.scores:
            object.__setattr__(self, "scores", canonical_scores)
        for field_name in (
            "total_probes",
            "consecutive_breaches",
            "cooldown_remaining",
            "history_limit",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if not 1 <= self.history_limit <= 32:
            raise ValueError("history_limit must be between 1 and 32")
        if len(self.scores) > self.history_limit:
            raise ValueError("scores exceed history_limit")
        if self.total_probes < len(self.scores):
            raise ValueError("total_probes cannot be smaller than bounded history")
        if self.consecutive_breaches > min(self.total_probes, len(self.scores)):
            raise ValueError("consecutive breaches exceed observed probe history")
        if self.consecutive_breaches > 8:
            raise ValueError("consecutive breaches are outside the supported range")
        if self.cooldown_remaining > 64:
            raise ValueError("cooldown_remaining is outside the supported range")
        if self.cooldown_remaining and self.consecutive_breaches:
            raise ValueError("cooldown and consecutive breach state cannot coexist")
        if self.total_probes > 0 and not self.scores:
            raise ValueError("nonzero probes require bounded score history")
        if self.total_probes == 0 and (
            self.scores or self.consecutive_breaches or self.cooldown_remaining
        ):
            raise ValueError("zero probes require an empty zero-state snapshot")


def _score_probe(probe: BehaviorProbe) -> tuple[float, tuple[str, ...]]:
    if not probe.truth_boundary_pass:
        return 1.0, ("drift.truth_boundary_failure", "drift.threshold_breach")
    score = min(
        1.0,
        0.35 * probe.persona_deviation
        + 0.20 * probe.voice_deviation
        + 0.20 * probe.repetition_score
        + (0.25 if probe.stance_violation else 0.0),
    )
    reasons: list[str] = []
    if probe.persona_deviation >= 0.50:
        reasons.append("drift.persona_deviation")
    if probe.voice_deviation >= 0.50:
        reasons.append("drift.voice_deviation")
    if probe.repetition_score >= 0.50:
        reasons.append("drift.repetition")
    if probe.stance_violation:
        reasons.append("drift.stance_violation")
    return score, tuple(reasons)


class DriftSentinel:
    """Accumulate bounded behavior scores and request deterministic re-anchors."""

    def __init__(
        self,
        *,
        threshold: float = 0.55,
        consecutive_required: int = 2,
        cooldown_turns: int = 8,
        history_limit: int = 16,
    ) -> None:
        self._threshold = _metric(threshold, "threshold")
        if not 0.01 <= self._threshold <= 0.99:
            raise ValueError("threshold must be between 0.01 and 0.99")
        for field_name, value, lower, upper in (
            ("consecutive_required", consecutive_required, 1, 8),
            ("cooldown_turns", cooldown_turns, 0, 64),
            ("history_limit", history_limit, 1, 32),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if not lower <= value <= upper:
                raise ValueError(f"{field_name} is outside the supported range")
        if consecutive_required > history_limit:
            raise ValueError("history_limit must cover the consecutive evidence window")
        self._consecutive_required = consecutive_required
        self._cooldown_turns = cooldown_turns
        self._history_limit = history_limit
        self._history: deque[float] = deque(maxlen=history_limit)
        self._consecutive_breaches = 0
        self._cooldown_remaining = 0
        self._total_probes = 0
        self._lock = RLock()

    def snapshot(self) -> DriftSnapshot:
        """Return an immutable metadata-only state snapshot."""

        with self._lock:
            return DriftSnapshot(
                scores=tuple(self._history),
                total_probes=self._total_probes,
                consecutive_breaches=self._consecutive_breaches,
                cooldown_remaining=self._cooldown_remaining,
                history_limit=self._history_limit,
            )

    def reset(self) -> None:
        """Clear scores, counters, and cooldown state."""

        with self._lock:
            self._history.clear()
            self._consecutive_breaches = 0
            self._cooldown_remaining = 0
            self._total_probes = 0

    def evaluate(self, probe: BehaviorProbe) -> DriftDecision:
        """Evaluate one trusted metadata probe and advance sentinel state."""

        if not isinstance(probe, BehaviorProbe):
            raise TypeError("probe must be BehaviorProbe")
        score, dimension_reasons = _score_probe(probe)
        with self._lock:
            self._history.append(score)
            self._total_probes += 1
            cooling_down = self._cooldown_remaining > 0
            if cooling_down:
                self._cooldown_remaining -= 1
            breached = score >= self._threshold
            self._consecutive_breaches = (
                self._consecutive_breaches + 1 if breached and not cooling_down else 0
            )
            severe = not probe.truth_boundary_pass
            should_anchor = not cooling_down and (
                severe or self._consecutive_breaches >= self._consecutive_required
            )
            reasons = list(dimension_reasons)
            if breached and "drift.threshold_breach" not in reasons:
                reasons.append("drift.threshold_breach")
            if cooling_down:
                reasons.append("drift.cooldown")
            if should_anchor and not severe:
                reasons.append("drift.consecutive_breach")
            if should_anchor:
                self._consecutive_breaches = 0
                self._cooldown_remaining = self._cooldown_turns
            consecutive = self._consecutive_breaches
            cooldown = self._cooldown_remaining
        return DriftDecision(
            score=score,
            reanchor_requested=should_anchor,
            reason_codes=tuple(reasons),
            consecutive_breaches=consecutive,
            cooldown_remaining=cooldown,
            threshold=self._threshold,
        )


__all__ = [
    "BehaviorProbe",
    "DriftDecision",
    "DriftSentinel",
    "DriftSnapshot",
    "ReanchorDirective",
]
