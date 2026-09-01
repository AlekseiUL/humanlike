import importlib
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace

import pytest

import humanlike_agent
import humanlike_agent.discourse as discourse
import humanlike_agent.drift as drift
import humanlike_agent.stance as stance
from humanlike_agent.models import Mode, SocialMove


@pytest.mark.parametrize(
    "module_name",
    [
        "humanlike_agent.discourse",
        "humanlike_agent.stance",
        "humanlike_agent.drift",
    ],
)
def test_behavior_control_modules_import(module_name: str) -> None:
    assert importlib.import_module(module_name)


def test_behavior_control_contracts_are_publicly_exported() -> None:
    assert humanlike_agent.DiscourseGuard is discourse.DiscourseGuard
    assert humanlike_agent.StanceProbe is stance.StanceProbe
    assert humanlike_agent.DriftSentinel is drift.DriftSentinel


def test_three_repeated_prefix_chains_rotate_support_opening() -> None:
    guard = discourse.DiscourseGuard()
    tactic = discourse.DiscourseTactic
    guard.observe((tactic.VALIDATE,))
    guard.observe((tactic.VALIDATE, tactic.LISTEN))
    guard.observe((tactic.VALIDATE, tactic.LISTEN, tactic.CLARIFY))

    decision = guard.recommend(
        Mode.SUPPORT,
        social_move=SocialMove.LISTEN,
        response_budget=900,
    )

    assert decision.rotation_applied is True
    assert decision.tactics == (tactic.LISTEN,)
    assert "discourse.repetition_rotated" in decision.reason_codes


def test_repair_starts_with_specific_acknowledgement_and_correction() -> None:
    decision = discourse.DiscourseGuard().recommend(
        Mode.REPAIR,
        social_move=SocialMove.REVISE,
        response_budget=850,
    )

    assert decision.tactics[:2] == (
        discourse.DiscourseTactic.SPECIFIC_ACKNOWLEDGE,
        discourse.DiscourseTactic.CORRECT,
    )
    assert discourse.DiscourseTactic.VALIDATE not in decision.tactics


def test_high_stakes_uses_safety_frame_and_never_banter_or_challenge() -> None:
    decision = discourse.DiscourseGuard().recommend(
        Mode.HIGH_STAKES,
        social_move=SocialMove.ANSWER,
        response_budget=1_500,
    )

    assert decision.tactics[:2] == (
        discourse.DiscourseTactic.SAFETY_FRAME,
        discourse.DiscourseTactic.DIRECT_ANSWER,
    )
    assert not {
        discourse.DiscourseTactic.JOKE,
        discourse.DiscourseTactic.BRIEF_BANTER,
        discourse.DiscourseTactic.CHALLENGE,
    } & set(decision.tactics)


def test_social_banter_respects_short_response_budget() -> None:
    guard = discourse.DiscourseGuard()

    short = guard.recommend(
        Mode.SOCIAL,
        social_move=SocialMove.CONNECT,
        response_budget=120,
    )
    roomy = guard.recommend(
        Mode.SOCIAL,
        social_move=SocialMove.CONNECT,
        response_budget=220,
    )

    assert short.tactics == (discourse.DiscourseTactic.BRIEF_BANTER,)
    assert roomy.tactics == (
        discourse.DiscourseTactic.CONNECT,
        discourse.DiscourseTactic.BRIEF_BANTER,
    )


def test_discourse_snapshot_is_bounded_metadata_only() -> None:
    tactic = discourse.DiscourseTactic
    guard = discourse.DiscourseGuard(history_limit=3, repetition_threshold=2)
    for chain in (
        (tactic.VALIDATE,),
        (tactic.LISTEN,),
        (tactic.DIRECT_ANSWER,),
        (tactic.CLARIFY,),
    ):
        guard.observe(chain)

    snapshot = guard.snapshot()

    assert snapshot.history == (
        (tactic.LISTEN,),
        (tactic.DIRECT_ANSWER,),
        (tactic.CLARIFY,),
    )
    assert snapshot.counts == (
        (tactic.LISTEN, 1),
        (tactic.DIRECT_ANSWER, 1),
        (tactic.CLARIFY, 1),
    )
    assert not {"text", "message", "response"} & {field.name for field in fields(snapshot)}
    with pytest.raises(FrozenInstanceError):
        snapshot.total_observations = 0


def test_discourse_reset_clears_all_observed_metadata() -> None:
    guard = discourse.DiscourseGuard()
    guard.observe((discourse.DiscourseTactic.DIRECT_ANSWER,))

    guard.reset()

    snapshot = guard.snapshot()
    assert snapshot.history == ()
    assert snapshot.counts == ()
    assert snapshot.total_observations == 0


def test_varied_discourse_history_does_not_rotate() -> None:
    tactic = discourse.DiscourseTactic
    guard = discourse.DiscourseGuard()
    for chain in (
        (tactic.VALIDATE, tactic.LISTEN),
        (tactic.DIRECT_ANSWER,),
        (tactic.CLARIFY,),
    ):
        guard.observe(chain)

    first = guard.recommend(Mode.SUPPORT, social_move=SocialMove.LISTEN, response_budget=900)
    second = guard.recommend(Mode.SUPPORT, social_move=SocialMove.LISTEN, response_budget=900)

    assert first == second
    assert first.rotation_applied is False


def test_interleaved_prefixes_do_not_count_as_repeated_chain() -> None:
    tactic = discourse.DiscourseTactic
    guard = discourse.DiscourseGuard(history_limit=8, repetition_threshold=3)
    for chain in (
        (tactic.VALIDATE,),
        (tactic.DIRECT_ANSWER,),
        (tactic.VALIDATE, tactic.LISTEN),
        (tactic.CLARIFY,),
        (tactic.VALIDATE,),
    ):
        guard.observe(chain)

    decision = guard.recommend(
        Mode.SUPPORT,
        social_move=SocialMove.LISTEN,
        response_budget=900,
    )

    assert decision.rotation_applied is False


def test_discourse_contracts_reject_raw_or_unsafe_metadata() -> None:
    tactic = discourse.DiscourseTactic
    guard = discourse.DiscourseGuard()

    with pytest.raises(TypeError):
        guard.observe(("raw response",))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        discourse.DiscourseGuard(history_limit=33)
    with pytest.raises(ValueError, match="reason"):
        discourse.DiscourseDecision(
            mode=Mode.TASK,
            tactics=(tactic.DIRECT_ANSWER,),
            response_budget=400,
            reason_codes=("raw user text",),
        )
    with pytest.raises(ValueError, match="high.stakes|high-stakes|forbidden"):
        discourse.DiscourseDecision(
            mode=Mode.HIGH_STAKES,
            tactics=(tactic.JOKE,),
            response_budget=400,
        )
    with pytest.raises(TypeError):
        discourse.DiscourseSnapshot(
            history=(("raw response",),),  # type: ignore[arg-type]
            counts=(),
            total_observations=1,
            history_limit=3,
            repetition_threshold=2,
        )


def test_high_stakes_decision_requires_safety_frame_first() -> None:
    with pytest.raises(ValueError, match="safety|high.stakes|high-stakes"):
        discourse.DiscourseDecision(
            mode=Mode.HIGH_STAKES,
            tactics=(discourse.DiscourseTactic.DIRECT_ANSWER,),
            response_budget=1_500,
            reason_codes=("discourse.mode_default",),
        )


@pytest.mark.parametrize(
    ("rotation_applied", "reason_codes"),
    [
        (True, ("discourse.mode_default",)),
        (False, ("discourse.repetition_rotated",)),
    ],
)
def test_discourse_rotation_flag_and_reason_must_correlate(
    rotation_applied: bool,
    reason_codes: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="rotation|reason"):
        discourse.DiscourseDecision(
            mode=Mode.SUPPORT,
            tactics=(discourse.DiscourseTactic.LISTEN,),
            response_budget=900,
            rotation_applied=rotation_applied,
            reason_codes=reason_codes,
        )


def test_rotated_discourse_decision_requires_the_support_alternative() -> None:
    with pytest.raises(ValueError, match="alternative|rotation|support"):
        discourse.DiscourseDecision(
            mode=Mode.SUPPORT,
            tactics=(
                discourse.DiscourseTactic.VALIDATE,
                discourse.DiscourseTactic.LISTEN,
            ),
            response_budget=900,
            rotation_applied=True,
            reason_codes=("discourse.repetition_rotated",),
        )


@pytest.mark.parametrize(
    ("mode", "tactics", "response_budget"),
    [
        (Mode.SUPPORT, (discourse.DiscourseTactic.DIRECT_ANSWER,), 900),
        (Mode.TASK, (discourse.DiscourseTactic.VALIDATE,), 1_700),
        (
            Mode.SOCIAL,
            (
                discourse.DiscourseTactic.CONNECT,
                discourse.DiscourseTactic.BRIEF_BANTER,
            ),
            120,
        ),
    ],
)
def test_discourse_decision_rejects_mode_incompatible_default_shape(
    mode: Mode,
    tactics: tuple[discourse.DiscourseTactic, ...],
    response_budget: int,
) -> None:
    with pytest.raises(ValueError, match="mode|shape|budget|support"):
        discourse.DiscourseDecision(
            mode=mode,
            tactics=tactics,
            response_budget=response_budget,
            reason_codes=("discourse.mode_default",),
        )


def test_discourse_decision_default_is_a_canonical_mode_decision() -> None:
    decision = discourse.DiscourseDecision(
        mode=Mode.TASK,
        tactics=(discourse.DiscourseTactic.DIRECT_ANSWER,),
        response_budget=1_700,
    )

    assert decision.reason_codes == ("discourse.mode_default",)
    assert decision.rotation_applied is False


def test_strong_independently_supported_correction_is_accepted() -> None:
    probe = stance.StanceProbe(
        claim_confidence=0.9,
        independent_evidence_strength=0.95,
        correction_quality=0.95,
        user_pressure=0.2,
        stakes=0.3,
        mode=Mode.TASK,
    )

    decision = stance.decide_stance(probe)

    assert decision.action is stance.StanceAction.ACCEPT_CORRECTION
    assert decision.acknowledge_correction is True
    assert "stance.strong_correction" in decision.reason_codes
    assert "acknowledge" in decision.guidance.lower()
    assert "revise" in decision.guidance.lower()


def test_pressure_does_not_block_a_strong_supported_correction() -> None:
    decision = stance.decide_stance(
        stance.StanceProbe(
            claim_confidence=0.9,
            independent_evidence_strength=0.95,
            correction_quality=0.9,
            user_pressure=1.0,
            stakes=0.3,
            mode=Mode.TASK,
        )
    )

    assert decision.action is stance.StanceAction.ACCEPT_CORRECTION
    assert decision.reason_codes == ("stance.strong_correction",)


def test_unsupported_pressure_is_held_even_during_support() -> None:
    probe = stance.StanceProbe(
        claim_confidence=0.9,
        independent_evidence_strength=0.65,
        correction_quality=0.1,
        user_pressure=0.95,
        stakes=0.3,
        mode=Mode.SUPPORT,
        support_intent=True,
    )

    decision = stance.decide_stance(probe)

    assert decision.action is stance.StanceAction.HOLD
    assert decision.acknowledge_correction is False
    assert decision.support_without_agreement is True
    assert decision.reason_codes == (
        "stance.unsupported_pressure",
        "stance.support_without_agreement",
    )


def test_pressure_without_evidence_does_not_create_a_position_to_hold() -> None:
    decision = stance.decide_stance(
        stance.StanceProbe(
            claim_confidence=0.0,
            independent_evidence_strength=0.0,
            correction_quality=0.0,
            user_pressure=1.0,
            stakes=1.0,
            mode=Mode.HIGH_STAKES,
        )
    )

    assert decision.action is stance.StanceAction.CLARIFY
    assert decision.acknowledge_correction is False
    assert "stance.unsupported_pressure" not in decision.reason_codes


def test_uncertain_correction_is_verified_not_reflexively_rejected() -> None:
    probe = stance.StanceProbe(
        claim_confidence=0.6,
        independent_evidence_strength=0.55,
        correction_quality=0.65,
        user_pressure=0.3,
        stakes=0.4,
        mode=Mode.RESEARCH,
    )

    decision = stance.decide_stance(probe)

    assert decision.action is stance.StanceAction.VERIFY
    assert decision.requires_verification is True
    assert decision.reason_codes == ("stance.uncertain_evidence",)


def test_high_stakes_raises_the_evidence_threshold() -> None:
    ordinary = stance.StanceProbe(
        claim_confidence=0.8,
        independent_evidence_strength=0.76,
        correction_quality=0.76,
        user_pressure=0.1,
        stakes=0.2,
        mode=Mode.TASK,
    )

    ordinary_decision = stance.decide_stance(ordinary)
    high_stakes_decision = stance.decide_stance(
        replace(ordinary, mode=Mode.HIGH_STAKES, stakes=0.9)
    )

    assert ordinary_decision.action is stance.StanceAction.ACCEPT_CORRECTION
    assert ordinary_decision.evidence_threshold == 0.70
    assert high_stakes_decision.action is stance.StanceAction.VERIFY
    assert high_stakes_decision.evidence_threshold == 0.85
    assert "stance.high_stakes_threshold" in high_stakes_decision.reason_codes


def test_strong_current_evidence_holds_without_reflexive_contrarianism() -> None:
    decision = stance.decide_stance(
        stance.StanceProbe(
            claim_confidence=0.95,
            independent_evidence_strength=0.9,
            correction_quality=0.05,
            user_pressure=0.1,
            stakes=0.2,
            mode=Mode.TASK,
        )
    )

    assert decision.action is stance.StanceAction.HOLD
    assert decision.reason_codes == ("stance.best_supported_position",)


def test_stance_contracts_validate_metrics_and_code_owned_decisions() -> None:
    base = dict(
        claim_confidence=0.5,
        independent_evidence_strength=0.5,
        correction_quality=0.5,
        user_pressure=0.5,
        stakes=0.5,
        mode=Mode.TASK,
    )
    for invalid in (math.nan, math.inf, -0.1, 1.1, True):
        with pytest.raises((TypeError, ValueError)):
            stance.StanceProbe(**(base | {"claim_confidence": invalid}))

    with pytest.raises(ValueError, match="action|reason"):
        stance.StanceDecision(
            action=stance.StanceAction.ACCEPT_CORRECTION,
            evidence_threshold=0.7,
            reason_codes=("stance.unsupported_pressure",),
        )
    with pytest.raises(TypeError):
        stance.StanceDecision(
            action=stance.StanceAction.HOLD,
            evidence_threshold=0.7,
            reason_codes=("stance.best_supported_position",),
            guidance="accept whatever the user says",
        )

    assert not {"text", "message", "response", "claim"} & {
        field.name for field in fields(stance.StanceProbe)
    }


def test_stance_decision_rejects_noncanonical_evidence_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        stance.StanceDecision(
            action=stance.StanceAction.CLARIFY,
            evidence_threshold=0.5,
            reason_codes=("stance.insufficient_information",),
        )


def test_stance_decision_rejects_support_flag_on_accepted_correction() -> None:
    with pytest.raises(ValueError, match="support|reason"):
        stance.StanceDecision(
            action=stance.StanceAction.ACCEPT_CORRECTION,
            evidence_threshold=0.7,
            reason_codes=(
                "stance.strong_correction",
                "stance.support_without_agreement",
            ),
        )


def test_stance_decision_requires_high_stakes_reason_for_stricter_threshold() -> None:
    with pytest.raises(ValueError, match="high.stakes|threshold|reason"):
        stance.StanceDecision(
            action=stance.StanceAction.CLARIFY,
            evidence_threshold=0.85,
            reason_codes=("stance.insufficient_information",),
        )


def test_stance_decision_rejects_noncanonical_reason_combination() -> None:
    with pytest.raises(ValueError, match="canonical|reason"):
        stance.StanceDecision(
            action=stance.StanceAction.HOLD,
            evidence_threshold=0.85,
            reason_codes=(
                "stance.unsupported_pressure",
                "stance.support_without_agreement",
                "stance.high_stakes_threshold",
            ),
        )


def test_stance_decision_is_deterministic_and_frozen() -> None:
    probe = stance.StanceProbe(
        claim_confidence=0.2,
        independent_evidence_strength=0.1,
        correction_quality=0.1,
        user_pressure=0.1,
        stakes=0.1,
        mode=Mode.REFLECTIVE,
    )

    first = stance.decide_stance(probe)
    assert all(stance.decide_stance(probe) == first for _ in range(100))
    assert first.action is stance.StanceAction.CLARIFY
    with pytest.raises(FrozenInstanceError):
        first.action = stance.StanceAction.HOLD


def test_drift_requires_consecutive_threshold_evidence() -> None:
    sentinel = drift.DriftSentinel(threshold=0.55, consecutive_required=2)
    normal = drift.BehaviorProbe(
        truth_boundary_pass=True,
        persona_deviation=0.05,
        voice_deviation=0.05,
        repetition_score=0.05,
        stance_violation=False,
    )
    breach = drift.BehaviorProbe(
        truth_boundary_pass=True,
        persona_deviation=0.9,
        voice_deviation=0.8,
        repetition_score=0.7,
        stance_violation=True,
    )

    for _ in range(20):
        assert sentinel.evaluate(normal).reanchor_requested is False
    first = sentinel.evaluate(breach)
    second = sentinel.evaluate(breach)

    assert first.reanchor_requested is False
    assert first.consecutive_breaches == 1
    assert second.reanchor_requested is True
    assert second.directive is drift.ReanchorDirective.SHORT_PERSONA_SPINE
    assert 0 < second.anchor_budget <= 600
    assert "drift.consecutive_breach" in second.reason_codes


def test_severe_truth_failure_is_immediate_then_cooldown_suppresses_repeats() -> None:
    sentinel = drift.DriftSentinel(
        threshold=0.55,
        consecutive_required=3,
        cooldown_turns=2,
    )
    severe = drift.BehaviorProbe(
        truth_boundary_pass=False,
        persona_deviation=0.0,
        voice_deviation=0.0,
        repetition_score=0.0,
        stance_violation=False,
    )

    immediate = sentinel.evaluate(severe)
    first_cooldown = sentinel.evaluate(severe)
    second_cooldown = sentinel.evaluate(severe)

    assert immediate.reanchor_requested is True
    assert immediate.score == 1.0
    assert "drift.truth_boundary_failure" in immediate.reason_codes
    assert first_cooldown.reanchor_requested is False
    assert first_cooldown.cooldown_remaining == 1
    assert second_cooldown.reanchor_requested is False
    assert second_cooldown.cooldown_remaining == 0
    assert "drift.cooldown" in first_cooldown.reason_codes


def test_drift_recovery_resets_evidence_and_snapshot_is_bounded() -> None:
    sentinel = drift.DriftSentinel(
        threshold=0.55,
        consecutive_required=3,
        history_limit=3,
    )
    breach = drift.BehaviorProbe(True, 1.0, 1.0, 1.0, True)
    normal = drift.BehaviorProbe(True, 0.0, 0.0, 0.0, False)

    assert sentinel.evaluate(breach).consecutive_breaches == 1
    assert sentinel.evaluate(breach).consecutive_breaches == 2
    recovered = sentinel.evaluate(normal)
    after_recovery = sentinel.evaluate(breach)
    snapshot = sentinel.snapshot()

    assert recovered.consecutive_breaches == 0
    assert after_recovery.consecutive_breaches == 1
    assert snapshot.scores == (1.0, 0.0, 1.0)
    assert snapshot.total_probes == 4
    assert snapshot.consecutive_breaches == 1
    assert not {"text", "message", "response"} & {field.name for field in fields(snapshot)}

    sentinel.reset()
    assert sentinel.snapshot().scores == ()
    assert sentinel.snapshot().total_probes == 0


def test_drift_contracts_reject_nonfinite_and_inconsistent_metadata() -> None:
    base = dict(
        truth_boundary_pass=True,
        persona_deviation=0.2,
        voice_deviation=0.2,
        repetition_score=0.2,
        stance_violation=False,
    )
    for invalid in (math.nan, math.inf, -0.1, 1.1, True):
        with pytest.raises((TypeError, ValueError)):
            drift.BehaviorProbe(**(base | {"persona_deviation": invalid}))

    with pytest.raises(ValueError, match="re-anchor|reanchor|reason"):
        drift.DriftDecision(
            score=0.1,
            reanchor_requested=True,
            reason_codes=(),
            consecutive_breaches=0,
            cooldown_remaining=0,
            threshold=0.55,
        )
    with pytest.raises(ValueError, match="reason"):
        drift.DriftDecision(
            score=0.8,
            reanchor_requested=False,
            reason_codes=("raw hidden reasoning",),
            consecutive_breaches=1,
            cooldown_remaining=0,
            threshold=0.55,
        )
    with pytest.raises(ValueError):
        drift.DriftSentinel(history_limit=33)

    assert not {"text", "message", "response", "reasoning"} & {
        field.name for field in fields(drift.BehaviorProbe)
    }


def test_unsuppressed_truth_failure_must_request_reanchor() -> None:
    with pytest.raises(ValueError, match="truth|re-anchor|reanchor"):
        drift.DriftDecision(
            score=1.0,
            reanchor_requested=False,
            reason_codes=(
                "drift.truth_boundary_failure",
                "drift.threshold_breach",
            ),
            consecutive_breaches=0,
            cooldown_remaining=0,
            threshold=0.55,
        )


@pytest.mark.parametrize(
    ("score", "reason_codes"),
    [
        (0.8, ("drift.persona_deviation",)),
        (0.1, ("drift.threshold_breach",)),
    ],
)
def test_drift_threshold_reason_must_match_score(
    score: float,
    reason_codes: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="threshold|reason"):
        drift.DriftDecision(
            score=score,
            reanchor_requested=False,
            reason_codes=reason_codes,
            consecutive_breaches=0,
            cooldown_remaining=0,
            threshold=0.55,
        )


def test_cooldown_reason_cannot_request_another_reanchor() -> None:
    with pytest.raises(ValueError, match="cooldown|re-anchor|reanchor"):
        drift.DriftDecision(
            score=1.0,
            reanchor_requested=True,
            reason_codes=(
                "drift.truth_boundary_failure",
                "drift.threshold_breach",
                "drift.cooldown",
            ),
            consecutive_breaches=0,
            cooldown_remaining=1,
            threshold=0.55,
        )


def test_truth_failure_reason_requires_the_severe_score() -> None:
    with pytest.raises(ValueError, match="truth|score|severe"):
        drift.DriftDecision(
            score=0.8,
            reanchor_requested=True,
            reason_codes=(
                "drift.truth_boundary_failure",
                "drift.threshold_breach",
            ),
            consecutive_breaches=0,
            cooldown_remaining=8,
            threshold=0.55,
        )


@pytest.mark.parametrize(
    ("consecutive_breaches", "cooldown_remaining"),
    [(1, 0), (0, 1)],
)
def test_empty_drift_snapshot_requires_zero_state(
    consecutive_breaches: int,
    cooldown_remaining: int,
) -> None:
    with pytest.raises(ValueError, match="zero|empty|probe|state"):
        drift.DriftSnapshot(
            scores=(),
            total_probes=0,
            consecutive_breaches=consecutive_breaches,
            cooldown_remaining=cooldown_remaining,
            history_limit=8,
        )


def test_drift_snapshot_breach_count_cannot_exceed_observed_probes() -> None:
    with pytest.raises(ValueError, match="breach|probe|count"):
        drift.DriftSnapshot(
            scores=(0.8,),
            total_probes=1,
            consecutive_breaches=2,
            cooldown_remaining=0,
            history_limit=8,
        )


def test_drift_history_must_cover_consecutive_evidence_window() -> None:
    with pytest.raises(ValueError, match="history|consecutive"):
        drift.DriftSentinel(history_limit=1, consecutive_required=2)


def test_drift_snapshot_rejects_out_of_range_cooldown() -> None:
    with pytest.raises(ValueError, match="cooldown|range"):
        drift.DriftSnapshot(
            scores=(0.0,),
            total_probes=1,
            consecutive_breaches=0,
            cooldown_remaining=65,
            history_limit=8,
        )


def test_drift_snapshot_rejects_out_of_range_breach_counter() -> None:
    with pytest.raises(ValueError, match="breach|range"):
        drift.DriftSnapshot(
            scores=(0.8,) * 9,
            total_probes=9,
            consecutive_breaches=9,
            cooldown_remaining=0,
            history_limit=16,
        )


def test_drift_snapshot_rejects_breach_evidence_during_cooldown() -> None:
    with pytest.raises(ValueError, match="cooldown|consecutive|breach"):
        drift.DriftSnapshot(
            scores=(0.8, 0.8),
            total_probes=2,
            consecutive_breaches=1,
            cooldown_remaining=1,
            history_limit=8,
        )


def test_nonempty_drift_session_requires_bounded_score_history() -> None:
    with pytest.raises(ValueError, match="score|history|probe"):
        drift.DriftSnapshot(
            scores=(),
            total_probes=1,
            consecutive_breaches=0,
            cooldown_remaining=0,
            history_limit=8,
        )


@pytest.mark.parametrize(
    ("reanchor_requested", "reason_codes", "cooldown_remaining"),
    [
        (
            False,
            (
                "drift.persona_deviation",
                "drift.threshold_breach",
                "drift.cooldown",
            ),
            1,
        ),
        (
            True,
            (
                "drift.persona_deviation",
                "drift.threshold_breach",
                "drift.consecutive_breach",
            ),
            8,
        ),
    ],
)
def test_anchored_drift_decision_cannot_keep_consecutive_evidence(
    reanchor_requested: bool,
    reason_codes: tuple[str, ...],
    cooldown_remaining: int,
) -> None:
    with pytest.raises(ValueError, match="cooldown|consecutive|breach"):
        drift.DriftDecision(
            score=0.8,
            reanchor_requested=reanchor_requested,
            reason_codes=reason_codes,
            consecutive_breaches=1,
            cooldown_remaining=cooldown_remaining,
            threshold=0.55,
        )


@pytest.mark.parametrize(
    ("consecutive_breaches", "cooldown_remaining"),
    [(9, 0), (0, 65)],
)
def test_drift_decision_rejects_out_of_range_counters(
    consecutive_breaches: int,
    cooldown_remaining: int,
) -> None:
    with pytest.raises(ValueError, match="breach|cooldown|range"):
        drift.DriftDecision(
            score=0.0,
            reanchor_requested=False,
            reason_codes=(),
            consecutive_breaches=consecutive_breaches,
            cooldown_remaining=cooldown_remaining,
            threshold=0.55,
        )


def test_drift_decision_rejects_unusable_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        drift.DriftDecision(
            score=0.1,
            reanchor_requested=False,
            reason_codes=(),
            consecutive_breaches=0,
            cooldown_remaining=0,
            threshold=1.0,
        )


def test_suppressed_drift_decision_requires_cooldown_reason() -> None:
    with pytest.raises(ValueError, match="cooldown|reason"):
        drift.DriftDecision(
            score=0.0,
            reanchor_requested=False,
            reason_codes=(),
            consecutive_breaches=0,
            cooldown_remaining=1,
            threshold=0.55,
        )


def test_consecutive_breach_counter_requires_a_current_breach() -> None:
    with pytest.raises(ValueError, match="consecutive|breach|score"):
        drift.DriftDecision(
            score=0.1,
            reanchor_requested=False,
            reason_codes=(),
            consecutive_breaches=1,
            cooldown_remaining=0,
            threshold=0.55,
        )


def test_drift_sequence_is_deterministic_and_state_is_thread_safe() -> None:
    sequence = (
        drift.BehaviorProbe(True, 0.1, 0.1, 0.1, False),
        drift.BehaviorProbe(True, 0.9, 0.8, 0.7, True),
        drift.BehaviorProbe(True, 0.9, 0.8, 0.7, True),
        drift.BehaviorProbe(True, 0.0, 0.0, 0.0, False),
    )
    left = drift.DriftSentinel()
    right = drift.DriftSentinel()

    assert [left.evaluate(probe) for probe in sequence] == [
        right.evaluate(probe) for probe in sequence
    ]

    concurrent = drift.DriftSentinel(history_limit=8)
    normal = drift.BehaviorProbe(True, 0.0, 0.0, 0.0, False)
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = tuple(pool.map(concurrent.evaluate, (normal,) * 100))
    snapshot = concurrent.snapshot()

    assert all(not decision.reanchor_requested for decision in decisions)
    assert snapshot.total_probes == 100
    assert len(snapshot.scores) == 8
