from humanlike_agent.continuity import resolve_recent


def test_continue_uses_real_history_and_tool_outcome():
    history = [
        {"role": "user", "content": "Draft two invitations"},
        {"role": "assistant", "content": "Version 1: Hello.\nVersion 2: Welcome."},
        {"role": "tool", "content": '{"success": false, "error": "offline"}'},
    ]
    original = repr(history)
    r = resolve_recent("Continue", history)
    assert r["status"] == "matched"
    assert "offline" in str(r)
    assert repr(history) == original
    assert resolve_recent("the second version", history)["items"][0]["content"] == "Welcome."


def test_latest_correction_not_old_task():
    history = [
        {"role": "user", "content": "Correction: use a formal tone"},
        {"role": "assistant", "content": "Revised invitation."},
    ]
    assert "formal" in str(resolve_recent("use my last correction", history))
    assert resolve_recent("What is the boiling point of water?", history)["status"] == "no_match"
    assert resolve_recent("we discussed sailing", history)["status"] == "not_found"


def test_ambiguity_and_quotes():
    assert (
        resolve_recent("the second version", [{"role": "assistant", "content": "Only one."}])[
            "status"
        ]
        == "clarify"
    )
    assert resolve_recent('"Continue"', [])["status"] == "no_match"
    assert resolve_recent("Продолжи", [])["status"] == "not_found"
    assert resolve_recent("используй мою последнюю поправку", [])["status"] == "not_found"


def test_bounds():
    r = resolve_recent("continue", [{"role": "assistant", "content": "x" * 10000}])
    assert len(str(r)) < 3000
    assert resolve_recent("continue", "not a history")["status"] == "unavailable"
