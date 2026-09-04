import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from humanlike_agent.memory import Evidence, MemoryKind, MemoryRecord, SQLiteMemoryLedger
from humanlike_agent.models import MemoryScope, SessionRef, TurnInput, TurnOutcome
from humanlike_agent.persona import Persona, PersonaSpine
from humanlike_agent.runtime import HumanlikeRuntime, RuntimeConfig

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _persona() -> Persona:
    return Persona(
        PersonaSpine("A truthful AI assistant.", "Warm and direct.", "Truth and autonomy."),
        "Respect privacy.",
    )


def test_no_save_plan_has_hard_privacy_policy_before_final_truth_tail() -> None:
    runtime = HumanlikeRuntime(
        RuntimeConfig("profile-1"),
        _persona(),
        clock=lambda: NOW,
        fingerprint_key=b"p" * 32,
    )

    plan = runtime.prepare(TurnInput("Не сохраняй этот разговор", "turn-1", "session-1", "ru"))
    selected = plan.selected_fragments()

    assert plan.memory_scope is MemoryScope.SESSION_NO_SAVE
    assert any(
        fragment.fragment_id == "runtime.no_persistence" and fragment.hard for fragment in selected
    )
    assert selected[-1].fragment_id == "persona.ai_truth"


def test_minimum_context_keeps_complete_privacy_and_truth_tails() -> None:
    runtime = HumanlikeRuntime(
        RuntimeConfig("profile-1", normal_context_chars=600, deep_context_chars=600),
        _persona(),
        clock=lambda: NOW,
        fingerprint_key=b"p" * 32,
    )

    plan = runtime.prepare(TurnInput("Don't remember this", "turn-1", "session-1", "en"))
    context = plan.render_context()

    assert len(context) <= 600
    assert "MANDATORY_NO_PERSISTENCE_POLICY" in context
    assert context.endswith("replacement of human relationships.")


@pytest.mark.skipif(os.name == "nt", reason="persistent SQLite memory is POSIX-only")
def test_no_save_real_ledger_prepare_observe_finalize_creates_nothing(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "never-created"
    ledger = SQLiteMemoryLedger(state_dir / "memory.db")
    runtime = HumanlikeRuntime(
        RuntimeConfig("profile-1"),
        _persona(),
        memory=ledger,
        clock=lambda: NOW,
        fingerprint_key=b"p" * 32,
    )

    runtime.prepare(TurnInput("Don't remember this conversation", "turn-1", "session-1", "en"))
    runtime.observe(TurnOutcome("turn-1", "session-1", True, 10))
    runtime.finalize(SessionRef("session-1"))

    assert not state_dir.exists()


def test_session_no_save_is_inherited_until_finalize() -> None:
    runtime = HumanlikeRuntime(
        RuntimeConfig("profile-1"),
        _persona(),
        clock=lambda: NOW,
        fingerprint_key=b"p" * 32,
    )

    runtime.prepare(TurnInput("Don't remember this conversation", "turn-1", "session-1", "en"))
    inherited = runtime.prepare(TurnInput("Hello", "turn-2", "session-1", "en"))
    runtime.finalize(SessionRef("session-1"))
    reset = runtime.prepare(TurnInput("Hello", "turn-3", "session-1", "en"))

    assert inherited.memory_scope is MemoryScope.SESSION_NO_SAVE
    assert reset.memory_scope is MemoryScope.DEFAULT


@pytest.mark.skipif(os.name == "nt", reason="persistent SQLite memory is POSIX-only")
def test_explicit_consent_writes_to_real_ledger(tmp_path: Path) -> None:
    database = tmp_path / "state" / "memory.db"
    ledger = SQLiteMemoryLedger(database)
    runtime = HumanlikeRuntime(
        RuntimeConfig("profile-1"),
        _persona(),
        memory=ledger,
        clock=lambda: NOW,
        fingerprint_key=b"p" * 32,
    )
    record = MemoryRecord(
        record_id="memory-1",
        profile_id="profile-1",
        session_id="session-1",
        kind=MemoryKind.PREFERENCE,
        key="drink",
        value="tea",
        confidence=0.9,
        created_at=NOW,
        valid_from=NOW,
        evidence=Evidence("host", "a" * 64, NOW, "turn-1"),
    )

    runtime.prepare(TurnInput("Please remember this: tea", "turn-1", "session-1", "en"))
    receipt = runtime.observe(
        TurnOutcome("turn-1", "session-1", True, 10),
        memory_records=(record,),
    )

    assert receipt.memory_write_count == 1
    assert database.is_file()
    assert ledger.quick_check() == "ok"
