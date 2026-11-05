"""Synthetic journeys for the controller (native dispatch is tested separately)."""

import os
from pathlib import Path

import pytest

from humanlike_agent.native import NativeController, Scope

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")


def controller(tmp_path):
    return NativeController(lambda: tmp_path / "memory.sqlite")


def test_complete_journey(tmp_path):
    c = controller(tmp_path)
    s = Scope("owner", "chat", "session", "cli")
    assert "disabled" in c.handle("status", s)
    assert not (tmp_path / "memory.sqlite").exists()
    assert "consent_required" in c.handle("enable memory", s)
    assert "enabled" in c.handle("I agree to local memory", s)
    assert "stored" in c.handle("Запомни: обычно отвечай кратко", s)
    assert "short" in c.handle("Что ты обо мне помнишь?", s)
    assert "stored" in c.handle("Исправь это: обычно отвечай подробно", s)
    assert "detailed" in c.handle("Что ты обо мне помнишь?", s)
    assert "forgotten" in c.handle("Забудь это", s)
    c = controller(tmp_path)
    assert "empty" in c.handle("Что ты обо мне помнишь?", s)
    assert "disabled" in c.handle("Pause memory", s)
    assert "disabled" in controller(tmp_path).handle("status", s)


def test_proposal_is_not_write_and_late_confirmation_revoked(tmp_path):
    c = controller(tmp_path)
    s = Scope("owner", "chat", "session", "cli")
    c.handle("I agree to local memory", s)
    assert "pending" in c.handle("Usually keep replies short", s, direct=False)
    assert "empty" in c.handle("What do you remember?", s)
    assert "stored" in c.handle("Confirm", s)
    c.handle("Correct that: usually give detailed replies", s, direct=False)
    other = controller(tmp_path)
    other.handle("Pause memory", s)
    assert "cancelled" in c.handle("Confirm", s)


def test_isolation_no_save_and_ambiguity(tmp_path):
    c = controller(tmp_path)
    s = Scope("owner", "chat", "session", "cli")
    c.handle("I agree to local memory", s)
    c.handle("Usually keep replies short", s)
    c.handle("Explain learning topics in detail", s)
    assert "clarify" in c.handle("Forget that", s)
    assert "empty" in c.handle("What do you remember?", Scope("other", "chat", "session", "cli"))
    assert "empty" in c.handle("What do you remember?", Scope("owner", "other", "session", "cli"))
    assert "no_save" in c.handle("Do not save this session", s)
    assert "no_save" in c.handle("Usually keep replies short", s)
    assert "short" in c.handle("What do you remember?", s)
    assert "no_recall" in c.handle("Do not recall this session", s)


def test_restart_cancels_pending(tmp_path):
    c = controller(tmp_path)
    s = Scope("owner", "chat", "session", "cli")
    c.handle("I agree to local memory", s)
    c.handle("Usually keep replies short", s, direct=False)
    assert "cancelled" in controller(tmp_path).handle("Confirm", s)


def test_error_is_not_saved(tmp_path):
    c = NativeController(lambda: Path("/nonexistent-parent-not-created/memory.sqlite"))
    s = Scope("owner", "chat", "session", "cli")
    # Existing unsafe directory path must not read as a success.
    bad = tmp_path / "bad"
    bad.mkdir()
    c = NativeController(lambda: bad)
    assert "error" in c.handle("I agree to local memory", s)
