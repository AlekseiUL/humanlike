"""Strict decoder, session policy and realistic explicit behavioral comparisons."""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from humanlike_agent import (
    AuthorizedHost,
    Candidate,
    HumanEvent,
    HumanlikeRuntime,
    Persona,
    PersonalMemory,
    PersonaSpine,
    RuntimeConfig,
    SQLiteMemoryLedger,
)
from humanlike_agent.adapters.hermes import HermesAdapter


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        '{"operation":"remember"}',
        '{"operation":"remember","kind":"preference","key":"tone","value":true}',
        '{"operation":"remember","kind":"preference","key":"tone","value":"a","no_save":false}',
        '{"operation":"remember","operation":"correct","kind":"preference","key":"tone","value":"a"}',
        '{"operation":"remember","kind":"trait","key":"mood","value":"sad"}',
        "x" * 2049,
    ],
)
def test_candidate_decoder_fails_closed(raw):
    with pytest.raises((TypeError, ValueError)):
        Candidate.from_json(raw)


def test_provider_neutral_candidate_roundtrip():
    candidate = Candidate("remember", "preference", "tone", "concise")
    assert Candidate.from_json(json.dumps(asdict(candidate))) == candidate


@pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")
def test_runtime_session_no_save_cannot_be_bypassed_by_new_bridge(tmp_path):
    events = {}

    def event(n, text):
        ref = str(n)
        events[ref] = HumanEvent(ref, "owner", "profile", "session", n, datetime.now(UTC), text)
        return ref

    persona = Persona(PersonaSpine("AI assistant", "Clear", "Accuracy"), "Be truthful.")
    adapter = HermesAdapter(HumanlikeRuntime(RuntimeConfig("profile"), persona))
    with SQLiteMemoryLedger(tmp_path / "memory.sqlite") as ledger:
        memory = PersonalMemory(
            ledger,
            owner_id="owner",
            profile_id="profile",
            session_id="session",
            authorize=lambda *_: True,
            resolve=events.get,
        )
        memory.enable()
        host = AuthorizedHost(
            owner_id="owner",
            profile_id="profile",
            session_id="session",
            resolve=events.get,
            memory=memory,
        )
        adapter.prepare_authorized(event(1, "Do not save anything from this session."), host=host)
        later = adapter.prepare_authorized(
            event(2, "Remember my preference: tone = concise"), host=host
        )
        assert later.capture.status == "denied"
        assert not memory.inspect()
        adapter.on_session_finalize(session_id="session")
        # Host must continue no_save metadata after finalize/restart if its own
        # consent policy still prohibits persistence; runtime metadata is ephemeral.
        assert not adapter._prepared_scopes


@pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")
def test_explicit_work_and_learning_preferences_without_false_conflicts(tmp_path):
    events = {}
    with SQLiteMemoryLedger(tmp_path / "memory.sqlite") as ledger:
        memory = PersonalMemory(
            ledger,
            owner_id="owner",
            profile_id="profile",
            session_id="session",
            authorize=lambda *_: True,
            resolve=events.get,
        )

        def save(n, text, condition="always", target_id=None):
            ref = str(n)
            events[ref] = HumanEvent(
                ref,
                "owner",
                "profile",
                "session",
                n,
                datetime.now(UTC),
                text,
                domain="communication",
                condition=condition,
                target_id=target_id,
            )
            return memory.capture(ref)

        assert save(1, "Remember my preference: detail = concise", "email").status == "disabled"
        memory.enable()
        assert save(2, "Make this email shorter.", "email").status == "not_explicit"
        first = save(3, "Remember my preference: detail = concise", "email")
        assert first.status == "stored"
        assert (
            save(4, "Remember my preference: detail = step by step", "learning").relation
            == "asserts"
        )
        assert (
            memory.recall("detail", domain="communication", condition="email")[0].record.value
            == "concise"
        )
        assert (
            memory.recall("detail", domain="communication", condition="learning")[0].record.value
            == "step by step"
        )
        assert (
            save(
                5, "Change my preference: detail = summary plus evidence", "email", first.record_id
            ).relation
            == "supersedes"
        )
        assert not memory.recall("detail")  # no unspecified-scope fallback
        assert len(memory.inspect()) == 3


@pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")
def test_host_rejects_misbound_scopes(tmp_path):
    with SQLiteMemoryLedger(tmp_path / "memory.sqlite") as ledger:
        memory = PersonalMemory(
            ledger,
            owner_id="other",
            profile_id="profile",
            session_id="session",
            authorize=lambda *_: True,
            resolve=lambda _: None,
        )
        with pytest.raises(ValueError, match="scope"):
            AuthorizedHost(
                owner_id="owner",
                profile_id="profile",
                session_id="session",
                resolve=lambda _: None,
                memory=memory,
            )
