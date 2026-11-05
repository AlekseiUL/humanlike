"""Persistence failures must remain distinguishable from a successful save."""

import os
from datetime import UTC, datetime

import pytest

from humanlike_agent import AuthorizedHost, HumanEvent, PersonalMemory, SQLiteMemoryLedger

pytestmark = pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")


def test_host_reports_ambiguous_storage_failure(tmp_path, monkeypatch):
    event = HumanEvent(
        "event",
        "owner",
        "profile",
        "session",
        1,
        datetime.now(UTC),
        "Remember my preference: tone = concise",
    )
    with SQLiteMemoryLedger(tmp_path / "memory.sqlite") as ledger:
        memory = PersonalMemory(
            ledger,
            owner_id="owner",
            profile_id="profile",
            session_id="session",
            authorize=lambda *_: True,
            resolve=lambda _: event,
        )
        memory.enable()
        host = AuthorizedHost(
            owner_id="owner",
            profile_id="profile",
            session_id="session",
            resolve=lambda _: event,
            memory=memory,
        )

        def broken(_):
            raise OSError("synthetic failure")

        monkeypatch.setattr(ledger, "_persist_snapshot", broken)
        result = host.enrich(event, "base")
        assert result.status == "integration_failed"
        assert result.capture.status == "storage_unknown"
        assert result.context == "base"


def test_complete_command_is_not_stored_and_denied_capture_does_not_write(tmp_path):
    text = "Remember my interest: hobby = synthetic astronomy"
    event = HumanEvent("event", "owner", "profile", "session", 1, datetime.now(UTC), text)
    path = tmp_path / "memory.sqlite"
    with SQLiteMemoryLedger(path) as ledger:
        memory = PersonalMemory(
            ledger,
            owner_id="owner",
            profile_id="profile",
            session_id="session",
            authorize=lambda *_: True,
            resolve=lambda _: event,
        )
        memory.enable()
        before = path.read_bytes()
        assert memory.capture("event", no_save=True).status == "denied"
        assert path.read_bytes() == before
        assert memory.capture("event").status == "stored"
        assert text.encode() not in path.read_bytes()
        assert b"synthetic astronomy" in path.read_bytes()
