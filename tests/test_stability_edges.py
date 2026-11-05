"""Only synthetic data; native authority is exercised through command challenges."""

import json
import os
import re
from datetime import UTC, datetime

import pytest

from humanlike_agent.models import TurnInput
from humanlike_agent.native import NativeController, Scope, digest
from humanlike_agent.personal import HumanEvent
from humanlike_agent.router import route_turn

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")


def cmd(c, text):
    return c.command(text, session_id="s", session_key="s", platform="cli")


def challenge(c, text):
    reply = cmd(c, text)
    return re.search(r"/humanlike (confirm [a-f0-9]{32})", reply)[1]


def approve(c, text):
    return cmd(c, challenge(c, text))


def seed(tmp_path, count=3):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    approve(c, "I agree to local memory")
    s = c._bindings["s"]
    for i in range(count):
        event = HumanEvent(
            f"fixture-{i}",
            s.owner,
            "humanlike-native",
            s.chat,
            c._memory(s).policy()[2] + 1,
            datetime.now(UTC),
            f"Remember my preference: reply_length = value-{i}",
        )
        assert c._memory(s, event).capture(event.event_id).status == "stored"
    return c, s


@pytest.mark.parametrize("count", [2, 33, 51, 255, 256])
def test_group_resolution_bounded_history_and_pages(tmp_path, count):
    c, s = seed(tmp_path, count)
    result = approve(c, "correct that: usually give detailed replies")
    memory = c._memory(s)
    if count == 256:
        assert "[group_full]" in result
        assert memory.recall("reply_length") == ()
    else:
        assert "[stored]" in result
        (fact,) = memory.recall("reply_length")
        assert fact.record.value == "detailed"
        assert len(fact.record.supersedes) == count
    rows = []
    reply = cmd(c, "what do you remember")
    while True:
        page = json.loads(reply[reply.index("{") :])
        rows.extend(page["records"])
        if not page["has_more"]:
            break
        reply = cmd(c, "next memory page")
    assert len(rows) == count + (count < 256)
    assert sum(r["active"] for r in rows) == (1 if count < 256 else count)
    assert "[forgotten]" in approve(c, "forget general reply length")
    assert not memory.inspect()
    assert not memory.recall("reply_length")


@pytest.mark.parametrize("invalidate", ["cancel", "restart", "revoke", "write", "no_save"])
def test_group_challenge_invalidated_without_commit(tmp_path, invalidate):
    c, s = seed(tmp_path)
    token = challenge(c, "correct that: usually give detailed replies")
    if invalidate == "cancel":
        cmd(c, "cancel")
    elif invalidate == "restart":
        c = NativeController(lambda: tmp_path / "memory.sqlite")
    elif invalidate == "revoke":
        cmd(c, "pause memory")
    elif invalidate == "no_save":
        cmd(c, "do not save this session")
    else:
        other = NativeController(lambda: tmp_path / "memory.sqlite")
        other.handle("correct that: usually keep replies short", s)
    assert "[cancelled]" in cmd(c, token)
    assert "[cancelled]" in cmd(c, token)
    assert len(c._memory(s).inspect()) == (4 if invalidate == "write" else 3)


def test_scope_choice_keeps_general_and_current_request_is_temporary(tmp_path):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    approve(c, "согласен на локальную память")
    approve(c, "обычно отвечай кратко")
    assert "[conflict_choice]" in approve(c, "Запомни: я предпочитаю подробные ответы")
    assert "[stored]" in approve(c, "объясняй учебные темы подробно")
    s = c._bindings["s"]
    assert c._memory(s).recall("reply_length")[0].record.value == "short"
    assert c._memory(s).recall("reply_length", domain="learning")[0].record.value == "detailed"
    for text in [
        "сейчас объясни подробно",
        "explain this in detail now",
        '"обычно отвечай подробно"',
        "не запоминай: обычно отвечай подробно",
        "usually keep replies shrot",
        "usually keep replies short; pause memory",
    ]:
        assert "[stored]" not in cmd(c, text)
    assert len(c._memory(s).inspect()) == 2


def test_mixed_no_save_admission_survives_restart(tmp_path):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    s = Scope(digest("telegram", "fixture"), digest("telegram", "fixture", "chat"), "s", "telegram")
    c._bindings["s"] = s
    text = "Build a CSV parser. Do not save this session."
    source = {"platform": "telegram", "chat_type": "dm", "user_id": "fixture", "chat_id": "chat"}
    assert c.admitted(source=source, platform="telegram", text=text, message_id="1") is None
    assert c._memory(s).session_mode("s")[0]
    other = NativeController(lambda: tmp_path / "memory.sqlite")
    assert other._memory(s).session_mode("s")[0]
    other.handle("I agree to local memory", s)
    assert "[no_save]" in other.handle("usually keep replies short", s)
    assert not other._memory(s).inspect()


def test_disk_refusal_never_claims_saved(tmp_path, monkeypatch):
    c, s = seed(tmp_path)
    token = challenge(c, "correct that: usually give detailed replies")
    from humanlike_agent.memory import SQLiteMemoryLedger

    monkeypatch.setattr(
        SQLiteMemoryLedger,
        "_insert_record",
        lambda *a: (_ for _ in ()).throw(OSError("synthetic private detail")),
    )
    result = cmd(c, token)
    assert "[error]" in result and "synthetic private detail" not in result
    assert len(c._memory(s).inspect()) == 3
    assert not c._memory(s).recall("reply_length")
    assert "[cancelled]" in cmd(c, token)


@pytest.mark.parametrize("text", ["Hello!", "Привет, бро", "Thanks!", "Ясно 😄"])
def test_positive_social_is_retained(text):
    assert route_turn(TurnInput(text)).mode.value == "social"


@pytest.mark.parametrize("selection", ["partial", "foreign", "condition"])
def test_group_selection_cannot_widen_scope(tmp_path, selection):
    from dataclasses import replace

    c, s = seed(tmp_path)
    memory = c._memory(s)
    targets = tuple(f.record.record_id for f in memory.management_targets("reply_length"))
    event = HumanEvent(
        "correction",
        s.owner,
        "humanlike-native",
        s.chat,
        memory.policy()[2] + 1,
        datetime.now(UTC),
        "correct that: usually give detailed replies",
        target_ids=targets,
    )
    if selection == "partial":
        event = replace(event, target_ids=targets[:1])
    elif selection == "foreign":
        event = replace(event, target_ids=(*targets, "foreign-record"))
    else:
        event = replace(event, condition="learning_only")
    assert c._memory(s, event).capture(event.event_id).status == "invalid_target"
    assert len(memory.inspect()) == 3
    assert not memory.recall("reply_length")


def test_legacy_authorized_no_save_independent_of_unknown_route(tmp_path):
    from dataclasses import replace

    from humanlike_agent.adapters.hermes import HermesAdapter
    from humanlike_agent.hermes_plugin import build_default_runtime
    from humanlike_agent.host import AuthorizedHost
    from humanlike_agent.memory import SQLiteMemoryLedger
    from humanlike_agent.personal import PersonalMemory

    event = HumanEvent(
        "e1",
        "owner",
        "profile",
        "chat",
        1,
        datetime.now(UTC),
        "Build a CSV parser. Do not save this session.",
    )
    events = {"e1": event}
    memory = PersonalMemory(
        SQLiteMemoryLedger(tmp_path / "legacy.sqlite"),
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        authorize=lambda *_: True,
        resolve=events.get,
    )
    memory.enable()
    host = AuthorizedHost(
        owner_id="owner", profile_id="profile", session_id="chat", resolve=events.get, memory=memory
    )
    adapter = HermesAdapter(build_default_runtime())
    first = adapter.prepare_authorized("e1", host=host)
    assert first.capture.status == "denied"
    events["e2"] = replace(
        event, event_id="e2", sequence=2, text="Remember my preference: reply_length = detailed"
    )
    assert adapter.prepare_authorized("e2", host=host).capture.status == "denied"
    assert not memory.inspect()


def test_late_group_confirmation_and_retry(tmp_path, monkeypatch):
    import humanlike_agent.native as native

    c, s = seed(tmp_path)
    token = challenge(c, "correct that: usually give detailed replies")
    clock = native.time.monotonic
    with monkeypatch.context() as m:
        m.setattr(native.time, "monotonic", lambda: clock() + 301)
        assert "[cancelled]" in cmd(c, token)
    assert len(c._memory(s).inspect()) == 3
    assert "[stored]" in approve(c, "correct that: usually give detailed replies")
    assert c._memory(s).recall("reply_length")[0].record.value == "detailed"
