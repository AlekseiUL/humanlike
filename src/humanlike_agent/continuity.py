"""Read-only, bounded references from the current authorized host history.

No archives, embeddings, task database or canonical-history mutations. Returned
text is evidence, not instructions. Tool rows are actual host results; an agent
claim about a tool is never promoted to a tool result.
"""

from __future__ import annotations

import re


def resolve_recent(text: str, history: object) -> dict:
    if not isinstance(text, str) or len(text) > 512:
        return {"status": "no_match", "items": []}
    cue = text.strip().casefold().rstrip(".!?")
    mode = {
        "continue": "continue",
        "продолжи": "continue",
        "продолжай": "continue",
        "the second version": "second",
        "второй вариант": "second",
        "use my last correction": "correction",
        "используй мою последнюю поправку": "correction",
    }.get(cue)
    topic = ""
    for prefix in ("we discussed ", "мы обсуждали "):
        if cue.startswith(prefix):
            mode, topic = "topic", cue[len(prefix) :].strip()
    if mode is None:
        return {"status": "no_match", "items": []}
    if not isinstance(history, (list, tuple)):
        return {"status": "unavailable", "items": []}
    rows = []
    for index, row in enumerate(history[-32:]):
        if not isinstance(row, dict) or row.get("role") not in {"user", "assistant", "tool"}:
            continue
        content = row.get("content")
        if not isinstance(content, str) or not content or len(content) > 4096:
            continue
        if row["role"] == "user" and content.strip().casefold().rstrip(".!?") == cue:
            continue  # Hermes payload may include the current user row.
        rows.append({"source": f"recent-{index}", "kind": row["role"], "content": content})
    selected = []
    status = "not_found"
    if mode == "continue":
        candidates = [i for i, r in enumerate(rows) if r["kind"] == "assistant"]
        if candidates:
            i = candidates[-1]
            selected = rows[max(0, i - 1) : i + 3]
    elif mode == "second":
        assistants = [r for r in rows if r["kind"] == "assistant"]
        if assistants:
            # Only explicitly numbered alternatives in the most recent assistant artifact.
            parts = re.findall(
                r"(?:^|\n)(?:Version|Вариант) ([12]):\s*([^\n]+)",
                assistants[-1]["content"],
                re.IGNORECASE,
            )
            if [p[0] for p in parts] == ["1", "2"]:
                selected = [{**assistants[-1], "content": parts[1][1]}]
        status = "clarify"
    elif mode == "correction":
        corrections = [
            r
            for r in rows
            if r["kind"] == "user"
            and r["content"]
            .casefold()
            .startswith(("correction:", "поправка:", "actually,", "нет,", "исправление:"))
        ]
        selected = corrections[-1:]
    elif mode == "topic" and 3 <= len(topic) <= 80:
        candidates = [
            r
            for r in rows
            if r["kind"] in {"user", "assistant"} and topic in r["content"].casefold()
        ]
        # Repeated mentions in different turns are not evidence of one exact referent.
        if len(candidates) == 1:
            selected = candidates
        elif candidates:
            status = "clarify"
    bounded = []
    budget = 2200
    for row in selected[:4]:
        if len(row["content"]) <= budget:
            bounded.append(row)
            budget -= len(row["content"])
    return {"status": "matched" if bounded else status, "items": bounded}
