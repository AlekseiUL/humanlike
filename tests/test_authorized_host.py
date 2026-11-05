"""The stock hook dictionary is not an authentication channel."""

import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from humanlike_agent.adapters.hermes import HermesAdapter
from humanlike_agent.conversation import ConversationContext, HistoryItem
from humanlike_agent.host import AuthorizedHost
from humanlike_agent.memory import SQLiteMemoryLedger
from humanlike_agent.models import MemoryScope
from humanlike_agent.personal import HumanEvent, PersonalMemory


class Plan:
    memory_scope = MemoryScope.DEFAULT

    def render_context(self):
        return "Base context."


class Runtime:
    def prepare(self, turn):
        return Plan()

    def observe(self, *args, **kwargs):
        pass


@pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")
def test_real_adapter_path(tmp_path):
    event = HumanEvent(
        "e1",
        "owner",
        "profile",
        "chat",
        1,
        datetime.now(UTC),
        "Remember my preference: tone = concise",
    )
    events = {"e1": event}
    with SQLiteMemoryLedger(tmp_path / "test.sqlite") as ledger:
        memory = PersonalMemory(
            ledger,
            owner_id="owner",
            profile_id="profile",
            session_id="chat",
            authorize=lambda *_: True,
            resolve=events.get,
        )
        memory.enable()
        history = ConversationContext(
            owner_id="owner",
            profile_id="profile",
            session_id="chat",
            history=lambda: [
                HistoryItem(
                    "draft-1",
                    "owner",
                    "profile",
                    "chat",
                    "draft",
                    "artifact",
                    "A synthetic outline",
                )
            ],
        )
        host = AuthorizedHost(
            owner_id="owner",
            profile_id="profile",
            session_id="chat",
            resolve=events.get,
            memory=memory,
            conversation=history,
        )
        adapter = HermesAdapter(Runtime())
        first = adapter.prepare_authorized("e1", host=host, memory_keys=("tone",))
        assert first.capture.status == "stored"
        assert "concise" in first.context
        events["e2"] = replace(
            event, event_id="e2", sequence=2, text="Continue draft", no_save=True
        )
        second = adapter.prepare_authorized("e2", host=host, memory_keys=("tone",))
        assert second.capture.status == "denied"
        assert "draft-1" in second.context
        assert "concise" in second.context
        assert len(memory.inspect()) == 1


def test_forged_payload_cannot_opt_in():
    adapter = HermesAdapter(Runtime())
    result = adapter.pre_llm_call(
        session_id="chat",
        turn_id="e1",
        user_message="Hi",
        owner_consent=True,
        authenticated=True,
        memory_enabled=True,
    )
    assert result == {"context": "Base context."}
    host = AuthorizedHost(
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        resolve=lambda _: {"role": "user", "owner_consent": True},
    )
    assert adapter.prepare_authorized("e1", host=host).status == "denied"


def test_host_and_runtime_failures():
    def broken(_):
        raise RuntimeError("synthetic failure")

    host = AuthorizedHost(owner_id="owner", profile_id="profile", session_id="chat", resolve=broken)
    assert HermesAdapter(Runtime()).prepare_authorized("e", host=host).status == "host_failed"
    event = HumanEvent("e", "owner", "profile", "chat", 1, datetime.now(UTC), "Continue draft")
    host = AuthorizedHost(
        owner_id="owner", profile_id="profile", session_id="chat", resolve=lambda _: event
    )
    assert HermesAdapter(object()).prepare_authorized("e", host=host).status == "runtime_failed"
