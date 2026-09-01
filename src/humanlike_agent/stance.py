"""Deterministic evidence-aware stance controls."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from .models import Mode


class StanceAction(StrEnum):
    """Externally inspectable action selected for a disputed claim."""

    ACCEPT_CORRECTION = "accept_correction"
    VERIFY = "verify"
    HOLD = "hold"
    CLARIFY = "clarify"


def _metric(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return result


@dataclass(frozen=True, slots=True)
class StanceProbe:
    """Trusted claim/evidence metadata without user or assistant text."""

    claim_confidence: float
    independent_evidence_strength: float
    correction_quality: float
    user_pressure: float
    stakes: float
    mode: Mode
    support_intent: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "claim_confidence",
            "independent_evidence_strength",
            "correction_quality",
            "user_pressure",
            "stakes",
        ):
            object.__setattr__(self, field_name, _metric(getattr(self, field_name), field_name))
        if not isinstance(self.mode, Mode):
            raise TypeError("mode must be Mode")
        if type(self.support_intent) is not bool:
            raise TypeError("support_intent must be a boolean")


_GUIDANCE = {
    StanceAction.ACCEPT_CORRECTION: (
        "Acknowledge the supported correction briefly, revise the claim, and give the corrected "
        "result."
    ),
    StanceAction.VERIFY: (
        "State the uncertainty, verify against independent evidence, and revise only if it "
        "supports the correction."
    ),
    StanceAction.HOLD: (
        "Keep the best-supported position and name the evidence that would justify changing it."
    ),
    StanceAction.CLARIFY: ("Ask one focused question that would distinguish the competing claims."),
}
_STANCE_REASON_CODES = frozenset(
    {
        "stance.strong_correction",
        "stance.unsupported_pressure",
        "stance.uncertain_evidence",
        "stance.insufficient_information",
        "stance.best_supported_position",
        "stance.high_stakes_threshold",
        "stance.support_without_agreement",
    }
)
_PRIMARY_REASONS = {
    StanceAction.ACCEPT_CORRECTION: frozenset({"stance.strong_correction"}),
    StanceAction.VERIFY: frozenset({"stance.uncertain_evidence"}),
    StanceAction.HOLD: frozenset({"stance.unsupported_pressure", "stance.best_supported_position"}),
    StanceAction.CLARIFY: frozenset({"stance.insufficient_information"}),
}


@dataclass(frozen=True, slots=True)
class StanceDecision:
    """Concise code-owned guidance without hidden reasoning."""

    action: StanceAction
    evidence_threshold: float
    reason_codes: tuple[str, ...]
    guidance: str = field(init=False)
    acknowledge_correction: bool = field(init=False)
    requires_verification: bool = field(init=False)
    support_without_agreement: bool = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.action, StanceAction):
            raise TypeError("action must be StanceAction")
        object.__setattr__(
            self,
            "evidence_threshold",
            _metric(self.evidence_threshold, "evidence_threshold"),
        )
        if self.evidence_threshold not in {0.70, 0.85}:
            raise ValueError("evidence_threshold must be a code-owned threshold")
        if not isinstance(self.reason_codes, tuple) or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty tuple")
        if (
            len(set(self.reason_codes)) != len(self.reason_codes)
            or not set(self.reason_codes) <= _STANCE_REASON_CODES
        ):
            raise ValueError("reason_codes must be code-owned stance metadata")
        if self.reason_codes[0] not in _PRIMARY_REASONS[self.action]:
            raise ValueError("action and primary reason code do not match")
        high_stakes_reason = "stance.high_stakes_threshold" in self.reason_codes
        if high_stakes_reason != (self.evidence_threshold == 0.85):
            raise ValueError("high-stakes reason must match the evidence threshold")
        if "stance.support_without_agreement" in self.reason_codes and not (
            self.action is StanceAction.HOLD
            and self.reason_codes[0] == "stance.unsupported_pressure"
        ):
            raise ValueError("support-without-agreement reason requires an evidence-backed hold")
        expected_reasons = [self.reason_codes[0]]
        if self.evidence_threshold == 0.85:
            expected_reasons.append("stance.high_stakes_threshold")
        if "stance.support_without_agreement" in self.reason_codes:
            expected_reasons.append("stance.support_without_agreement")
        if self.reason_codes != tuple(expected_reasons):
            raise ValueError("reason_codes are not a canonical stance combination")
        object.__setattr__(self, "guidance", _GUIDANCE[self.action])
        object.__setattr__(
            self,
            "acknowledge_correction",
            self.action is StanceAction.ACCEPT_CORRECTION,
        )
        object.__setattr__(
            self,
            "requires_verification",
            self.action is StanceAction.VERIFY,
        )
        object.__setattr__(
            self,
            "support_without_agreement",
            "stance.support_without_agreement" in self.reason_codes,
        )


def decide_stance(probe: StanceProbe) -> StanceDecision:
    """Apply fixed evidence precedence to trusted stance metadata."""

    if not isinstance(probe, StanceProbe):
        raise TypeError("probe must be StanceProbe")
    high_stakes = probe.mode is Mode.HIGH_STAKES or probe.stakes >= 0.75
    threshold = 0.85 if high_stakes else 0.70
    if probe.correction_quality >= threshold and probe.independent_evidence_strength >= threshold:
        reasons = ["stance.strong_correction"]
        if high_stakes:
            reasons.append("stance.high_stakes_threshold")
        return StanceDecision(
            action=StanceAction.ACCEPT_CORRECTION,
            evidence_threshold=threshold,
            reason_codes=tuple(reasons),
        )
    if (
        probe.user_pressure >= 0.70
        and probe.independent_evidence_strength >= 0.50
        and probe.correction_quality < probe.independent_evidence_strength
    ):
        reasons = ["stance.unsupported_pressure"]
        if high_stakes:
            reasons.append("stance.high_stakes_threshold")
        if probe.support_intent:
            reasons.append("stance.support_without_agreement")
        return StanceDecision(
            action=StanceAction.HOLD,
            evidence_threshold=threshold,
            reason_codes=tuple(reasons),
        )
    if (
        probe.claim_confidence >= threshold
        and probe.independent_evidence_strength >= threshold
        and probe.correction_quality < 0.40
    ):
        reasons = ["stance.best_supported_position"]
        if high_stakes:
            reasons.append("stance.high_stakes_threshold")
        return StanceDecision(
            action=StanceAction.HOLD,
            evidence_threshold=threshold,
            reason_codes=tuple(reasons),
        )
    if probe.correction_quality >= 0.40 or probe.independent_evidence_strength >= 0.40:
        reasons = ["stance.uncertain_evidence"]
        if high_stakes:
            reasons.append("stance.high_stakes_threshold")
        return StanceDecision(
            action=StanceAction.VERIFY,
            evidence_threshold=threshold,
            reason_codes=tuple(reasons),
        )
    reasons = ["stance.insufficient_information"]
    if high_stakes:
        reasons.append("stance.high_stakes_threshold")
    return StanceDecision(
        action=StanceAction.CLARIFY,
        evidence_threshold=threshold,
        reason_codes=tuple(reasons),
    )


__all__ = ["StanceAction", "StanceDecision", "StanceProbe", "decide_stance"]
