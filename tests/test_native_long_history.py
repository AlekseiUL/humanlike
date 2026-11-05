"""Synthetic version histories; owner controls must not depend on the first page."""

import json
import os

import pytest

from humanlike_agent.native import NativeController, Scope

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")


def seeded(tmp_path, count):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    s = Scope("owner", "chat", "session", "cli")
    assert "[enabled]" in c.handle("I agree to local memory", s)
    for _ in range(count):
        assert "[stored]" in c.handle("Usually keep replies short", s)
    return c, s


def page(reply):
    assert reply.startswith("[stored_records]"), reply
    return json.loads(reply[reply.index("{") :])


@pytest.mark.parametrize("count", [49, 50, 51, 120, 255])
def test_full_history_is_pageable_correctable_and_forgettable(tmp_path, count):
    c, s = seeded(tmp_path, count)
    seen = []
    response = c.handle("What do you remember?", s)
    while True:
        data = page(response)
        assert 1 <= len(data["records"]) <= 5
        seen.extend(data["records"])
        if not data["has_more"]:
            break
        response = c.handle("Next memory page", s)
    assert len(seen) == count
    assert len({row["source"] for row in seen}) == count
    assert sum(row["active"] for row in seen) == 1
    assert "[stored]" in c.handle("Correct that: usually give detailed replies", s)
    assert c._memory(s).recall("reply_length")[0].record.value == "detailed"
    # First page contains only replaced versions, not the current correction.
    assert not any(row["active"] for row in page(c.handle("What do you remember?", s))["records"])
    assert "[forgotten]" in c.handle("Forget general reply length", s)
    restarted = NativeController(lambda: tmp_path / "memory.sqlite")
    assert "[empty]" in restarted.handle("What do you remember?", s)
    assert not restarted._memory(s).recall("reply_length")


def test_page_and_target_selection_are_independent(tmp_path):
    c, s = seeded(tmp_path, 51)
    assert "[stored]" in c.handle("Explain learning topics in detail", s)
    assert "[clarify]" in c.handle("Forget that", s)
    assert "[stored]" in c.handle("Correct that: explain learning topics in detail", s)
    assert "[forgotten]" in c.handle("Forget learning reply length", s)
    assert c._memory(s).recall("reply_length")[0].record.value == "short"
    assert len(c._memory(s).inspect()) == 50


def test_pagination_changed_policy_restart_and_isolation(tmp_path):
    c, s = seeded(tmp_path, 51)
    page(c.handle("What do you remember?", s))
    other = NativeController(lambda: tmp_path / "memory.sqlite")
    assert "[stored]" in other.handle("Correct that: usually give detailed replies", s)
    assert "[page_expired]" in c.handle("Next memory page", s)
    page(c.handle("What do you remember?", s))
    assert "[page_expired]" in other.handle("Next memory page", s)
    for foreign in [
        Scope("other", "chat", "session", "cli"),
        Scope("owner", "other", "session", "cli"),
    ]:
        assert "[page_expired]" in c.handle("Next memory page", foreign)
        assert "[empty]" in c.handle("What do you remember?", foreign)
    assert "[no_save]" in c.handle("Do not save this session", s)
    assert "[no_recall]" in c.handle("Do not recall this session", s)
    page(c.handle("What do you remember?", s))
    page(c.handle("Next memory page", s))
    assert "[no_save]" in c.handle("Correct that: usually give detailed replies", s)
    assert "[forgotten]" in c.handle("Forget general reply length", s)


def test_full_group_still_allows_inspection_and_forget(tmp_path):
    c, s = seeded(tmp_path, 256)
    assert "[group_full]" in c.handle("Correct that: usually give detailed replies", s)
    page(c.handle("What do you remember?", s))
    assert "[forgotten]" in c.handle("Forget general reply length", s)
    assert "[stored]" in c.handle("Usually give detailed replies", s)
    assert len(c._memory(s).inspect()) == 1


def test_large_two_scope_history_and_other_owners_survive_forget(tmp_path):
    c, s = seeded(tmp_path, 256)
    for _ in range(256):
        assert "[stored]" in c.handle("Explain learning topics in detail", s)
    foreign_scopes = [
        Scope("other", "chat", "foreign", "cli"),
        Scope("owner", "other", "foreign", "cli"),
    ]
    for foreign in foreign_scopes:
        c.handle("I agree to local memory", foreign)
        assert "[stored]" in c.handle("Usually keep replies short", foreign)
    response = c.handle("What do you remember?", s)
    records = []
    while True:
        data = page(response)
        records.extend(data["records"])
        if not data["has_more"]:
            break
        response = c.handle("Next memory page", s)
    assert len(records) == len({r["source"] for r in records}) == 512
    assert sum(r["active"] for r in records) == 2
    assert "[clarify]" in c.handle("Forget that", s)
    assert "[disabled]" in c.handle("Pause memory", s)
    assert "[forgotten]" in c.handle("Forget general reply length", s)
    assert all(f.domain == "learning" for f in c._memory(s).inspect())
    for foreign in foreign_scopes:
        assert c._memory(foreign).recall("reply_length")[0].record.value == "short"
    assert "[forgotten]" in c.handle("Forget learning reply length", s)
    assert "[empty]" in c.handle("What do you remember?", s)


def test_scoped_forget_erases_contradictory_lineage_only(tmp_path):
    c, s = seeded(tmp_path, 51)
    assert "[stored]" in c.handle("Usually give detailed replies", s)
    assert "[clarify]" in c.handle("Correct that: usually give detailed replies", s)
    assert "[stored]" in c.handle("Explain learning topics in detail", s)
    assert "[forgotten]" in c.handle("Forget general reply length", s)
    assert not c._memory(s).recall("reply_length")
    assert c._memory(s).recall("reply_length", domain="learning")
