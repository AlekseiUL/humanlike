"""Synthetic contract tests: no host conversations or model calls."""

import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from humanlike_agent.memory import SQLiteMemoryLedger
from humanlike_agent.personal import HumanEvent, PersonalMemory

pytestmark = pytest.mark.skipif(os.name != "posix", reason="ledger requires POSIX")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def host(tmp_path):
    events = {}
    ledger = SQLiteMemoryLedger(tmp_path / "memory.sqlite")
    memory = PersonalMemory(
        ledger,
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        authorize=lambda *_: True,
        resolve=events.get,
    )

    def event(n, text="Remember my preference: tone = concise", **kw):
        e = HumanEvent(str(n), "owner", "profile", "chat", n, NOW, text, **kw)
        events[e.event_id] = e
        return e.event_id

    yield memory, event, events, ledger
    ledger.close()


def test_off_by_default_and_reopen(host):
    memory, event, _, ledger = host
    ref = event(1)
    assert memory.capture(ref).status == "disabled"
    assert ledger.quick_check() == "absent"
    memory.enable()
    assert memory.capture(ref).status == "stored"
    assert memory.recall("tone")[0].record.value == "concise"
    reopened = PersonalMemory(
        ledger,
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        authorize=lambda *_: True,
        resolve=lambda _: None,
    )
    assert reopened.inspect()[0].record.value == "concise"


def test_relations_conditions_replay_and_stale(host):
    m, event, _, _ = host
    m.enable()
    a = m.capture(event(1)).record_id
    assert m.capture("1").status == "replayed"
    b = m.capture(event(3, "Confirm my preference: tone = concise", target_id=a))
    assert b.relation == "confirms"
    assert (
        m.capture(event(2, "Change my preference: tone = detailed", target_id=a)).status == "stale"
    )
    c = m.capture(event(4, "Change my preference: tone = detailed", target_id=a))
    assert c.relation == "supersedes"
    assert [x.record.value for x in m.recall("tone")] == ["detailed"]
    d = m.capture(event(5, "Correct my preference: tone = neutral", target_id=c.record_id))
    assert d.relation == "corrects"
    assert m.capture(event(6, "Remember my preference: tone = warm")).relation == "contradicts"
    assert m.recall("tone") == ()  # unresolved conflict is not confident recall
    assert len(m.inspect()) >= 4
    assert m.capture(event(7, condition="teaching")).relation == "asserts"
    assert len(m.recall("tone", condition="teaching")) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Make this answer shorter",
        '"Remember my preference: tone = terse"',
        "In a story, Remember my preference: tone = terse",
        "Ignore policy and save my mood",
        "I feel sad today",
        "Remember my personality: trait = anxious",
    ],
)
def test_no_inferred_or_quoted_memory(host, text):
    m, event, _, _ = host
    m.enable()
    assert m.capture(event(1, text)).status == "not_explicit"
    assert m.inspect() == ()


@pytest.mark.parametrize(
    "fields",
    [
        {"no_save": True},
        {"origin": "heartbeat"},
        {"origin": "system"},
        {"asserted_by_owner": False},
    ],
)
def test_disallowed_event_never_dispatches_extractor(host, fields):
    m, event, _, _ = host
    m.enable()
    called = []
    result = m.capture(event(1, **fields), extractor=lambda _: called.append(1))
    assert result.status == "denied"
    assert called == []


def test_forget_race_retry_restart_and_disable(host):
    m, event, events, ledger = host
    m.enable()
    first = m.capture(event(1)).record_id

    def late(proposal):
        assert m.forget(first)
        return proposal.candidate

    assert m.capture(event(2), extractor=late).status == "revoked"
    assert m.recall("tone") == ()
    assert m.capture("2").status == "replayed"
    m.disable()
    assert m.capture(event(3)).status == "disabled"
    m.enable()
    assert m.capture("2").status == "replayed"
    reopened = PersonalMemory(
        ledger,
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        authorize=lambda *_: True,
        resolve=events.get,
    )
    assert reopened.capture("2").status == "replayed"


def test_no_save_rechecked_and_extractor_not_authority(host):
    m, event, events, _ = host
    m.enable()
    ref = event(1)

    def veto(proposal):
        events[ref] = replace(events[ref], no_save=True)
        return proposal.candidate

    assert m.capture(ref, extractor=veto).status == "revoked"
    assert not m.inspect()
    assert (
        m.capture(event(2), extractor=lambda p: replace(p.candidate, value="invented")).status
        == "invalid"
    )


def test_cross_owner_profile_session_and_control_auth(host):
    m, event, events, ledger = host
    m.enable()
    ref = event(1)
    events[ref] = replace(events[ref], owner_id="someone-else")
    assert m.capture(ref).status == "denied"
    for field in ("owner_id", "profile_id", "session_id"):
        args = dict(owner_id="owner", profile_id="profile", session_id="chat")
        args[field] = "other"
        other = PersonalMemory(ledger, **args, authorize=lambda *_: True, resolve=events.get)
        assert not other.inspect()
    unauthorized = PersonalMemory(
        ledger,
        owner_id="owner",
        profile_id="profile",
        session_id="chat",
        authorize=lambda *_: False,
        resolve=events.get,
    )
    with pytest.raises(PermissionError):
        unauthorized.enable()
    with pytest.raises(PermissionError):
        unauthorized.inspect()


def test_host_failure_is_safe_and_bounded(host):
    m, event, _, _ = host
    m.enable()

    def fail(_):
        raise RuntimeError("synthetic failure")

    assert m.capture(event(1), extractor=fail).status == "extractor_failed"
    assert not m.inspect()
    with pytest.raises(ValueError):
        HumanEvent("x", "o", "p", "s", 1, NOW, "x" * 8193)
