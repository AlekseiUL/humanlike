import json
import tomllib
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

import humanlike_agent
from humanlike_agent.models import (
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


def test_package_version_has_one_setuptools_source() -> None:
    pyproject_path = Path(__file__).parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "humanlike_agent.__version__"
    }
    assert humanlike_agent.__version__ == "0.1.0"


def test_mode_values_are_stable() -> None:
    assert [mode.value for mode in Mode] == [
        "social",
        "support",
        "task",
        "research",
        "creative",
        "repair",
        "high_stakes",
        "meta_truth",
        "reflective",
    ]


def test_social_move_values_are_stable() -> None:
    assert [move.value for move in SocialMove] == [
        "connect",
        "acknowledge",
        "listen",
        "answer",
        "ask",
        "challenge",
        "revise",
        "create",
        "act",
        "refuse",
        "wait",
    ]


def test_memory_scope_values_are_stable() -> None:
    assert [scope.value for scope in MemoryScope] == [
        "default",
        "item_no_save",
        "session_no_save",
    ]


@pytest.mark.parametrize(
    "contract",
    [
        TurnInput(),
        RouteDecision(),
        ContextFragment(),
        TurnPlan(),
        TurnOutcome(),
        BehaviorReceipt(),
        SessionRef(),
    ],
)
def test_runtime_contracts_are_immutable(contract: object) -> None:
    field_name = fields(contract)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(contract, field_name, None)


def test_turn_input_to_dict_is_json_safe() -> None:
    turn = TurnInput(
        text="hello",
        turn_id="t1",
        session_id="s1",
        locale="en",
        elapsed_seconds=2.5,
        memory_scope=MemoryScope.ITEM_NO_SAVE,
    )

    payload = turn.to_dict()

    assert payload["memory_scope"] == "item_no_save"
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.parametrize(
    "non_finite",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_to_dict_rejects_non_finite_float(non_finite: float) -> None:
    turn = TurnInput(elapsed_seconds=non_finite)

    with pytest.raises(ValueError, match="finite"):
        turn.to_dict()


def test_route_decision_to_dict_is_json_safe() -> None:
    decision = RouteDecision(
        mode=Mode.CREATIVE,
        social_move=SocialMove.CREATE,
        response_budget=600,
        candidate_count=4,
        constraints=("six_words",),
        reason_codes=("explicit_creative",),
    )

    payload = decision.to_dict()

    assert payload["mode"] == "creative"
    assert payload["constraints"] == ["six_words"]
    assert json.loads(json.dumps(payload)) == payload


def test_route_decision_policy_defaults_are_backward_compatible() -> None:
    decision = RouteDecision()

    assert decision.confidence == 0.0
    assert decision.memory_scope is MemoryScope.DEFAULT
    assert decision.requires_tools is False
    assert decision.strict_truth is False


def test_turn_plan_safe_default_is_conservative() -> None:
    plan = TurnPlan.safe_default("t1", "s1")

    assert plan.turn_id == "t1"
    assert plan.session_id == "s1"
    assert plan.route.mode is Mode.TASK
    assert plan.route.social_move is SocialMove.ANSWER
    assert plan.memory_scope is MemoryScope.DEFAULT
    assert plan.fragments == ()


def test_turn_plan_to_dict_serializes_nested_contracts() -> None:
    plan = TurnPlan(
        turn_id="t1",
        session_id="s1",
        route=RouteDecision(mode=Mode.SUPPORT, social_move=SocialMove.LISTEN),
        fragments=(ContextFragment(fragment_id="identity", content="Be warm", hard=True),),
    )

    payload = plan.to_dict()

    assert payload["route"]["mode"] == "support"
    assert payload["fragments"][0]["fragment_id"] == "identity"
    assert json.loads(json.dumps(payload)) == payload


def test_render_context_orders_fragments_by_descending_priority() -> None:
    plan = TurnPlan(
        fragments=(
            ContextFragment(content="low", priority=10),
            ContextFragment(content="high", priority=30),
            ContextFragment(content="middle", priority=20),
        ),
        context_limit=100,
    )

    assert plan.render_context() == "high\n\nmiddle\n\nlow"


def test_render_context_never_exceeds_context_limit() -> None:
    plan = TurnPlan(
        fragments=(ContextFragment(content="abcdefghij", priority=10),),
        context_limit=6,
    )

    assert plan.render_context() == "abcdef"


def test_render_context_preserves_hard_fragment_during_truncation() -> None:
    plan = TurnPlan(
        fragments=(
            ContextFragment(content="soft-content-that-will-be-cut", priority=100),
            ContextFragment(content="TRUTH", priority=1, hard=True),
        ),
        context_limit=16,
    )

    rendered = plan.render_context()

    assert len(rendered) <= 16
    assert "TRUTH" in rendered


def test_render_context_keeps_stable_order_when_reserving_equal_priority_hard_fragment() -> None:
    plan = TurnPlan(
        fragments=(
            ContextFragment(content="AAAA", priority=0),
            ContextFragment(content="B", priority=0, hard=True),
        ),
        context_limit=6,
    )

    assert plan.render_context() == "AAA\n\nB"


def test_render_context_rejects_hard_fragments_larger_than_limit() -> None:
    plan = TurnPlan(
        fragments=(ContextFragment(content="IDENTITY_TRUTH", hard=True),),
        context_limit=5,
    )

    with pytest.raises(ValueError, match="hard context fragments"):
        plan.render_context()


def test_turn_outcome_to_dict_is_json_safe() -> None:
    outcome = TurnOutcome(
        turn_id="t1",
        session_id="s1",
        success=True,
        response_chars=42,
        tactic_ids=("answer",),
        tool_names=("search",),
    )

    payload = outcome.to_dict()

    assert payload["tactic_ids"] == ["answer"]
    assert json.loads(json.dumps(payload)) == payload


def test_behavior_receipt_contains_metadata_without_raw_input() -> None:
    receipt = BehaviorReceipt(
        turn_id="t1",
        session_id="s1",
        mode=Mode.REPAIR,
        social_move=SocialMove.REVISE,
        memory_scope=MemoryScope.ITEM_NO_SAVE,
        context_chars=120,
        fragment_ids=("identity", "truth"),
        rule_ids=("repair.explicit",),
    )

    payload = receipt.to_dict()

    assert payload["mode"] == "repair"
    assert not ({"text", "raw_input", "input", "message", "prompt"} & payload.keys())
    assert json.loads(json.dumps(payload)) == payload


def test_session_ref_to_dict_is_json_safe() -> None:
    session = SessionRef(session_id="s1", user_id="u1", locale="ru-RU")

    payload = session.to_dict()

    assert payload == {
        "session_id": "s1",
        "user_id": "u1",
        "locale": "ru-RU",
        "started_at": None,
    }
    assert json.loads(json.dumps(payload)) == payload
