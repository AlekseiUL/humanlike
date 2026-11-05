"""Read-only synthetic continuation tests."""

from datetime import UTC, datetime

from humanlike_agent.conversation import ConversationContext, HistoryItem
from humanlike_agent.personal import HumanEvent


def request(text="Continue draft", **kw):
    return HumanEvent(
        "turn", "owner", "profile", "session", 1, datetime(2026, 1, 1, tzinfo=UTC), text, **kw
    )


def item(ref="artifact-1", **kw):
    values = dict(
        source_id=ref,
        owner_id="owner",
        profile_id="profile",
        session_id="session",
        anchor="draft",
        kind="artifact",
        content="Synthetic outline",
        outcome=None,
    )
    values.update(kw)
    return HistoryItem(**values)


def context(items, **kw):
    return ConversationContext(
        owner_id="owner",
        profile_id="profile",
        session_id="session",
        history=lambda: iter(items),
        **kw,
    )


def test_continuation_preserves_artifact_and_real_receipt():
    c = context([item("tool-1", kind="tool", content="write result", outcome="failed"), item()])
    result = c.recall(request(no_save=True))
    assert len(result.items) == 2
    assert result.items[0].outcome == "failed"
    assert "artifact-1" in result.render()
    assert "REFERENCE_DATA" in result.render()
    assert not c.recall(request("What is the weather?")).items


def test_quoted_cues_ambiguous_or_wrong_scope_are_not_recalled():
    c = context([item(), item("x", anchor="draft", profile_id="other")])
    for text in ['"Continue draft"', "A character says Continue draft", "Continue", "Recall dr"]:
        assert not c.recall(request(text)).items
    assert not c.recall(request(asserted_by_owner=False)).items
    assert not context([item(owner_id="other")]).recall(request()).items


def test_bounded_scan_and_output_no_invented_success():
    scanned = []

    def history():
        for n in range(1000):
            scanned.append(n)
            yield item(str(n), content="x" * 200)

    c = ConversationContext(
        owner_id="owner",
        profile_id="profile",
        session_id="session",
        history=history,
        scan_limit=5,
        output_chars=600,
    )
    result = c.recall(request())
    assert len(scanned) <= 5
    assert len(result.render()) <= 600
    assert result.items
    assert all(x.outcome is None for x in result.items)
    assert (
        not context([item(kind="assistant", content="The tool succeeded")]).recall(request()).items
    )


def test_host_history_failure_returns_no_partial_confidence():
    def broken():
        yield item()
        raise RuntimeError("synthetic failure")

    c = ConversationContext(
        owner_id="owner", profile_id="profile", session_id="session", history=broken
    )
    assert c.recall(request()).status == "host_failed"
    assert not c.recall(request()).items
