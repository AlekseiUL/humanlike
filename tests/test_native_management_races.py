"""Deterministically interleave real ledger writes at selection/commit boundaries."""

import os
import re
from datetime import UTC, datetime

import pytest

from humanlike_agent.native import NativeController, Scope
from humanlike_agent.personal import HumanEvent, PersonalMemory

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")


def setup(tmp_path):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    s = Scope("local-human", "unused", "synthetic", "cli")

    # Native CLI dispatch owns the real scope, not a caller-supplied chat ID.
    def command(text):
        return c.command(text, platform="cli", session_id=s.session, session_key=s.session)

    def accept(reply):
        return command("confirm " + re.search(r"confirm ([a-f0-9]{32})", reply)[1])

    assert "[enabled]" in accept(command("I agree to local memory"))
    s = c._bindings[s.session]
    for i in range(51):
        assert "[stored]" in c.handle("Usually keep replies short", s, event_id=f"seed-{i}")
    return c, s, command, accept


@pytest.mark.parametrize(
    "operation", ["Forget general reply length", "Correct that: usually give detailed replies"]
)
def test_confirmation_expires_replays_and_revokes(tmp_path, monkeypatch, operation):
    c, s, command, accept = setup(tmp_path)
    reply = command(operation)
    other = NativeController(lambda: tmp_path / "memory.sqlite")
    assert "[stored]" in other.handle("Usually keep replies short", s)
    assert "[cancelled]" in accept(reply)
    reply = command(operation)
    import humanlike_agent.native as native

    with monkeypatch.context() as m:
        m.setattr(native.time, "monotonic", lambda: float("inf"))
        assert "[cancelled]" in accept(reply)
    reply = command(operation)
    result = accept(reply)
    assert any(code in result for code in ("[forgotten]", "[stored]"))
    assert "[cancelled]" in accept(reply)
    if operation.startswith("Forget"):
        # Replaying a pre-forget event cannot resurrect a deleted lineage.
        assert "[replayed]" in other.handle("Usually keep replies short", s, event_id="seed-0")
        assert other._memory(s).inspect() == ()


@pytest.mark.parametrize(
    "operation", ["Forget general reply length", "Correct that: usually give detailed replies"]
)
def test_policy_change_during_target_selection(tmp_path, monkeypatch, operation):
    c, s, _, _ = setup(tmp_path)
    original = PersonalMemory.management_targets
    other = NativeController(lambda: tmp_path / "memory.sqlite")

    def interleave(memory, *args, **kwargs):
        result = original(memory, *args, **kwargs)
        # Direct SDK control avoids calling the patched selector recursively.
        other._memory(s).disable()
        return result

    monkeypatch.setattr(PersonalMemory, "management_targets", interleave)
    assert "[cancelled]" in c.handle(operation, s)
    assert len(c._memory(s).inspect()) == 50  # bounded SDK first page, no erasure
    assert len(c._memory(s).inspect(after=c._memory(s).inspect()[-1].sequence)) == 1


def test_capture_rechecks_whole_policy_not_just_epoch(tmp_path):
    c, s, _, _ = setup(tmp_path)
    old = c._memory(s).policy()
    assert "[stored]" in c.handle("Usually keep replies short", s)
    now = c._memory(s).policy()
    assert old[1] == now[1] and old[2] != now[2]
    event = HumanEvent(
        "late",
        s.owner,
        "humanlike-native",
        s.chat,
        now[2] + 1,
        datetime.now(UTC),
        "Usually give detailed replies",
    )
    assert c._memory(s, event).capture("late", expected_policy=old).status == "revoked"
    assert c._memory(s).recall("reply_length")[0].record.value == "short"


def test_page_invalidated_during_read_and_after_timeout(tmp_path, monkeypatch):
    c, s, _, _ = setup(tmp_path)
    original = PersonalMemory.inspect_page

    def interleave(memory, **kwargs):
        result = original(memory, **kwargs)
        memory.disable()
        return result

    with monkeypatch.context() as m:
        m.setattr(PersonalMemory, "inspect_page", interleave)
        assert "[page_expired]" in c.handle("What do you remember?", s)
    assert "[stored_records]" in c.handle("What do you remember?", s)
    import humanlike_agent.native as native

    monkeypatch.setattr(native.time, "monotonic", lambda: float("inf"))
    assert "[page_expired]" in c.handle("Next memory page", s)


def test_management_read_authorization_and_bounds(tmp_path):
    c, s, _, _ = setup(tmp_path)
    memory = c._memory(s)
    for limit in [0, 6, True]:
        with pytest.raises(ValueError):
            memory.inspect_page(limit=limit)
    with pytest.raises(ValueError):
        memory.management_targets("reply_length", domain="unknown")
    memory._authorize = lambda *args: False
    with pytest.raises(PermissionError):
        memory.inspect_page()
    with pytest.raises(PermissionError):
        memory.management_targets("reply_length")
