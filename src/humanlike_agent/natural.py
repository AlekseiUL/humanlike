"""Small, closed RU/EN vocabulary. Parsing is a proposal, never authorization.

Only reply length (general / learning) is extracted deterministically. Unknown
wording is not guessed; use help or a human clarification. No model or network.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Request:
    action: str = "none"
    key: str = "reply_length"
    value: str = ""
    domain: str = "general"


CONTROLS = {
    "status": ("status", "статус"),
    "help": ("help", "помощь"),
    "enable": ("enable memory", "включи память"),
    "consent": ("i agree to local memory", "согласен на локальную память"),
    "confirm": ("confirm", "подтверждаю"),
    "cancel": ("cancel", "отмена"),
    "inspect": (
        "what do you remember about me",
        "what do you remember",
        "что ты обо мне помнишь",
        "что ты помнишь",
    ),
    "inspect_next": ("next memory page", "следующая страница памяти"),
    "why": ("why did you use that", "почему ты это использовал"),
    "forget": ("forget that", "забудь это"),
    "disable": ("pause memory", "disable memory", "pause", "отключи память", "приостанови память"),
    "no_save": ("do not save this session", "не сохраняй эту сессию"),
    "no_recall": ("do not recall this session", "не вспоминай в этой сессии"),
    "resume": ("resume this session", "возобнови эту сессию"),
}
PREFERENCES = {
    ("short", "general"): (
        "usually keep replies short",
        "i usually prefer short replies",
        "i prefer short replies",
        "я предпочитаю короткие ответы",
        "обычно отвечай кратко",
        "обычно предпочитаю короткие ответы",
    ),
    ("detailed", "general"): (
        "usually give detailed replies",
        "i usually prefer detailed replies",
        "i prefer detailed replies",
        "я предпочитаю подробные ответы",
        "обычно отвечай подробно",
    ),
    ("detailed", "learning"): (
        "explain learning topics in detail",
        "объясняй учебные темы подробно",
    ),
}


def parse_request(text: str) -> Request:
    """Full-match only: quotes, mixed commands and temporary requests never save."""
    if not isinstance(text, str) or len(text) > 512 or any(c in text for c in "\n\r\x00"):
        return Request()
    normalized = text.strip().casefold().rstrip(".!?").strip()
    # One optional leading politeness token, not arbitrary filler deletion.
    for prefix in ("please, ", "please ", "пожалуйста, ", "пожалуйста "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    for action, phrases in CONTROLS.items():
        if normalized in phrases:
            return Request(action)
    for domain, phrases in {
        "general": ("forget general reply length", "забудь длину общих ответов"),
        "learning": ("forget learning reply length", "забудь длину учебных ответов"),
    }.items():
        if normalized in phrases:
            return Request("forget", domain=domain, value="scoped")
    action = "remember"
    explicit = False
    for prefix, verb in (
        ("correct that: ", "correct"),
        ("исправь это: ", "correct"),
        ("remember that ", "remember"),
        ("remember: ", "remember"),
        ("запомни: ", "remember"),
        ("запомни, ", "remember"),
    ):
        if normalized.startswith(prefix):
            normalized, action = normalized[len(prefix) :], verb
            explicit = True
            break
    for (value, domain), phrases in PREFERENCES.items():
        if normalized in phrases:
            return Request(action, value=value, domain=domain)
    return Request("clarify" if explicit else "none")
