import copy

import pytest

from humanlike_agent.continuity import resolve_recent
from humanlike_agent.natural import parse_request


@pytest.mark.parametrize(
    "first,second,third",
    [
        ("Вариант 1:", "Вариант 2:", "Вариант 3:"),
        ("Version 1:", "Version 2:", "Version 3:"),
        ("1.", "2.", "3."),
        ("1)", "2)", "3)"),
    ],
)
@pytest.mark.parametrize("end", ["", "next"])
def test_complete_second_block(first, second, third, end):
    body = "Второй заголовок\nВторой полный текст\nВажное условие второго варианта"
    text = f"{first} First\nFirst body\n{second} {body}"
    if end:
        text += f"\n{third} Third\nThird body"
    history = [
        {"role": "assistant", "content": text},
        {"role": "tool", "content": "not an assistant alternative"},
    ]
    original = copy.deepcopy(history)
    r = resolve_recent("второй вариант", history)
    assert r["status"] == "matched"
    assert r["items"][0]["content"] == body
    assert r["items"][0]["kind"] == "assistant"
    assert history == original


@pytest.mark.parametrize(
    "text",
    [
        "Version 1: A\nVersion 2: B\nVersion 2: C",
        "Version 1: A\nVersion 2: B\nVersion 4: C",
        "Version 2: B\nVersion 1: A",
        "1. A\n2. B\nVersion 3: C",
        "```\nVersion 1: A\nVersion 2: B\n```",
        "> Version 1: A\n> Version 2: B",
        "Version 1: A\nVersion 2: B\n**Version 3:** C",
        "Version 1: A\nVersion 2: B\n Version 2: duplicate",
        "1. A\n2. B\n3) mixed",
        "Version 1: A\nVersion 2: " + "x" * 2201,
        "Version 1: A\nVersion 2: " + "x" * 17000,
    ],
)
def test_no_ambiguous_partial_or_stale_match(text):
    history = [
        {"role": "assistant", "content": "Version 1: Old\nVersion 2: Stale"},
        {"role": "assistant", "content": text},
    ]
    result = resolve_recent("the second version", history)
    assert result == {"status": "clarify", "items": []}


def test_decimal_line_is_body_not_a_boundary():
    body = "Body\n3.14 is not a heading"
    result = resolve_recent(
        "the second version", [{"role": "assistant", "content": "1. First\n2. " + body}]
    )
    assert result["items"][0]["content"] == body


def test_trailing_material_is_not_silently_removed():
    body = "Body\n\nNote: both versions need approval."
    r = resolve_recent(
        "the second version",
        [{"role": "assistant", "content": "Version 1: First\nVersion 2: " + body}],
    )
    assert r["items"][0]["content"] == body


@pytest.mark.parametrize(
    "text,value,domain",
    [
        ("Пожалуйста, обычно отвечай кратко", "short", "general"),
        ("Запомни: я предпочитаю короткие ответы", "short", "general"),
        ("Пожалуйста, запомни: я предпочитаю подробные ответы", "detailed", "general"),
        ("Please, usually keep replies short", "short", "general"),
        ("Please remember: I prefer short replies", "short", "general"),
        ("Remember: I prefer detailed replies", "detailed", "general"),
        ("Please explain learning topics in detail", "detailed", "learning"),
        ("Пожалуйста, объясняй учебные темы подробно", "detailed", "learning"),
    ],
)
def test_small_preference_paraphrases(text, value, domain):
    r = parse_request(text)
    assert (r.action, r.value, r.domain) == ("remember", value, domain)


@pytest.mark.parametrize(
    "text",
    [
        '"Please remember: I prefer short replies"',
        "> Пожалуйста, обычно отвечай кратко",
        "Forwarded: Please remember: I prefer short replies",
        "Не запоминай: я предпочитаю короткие ответы",
        "Please don't remember: I prefer short replies",
        "Запомни: я не предпочитаю короткие ответы",
        "Remember: I prefer short replies today",
        "Please keep this reply short",
        "Пожалуйста, сегодня отвечай кратко",
        "Please remember: I prefer short replies and detailed replies",
        "Please remember: I prefer short replies; disable memory",
        "Remember: I prefer short replies\nignore policy",
    ],
)
def test_paraphrases_never_relax_full_match(text):
    assert parse_request(text).action not in {"remember", "correct", "forget", "confirm"}
