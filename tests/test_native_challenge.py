"""Native transport metadata lacks forwarded-message provenance: require a fresh challenge."""

import os
import re

import pytest

from humanlike_agent.native import NativeController

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")


def invoke(controller, text, session="synthetic"):
    return controller.command(text, platform="cli", session_id=session, session_key=session)


def accept(controller, reply):
    token = re.search(r"/humanlike confirm ([a-f0-9]{32})", reply).group(1)
    return invoke(controller, "confirm " + token)


def test_native_control_requires_fresh_challenge_and_is_single_use(tmp_path):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    reply = invoke(c, "I agree to local memory")
    assert "[confirmation_required]" in reply
    assert "[disabled]" in invoke(c, "status")
    assert "[cancelled]" in invoke(c, "confirm " + "0" * 32)
    reply = invoke(c, "I agree to local memory")
    assert "[enabled]" in accept(c, reply)
    assert "[cancelled]" in accept(c, reply)
    reply = invoke(c, "usually keep replies short")
    assert "[empty]" in invoke(c, "what do you remember")
    assert "[stored]" in accept(c, reply)


def test_challenge_is_session_scoped_revocable_and_not_restored(tmp_path):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    reply = invoke(c, "I agree to local memory")
    token = re.search(r"confirm ([a-f0-9]{32})", reply).group(1)
    assert "[cancelled]" in invoke(c, "confirm " + token, session="other")
    assert "[enabled]" in accept(c, reply)
    reply = invoke(c, "usually keep replies short")
    assert "[disabled]" in invoke(c, "pause memory")
    assert "[cancelled]" in accept(c, reply)
    reply = invoke(c, "I agree to local memory")
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    assert "[cancelled]" in accept(c, reply)


def test_delayed_consent_cannot_override_newer_revocation(tmp_path):
    from humanlike_agent.native import Scope

    c = NativeController(lambda: tmp_path / "memory.sqlite")
    scope = Scope("owner", "chat", "session", "cli")
    memory = c._memory(scope)
    old_policy = memory.policy()
    assert memory.control("disable", session="session", event_id="stop", sequence=10) == "applied"
    assert (
        memory.control(
            "consent", session="session", event_id="late", sequence=11, expected_policy=old_policy
        )
        == "revoked"
    )
    assert "[revoked]" in c.handle(
        "I agree to local memory", scope, sequence=12, required_policy=old_policy
    )
    assert memory.policy()[0] is False
