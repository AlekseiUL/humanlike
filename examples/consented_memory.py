"""Offline end-to-end demo. All data is synthetic; no provider or host DB access.

Run after a normal install: python examples/consented_memory.py
On Windows the read-only conversation path runs; durable memory needs POSIX.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from humanlike_agent import (
    AuthorizedHost,
    ConversationContext,
    HistoryItem,
    HumanEvent,
    HumanlikeRuntime,
    Persona,
    PersonalMemory,
    PersonaSpine,
    RuntimeConfig,
    SQLiteMemoryLedger,
)
from humanlike_agent.adapters.hermes import HermesAdapter


def run() -> dict[str, object]:
    now = datetime.now(UTC)
    events = {
        "turn-1": HumanEvent(
            "turn-1",
            "demo-owner",
            "demo-profile",
            "demo-session",
            1,
            now,
            "Remember my preference: tone = concise",
        ),
    }
    history = ConversationContext(
        owner_id="demo-owner",
        profile_id="demo-profile",
        session_id="demo-session",
        history=lambda: (
            HistoryItem(
                "receipt-1",
                "demo-owner",
                "demo-profile",
                "demo-session",
                "outline",
                "tool",
                "Synthetic export did not complete",
                "failed",
            ),
            HistoryItem(
                "artifact-1",
                "demo-owner",
                "demo-profile",
                "demo-session",
                "outline",
                "artifact",
                "Synthetic outline: introduction, method, conclusion",
            ),
        ),
    )
    continuation = replace(
        events["turn-1"], event_id="turn-2", sequence=2, text="Continue outline", no_save=True
    )
    recalled = history.recall(continuation)
    assert len(recalled.items) == 2 and recalled.items[0].outcome == "failed"
    assert not history.recall(replace(continuation, text="Explain triangles")).items
    results: dict[str, object] = {
        "conversation": "PASS",
        "unrelated_request": "no_match",
        "model_ab": "NOT_RUN",
    }
    if os.name != "posix":
        return {**results, "memory": "UNSUPPORTED_PLATFORM"}
    with TemporaryDirectory(prefix="humanlike-demo-") as temporary:
        path = Path(temporary).resolve() / "memory.sqlite"
        with SQLiteMemoryLedger(path) as ledger:
            # Synthetic authorization ONLY. Production must check the signed-in
            # owner, transport origin, consent and action ACL, never trust text.
            memory = PersonalMemory(
                ledger,
                owner_id="demo-owner",
                profile_id="demo-profile",
                session_id="demo-session",
                authorize=lambda *_: True,
                resolve=events.get,
            )
            assert memory.capture("turn-1").status == "disabled"
            memory.enable()
            host = AuthorizedHost(
                owner_id="demo-owner",
                profile_id="demo-profile",
                session_id="demo-session",
                resolve=events.get,
                memory=memory,
                conversation=history,
            )
            persona = Persona(
                PersonaSpine("AI assistant", "Clear and direct", "Accuracy"),
                "Never invent tool success.",
            )
            adapter = HermesAdapter(HumanlikeRuntime(RuntimeConfig("demo-profile"), persona))
            first = adapter.prepare_authorized("turn-1", host=host, memory_keys=("tone",))
            assert first.status == "prepared" and first.capture.status == "stored"
            assert "concise" in first.context
            events["turn-2"] = continuation
            second = adapter.prepare_authorized("turn-2", host=host, memory_keys=("tone",))
            assert second.status == "prepared" and second.capture.status == "denied"
            assert "artifact-1" in second.context and "failed" in second.context
            assert len(memory.inspect()) == 1
            events["turn-3"] = replace(
                events["turn-1"],
                event_id="turn-3",
                sequence=3,
                text="Correct my preference: tone = neutral",
                target_id=first.capture.record_id,
            )
            correction = memory.correct("turn-3")
            assert correction.relation == "corrects"
            assert memory.recall("tone")[0].record.value == "neutral"
        # A new ledger object reads the actual persisted image, not an in-memory cache.
        with SQLiteMemoryLedger(path) as ledger:
            memory = PersonalMemory(
                ledger,
                owner_id="demo-owner",
                profile_id="demo-profile",
                session_id="demo-session",
                authorize=lambda *_: True,
                resolve=events.get,
            )
            assert memory.recall("tone")[0].record.value == "neutral"
            assert memory.forget(correction.record_id)
            assert not memory.inspect()
            assert memory.capture("turn-3").status == "replayed"
            memory.disable()
            assert memory.capture("turn-1").status == "disabled"
            assert ledger.quick_check() == "ok"
        results.update(
            memory="PASS",
            reopen="PASS",
            correction="PASS",
            forget="PASS",
            replay="blocked",
            no_save="blocked",
            adapter="PASS",
        )
    return results


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
