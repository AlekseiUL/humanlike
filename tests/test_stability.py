"""Synthetic end-state regressions for stability boundaries."""

import os
import re

import pytest

from humanlike_agent.adapters.hermes import HermesAdapter
from humanlike_agent.hermes_plugin import build_default_runtime
from humanlike_agent.models import MemoryScope, TurnInput
from humanlike_agent.native import NativeController, Scope
from humanlike_agent.router import route_turn


@pytest.mark.parametrize(
    "text",
    [
        "Спроектируй структуру библиотеки для обработки событий",
        "Напиши функцию сортировки массива",
        "Build a CSV parser with validation",
        "Hello, build a CSV parser",
        "Привет! Спроектируй библиотеку",
        "Buid a CSV parser",
        '"hello"',
    ],
)
def test_unknown_is_not_social(text):
    route = route_turn(TurnInput(text))
    assert route.mode.value == "unknown"
    assert route.social_move.value == "neutral"
    assert route.response_budget is None
    plan = build_default_runtime().prepare(TurnInput(text, "t", "s"))
    context = plan.render_context()
    assert "TRUSTED_ROUTE_POLICY_JSON" not in context
    assert "ADVISORY" in context
    assert "MANDATORY_AI_TRUTH_CONTRACT" in context
    assert len(context) <= plan.context_limit


def test_unknown_privacy_independent():
    runtime = build_default_runtime()
    plan = runtime.prepare(TurnInput("Build a CSV parser. Do not save this session.", "t", "s"))
    assert plan.memory_scope == MemoryScope.SESSION_NO_SAVE
    assert runtime.prepare(TurnInput("Build another parser", "t2", "s")).memory_scope == (
        MemoryScope.SESSION_NO_SAVE
    )


def command(controller, text, session="s"):
    return controller.command(text, session_id=session, session_key=session, platform="cli")


def approve(controller, text):
    challenge = command(controller, text)
    token = re.search(r"/humanlike (confirm [a-f0-9]{32})", challenge)
    assert token, challenge
    return command(controller, token[1])


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")
def test_native_conflict_requires_choice_then_resolves(tmp_path):
    controller = NativeController(lambda: tmp_path / "memory.sqlite")
    assert "[enabled]" in approve(controller, "I agree to local memory")
    assert "[stored]" in approve(controller, "usually keep replies short")
    result = approve(controller, "usually give detailed replies")
    assert "[conflict_choice]" in result
    scope = controller._bindings["s"]
    assert controller._memory(scope).recall("reply_length")[0].record.value == "short"
    assert "[stored]" in approve(controller, "correct that: usually give detailed replies")
    memory = controller._memory(scope)
    assert memory.recall("reply_length")[0].record.value == "detailed"
    assert len(memory.inspect()) == 2
    assert sum(f.record.record_id in memory.inspect_page()[1] for f in memory.inspect()) == 1


def test_prepare_failure_has_safe_status():
    class Broken:
        def prepare(self, *_):
            raise OSError("private text /private/path secret")

    adapter = HermesAdapter(Broken())
    assert adapter.pre_llm_call(session_id="s", turn_id="t", user_message="hello") is None
    assert adapter.status()["reason"] == "prepare_failed"
    assert "private" not in str(adapter.status())


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")
def test_existing_contradiction_group_resolves(tmp_path):
    from datetime import UTC, datetime

    from humanlike_agent.personal import HumanEvent

    controller = NativeController(lambda: tmp_path / "memory.sqlite")
    scope = Scope("synthetic-owner", "synthetic-chat", "s", "cli")
    controller.handle("I agree to local memory", scope, sequence=1)
    for i, value in enumerate(("short", "detailed", "short"), 2):
        event = HumanEvent(
            str(i),
            scope.owner,
            "humanlike-native",
            scope.chat,
            i,
            datetime.now(UTC),
            f"Remember my preference: reply_length = {value}",
        )
        assert controller._memory(scope, event).capture(str(i)).status == "stored"
    assert controller._memory(scope).recall("reply_length") == ()
    assert "[stored]" in controller.handle("correct that: usually give detailed replies", scope)
    memory = controller._memory(scope)
    assert memory.recall("reply_length")[0].record.value == "detailed"
    assert len(memory.inspect()) == 4
