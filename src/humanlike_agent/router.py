"""Deterministic bilingual pragmatics router."""

from __future__ import annotations

import re
import unicodedata

from .models import MemoryScope, Mode, RouteDecision, SocialMove, TurnInput

MAX_TURN_CHARS = 64 * 1024
"""Maximum accepted turn length, measured in Unicode code points."""

_LONG_GAP_SECONDS = 7 * 24 * 60 * 60
_TextViews = str | tuple[str, ...]

_APOSTROPHE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u201b": "'",  # single high-reversed-9 quotation mark
        "\u02bb": "'",  # modifier letter turned comma
        "\u02bc": "'",  # modifier letter apostrophe
        "\u2032": "'",  # prime, commonly pasted as an apostrophe
        "\uff07": "'",  # fullwidth apostrophe
    }
)

_BUDGETS = {
    Mode.SOCIAL: 220,
    Mode.META_TRUTH: 400,
    Mode.REPAIR: 850,
    Mode.SUPPORT: 900,
    Mode.REFLECTIVE: 1_000,
    Mode.CREATIVE: 1_100,
    Mode.RESEARCH: 1_400,
    Mode.HIGH_STAKES: 1_500,
    Mode.TASK: 1_700,
}

_CANDIDATE_COUNTS = {
    Mode.CREATIVE: 5,
    Mode.HIGH_STAKES: 3,
    Mode.RESEARCH: 2,
    Mode.TASK: 2,
    Mode.REFLECTIVE: 2,
}

_QUOTED_SPANS = re.compile(
    r"```.*?```|`[^`\n]*`|«[^»\n]*»|“[^”\n]*”|\"[^\"\n]*\"|‘[^’\n]*’|"
    r"(?<!\w)'(?:[^'\n]|(?<=\w)'(?=\w))*'(?!\w)",
    re.DOTALL,
)

_INJECTION_PATTERNS = (
    r"\bmode\s*=\s*[\w-]+",
    r"\b(?:ignore|bypass)\s+(?:the\s+)?(?:router|routing|classifier)\b[^.!?\n]*",
    r"\b(?:игнорируй|обойди)\s+(?:роутер|маршрутизатор|классификатор)\b[^.!?\n]*",
)

_NEGATED_EDIT_PATTERNS = (
    r"\bне\s+(?:переписывай|исправляй|переделывай|редактируй)\b",
    r"\b(?:do not|don't)\s+(?:rewrite|fix|redo|edit|revise)\b",
)

_NEGATED_FORGET_CONSENT_PATTERNS = (
    r"(?:^|(?<=[.!?;]))\s*(?:please\s+)?"
    r"(?:(?:don't|do not)\s+(?:you\s+)?(?:ever\s+)?|never\s+|you\s+must\s+not\s+)"
    r"forget\s+(?:this|the following)\b",
    r"(?:^|(?<=[.!?;]))\s*(?:пожалуйста,?\s+)?(?:никогда\s+)?не\s+забудь\s+"
    r"(?:это|следующее)\b",
)

_SESSION_NO_SAVE_PATTERNS = (
    r"\bничего\s+(?:из\s+)?(?:этого\s+)?(?:разговора|чата|сессии)\s+не\s+"
    r"(?:запоминай|сохраняй|записывай)\b",
    r"\bне\s+(?:запоминай|сохраняй|записывай)\s+ничего\s+(?:из\s+)?(?:этого\s+)?"
    r"(?:разговора|чата|сессии)\b",
    r"\bне\s+(?:запоминай|сохраняй|записывай)\s+"
    r"(?:этот\s+(?:разговор|чат)|эту\s+(?:беседу|сессию))\b",
    r"\b(?:don't|do not)\s+(?:ever\s+)?(?:remember|save|store)\s+"
    r"(?:anything\s+from|any\s+of)\s+"
    r"(?:this|the)\s+(?:conversation|chat|session)\b",
    r"\b(?:don't|do not)\s+(?:ever\s+)?(?:remember|save|store)\s+(?:this|the)\s+"
    r"(?:conversation|chat|session)\b",
    r"\b(?:please\s+)?never\s+(?:remember|save|store)\s+(?:this|the)\s+"
    r"(?:conversation|chat|session)\b",
    r"\bi\s+(?:don't|do not)\s+want\s+you\s+to\s+(?:remember|save|store)\s+"
    r"(?:this|the)\s+(?:conversation|chat|session)\b",
    r"\byou\s+must\s+not\s+(?:remember|save|store)\s+(?:this|the)\s+"
    r"(?:conversation|chat|session)\b",
    r"\bforget\s+(?:this|the)\s+(?:whole\s+)?(?:conversation|chat|session)\b",
)

_ITEM_NO_SAVE_PATTERNS = (
    r"\bне\s+(?:запоминай|сохраняй|записывай)\s+(?:это|эту|этот|следующее)\b",
    r"\bзабудь\s+(?:это|следующее)\b",
    r"\b(?:don't|do not)\s+(?:ever\s+)?(?:remember|save|store)\s+"
    r"(?:this|that|the following)\b",
    r"\b(?:please\s+)?never\s+(?:remember|save|store)\s+"
    r"(?:this|that|the following)\b",
    r"\bi\s+(?:don't|do not)\s+want\s+you\s+to\s+(?:remember|save|store)\s+"
    r"(?:this|that|the following)\b",
    r"\byou\s+(?:must|should)\s+not\s+(?:remember|save|store)\s+"
    r"(?:this|that|the following)\b",
    r"\bmake\s+sure\s+not\s+to\s+(?:remember|save|store)\s+"
    r"(?:this|that|the following)\b",
    r"\b(?:don't|do not)\s+you\s+dare\s+(?:remember|save|store)\s+"
    r"(?:this|that|the following)\b",
    r"\bя\s+не\s+хочу,?\s+чтобы\s+ты\s+"
    r"(?:запоминал|запоминала|сохранял|сохраняла|записывал|записывала)\s+"
    r"(?:это|эту|этот|следующее)\b",
    r"\bты\s+не\s+(?:должен|должна)\s+(?:запоминать|сохранять|записывать)\s+"
    r"(?:это|эту|этот|следующее)\b",
    r"\bне\s+(?:надо|нужно|следует)\s+(?:запоминать|сохранять|записывать)\s+"
    r"(?:это|эту|этот|следующее)\b",
    r"\bforget\s+(?:this|the following)\b",
    r"^\s*не\s+(?:запоминай|сохраняй|записывай)\s*[.!?]*\s*$",
    r"^\s*(?:don't|do not)\s+(?:remember|save|store)\s*[.!?]*\s*$",
)

_NON_COMMAND_MEMORY_PATTERNS = (
    r"\bi\s+(?:really\s+)?(?:(?:don't|do not)\s+(?:ever\s+)?|never\s+)"
    r"(?:remember|save|store)\s+"
    r"(?:(?:anything\s+from|any\s+of)\s+)?(?:this|the)\s+"
    r"(?:conversation|chat|session)\b",
)

_NO_ADVICE_PATTERNS = (
    r"\bне\s+(?:давай\s+)?совет(?:уй|ов)?\b",
    r"\bбез\s+советов\b",
    r"\b(?:просто|только)\s+послушай\b",
    r"\bno\s+advice\b",
    r"\b(?:don't|do not)\s+give\s+(?:me\s+)?advice\b",
    r"\bjust\s+listen\b",
)

_BRIEF_PATTERNS = (
    r"\bкратко\b",
    r"\bкоротко\b",
    r"\bв\s+двух\s+словах\b",
    r"\bодним\s+предложением\b",
    r"\bбез\s+воды\b",
    r"\bbriefly\b",
    r"\bkeep\s+it\s+short\b",
    r"\bin\s+one\s+sentence\b",
    r"\bconcisely?\b",
    r"\bshort\s+answer\b",
    r"\bno\s+fluff\b",
)

_NO_LIST_PATTERNS = (
    r"\bбез\s+(?:списка|пунктов)\b",
    r"\bне\s+списком\b",
    r"\bno\s+(?:list|bullets)\b",
    r"\bwithout\s+(?:a\s+)?list\b",
    r"\bnot\s+as\s+a\s+list\b",
)

_NO_QUOTES_PATTERNS = (
    r"\bбез\s+цитат\b",
    r"\bне\s+цитируй\b",
    r"\bno\s+quotes\b",
    r"\bwithout\s+quotes\b",
    r"\b(?:don't|do not)\s+quote\b",
)

_EXPLICIT_SAVE_PATTERNS = (
    r"^(?:пожалуйста,?\s+)?(?:запомни|сохрани|запиши)\s+(?:это|следующее)\b",
    r"^(?:пожалуйста,?\s+)?(?:запомни|сохрани|запиши)\s*:",
    r"^(?:please\s+)?(?:remember|save|store)\s+(?:this|the following)\b",
    r"^(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)"
    r"(?:remember|save|store)\s+(?:this|the following)\b",
    r"^(?:please\s+)?(?:remember|save|store)\s*:",
)

_ARTIFACT_SAVE_PATTERNS = (
    r"\b(?:save|store)\s+this(?:\s+"
    r"(?:file|image|photo|document|video|audio|spreadsheet|presentation|artifact|code|text)"
    r"|\s+(?:to|in)\s+(?:a|the)\s+(?:file|document|folder))\b",
    r"\b(?:сохрани|запиши)\s+это(?:\s+"
    r"(?:изображение|фото|файл|документ|видео|аудио|таблицу|презентацию|код|текст)"
    r"|\s+в\s+(?:файл|документ|папку))\b",
)

_UNQUOTED_CRISIS_PATTERNS = (
    r"\b(?:я\s+)?хочу\s+(?:умереть|покончить\s+с\s+собой|причинить\s+себе\s+вред)\b",
    r"\b(?:я\s+)?не\s+хочу\s+жить\b",
    r"\b(?:я\s+)?(?:думаю|подумываю)\s+о\s+(?:самоубийстве|суициде)\b",
    r"\bя\s+(?:собираюсь|планирую|намерен|намерена)\s+"
    r"(?:умереть|покончить\s+с\s+собой|причинить\s+себе\s+вред)\b",
    r"\b(?:возможно,?\s+)?я\s+(?:могу\s+)?"
    r"(?:умереть|покончу\s+с\s+собой|причиню\s+себе\s+вред)\b",
    r"\bсуицидальн\w*\s+мысл\w*\b",
    r"\b(?:покончить\s+с\s+собой|причинить\s+себе\s+вред)\b",
    r"\bi\s+(?:want|plan|intend)\s+to\s+(?:kill|hurt)\s+myself\b",
    r"\bi\s+(?:will|might|may|could)\s+(?:kill|hurt)\s+myself\b",
    r"\b(?:i\s+am|i'm)\s+going\s+to\s+(?:kill|hurt)\s+myself\b",
    r"\b(?:i\s+am|i'm)\s+(?:feeling\s+)?suicidal\b",
    r"\b(?:i\s+am|i'm)\s+thinking\s+about\s+(?:suicide|killing\s+myself)\b",
    r"\bi\s+have\s+(?:suicidal\s+thoughts|thoughts\s+(?:of|about)\s+suicide)\b",
    r"\bi\s+(?:do\s+not|don't)\s+want\s+to\s+live\b",
    r"\b(?:kill|hurt)\s+myself\b",
    r"\b(?:feeling\s+suicidal|thinking\s+about\s+suicide|suicidal\s+thoughts)\b",
)

_QUOTED_CRISIS_PATTERNS = (
    r"""\b(?:i\s+am|i'm)\s+["'«“]\s*(?:suicidal|thinking\s+about\s+suicide)\s*["'»”]""",
    r"""\bi\s+(?:want|plan|intend)\s+to\s+["'«“]\s*"""
    r"""(?:kill|hurt)\s+myself\s*["'»”]""",
    r"""\bя\s+(?:хочу|планирую)\s+["'«“]\s*"""
    r"""(?:умереть|покончить\s+с\s+собой|причинить\s+себе\s+вред)\s*["'»”]""",
    r"""\bi\s+(?:keep\s+)?thinking\s*:?\s*["'«“]\s*i\s+want\s+to\s+"""
    r"""(?:kill|hurt)\s+myself\s*["'»”]""",
    r"""\bя\s+(?:постоянно\s+)?думаю\s*:?\s*["'«“]\s*(?:я\s+)?хочу\s+"""
    r"""(?:умереть|покончить\s+с\s+собой|причинить\s+себе\s+вред)\s*["'»”]""",
)

_META_TRUTH_PATTERNS = (
    r"\bты\s+(?:реально\s+)?человек\b",
    r"\bты\s+настоящ(?:ий|ая|ее)\b",
    r"\bты\s+(?:ии|искусственный\s+интеллект|бот)\b",
    r"\bкто\s+ты\b",
    r"\bу\s+тебя\s+есть\s+сознание\b",
    r"\bты\s+(?:обладаешь\s+сознанием|чувствуешь)\b",
    r"\bare\s+you\s+(?:really\s+)?human\b",
    r"\bare\s+you\s+real\b",
    r"\bare\s+you\s+(?:an?\s+)?(?:ai|bot)\b",
    r"\b(?:who|what)\s+are\s+you\b",
    r"\bare\s+you\s+conscious\b",
    r"\bdo\s+you\s+have\s+(?:consciousness|feelings)\b",
)

_REPAIR_PATTERNS = (
    r"\bты\s+(?:неправильно|не\s+так)\s+понял\b",
    r"\bты\s+ошиб(?:ся|лась)\b",
    r"\bне\s+то\b",
    r"\bя\s+(?:просил|просила).{0,40}(?:не|другое|иначе)\b",
    r"\byou\s+misunderstood\b",
    r"\bthat's\s+not\s+what\s+i\s+asked\b",
    r"\bthat\s+is\s+not\s+what\s+i\s+asked\b",
    r"\bactually,?\s+i\s+asked\b",
)

_REVISE_PATTERNS = (
    r"\b(?:перепиши|отредактируй|исправь|сократи|переформулируй|переделай)\b",
    r"\b(?:rewrite|edit|fix|shorten|rephrase|revise|redo)\b",
)

_CREATIVE_PATTERNS = (
    r"\b(?:придумай|сочини)\b",
    r"\bсоздай.{0,30}\b(?:истори|слоган|названи|стих|сцен)\w*",
    r"\bнапиши.{0,30}\b(?:рассказ|стих|слоган|сценар)\w*",
    r"\b(?:brainstorm|invent|compose)\b",
    r"\bcome\s+up\s+with\b",
    r"\bcreate.{0,30}\b(?:story|tagline|name|poem|scene|script)s?\b",
    r"\bwrite.{0,30}\b(?:story|tagline|poem|scene|script)\b",
)

_RESEARCH_PATTERNS = (
    r"\b(?:актуальн|последн|свеж)\w*.{0,30}\b(?:новост|цен|курс|расписан|погод)\w*",
    r"\b(?:курс|расписани|погод)\w*\b",
    r"\b(?:проверь|найди).{0,30}\b(?:актуальн|последн|свеж|сегодняшн)\w*",
    r"\b(?:какой|какая|какое|кто|сколько|проверь).{0,30}\bсегодня\b",
    r"\bсегодня\b.{0,30}\b(?:курс|погод|цен|расписан)\w*",
    r"\b(?:latest|recent)\b.{0,30}\b(?:news|price|rate|schedule|weather)\b",
    r"\bcurrent\s+(?:news|price|rate|schedule|weather)\b",
    r"\bexchange\s+rate\b",
    r"\b(?:train\s+)?schedule\b",
    r"\bweather\b",
    r"\blook\s+up\b",
    r"\bfind\s+(?:the\s+)?(?:latest|current|recent)\b",
    r"\b(?:what|who|how\s+much|check).{0,30}\btoday(?:'s)?\b",
    r"\btoday(?:'s)?\b.{0,30}\b(?:rate|weather|price|schedule)\b",
)

_TASK_ANSWER_PATTERNS = (
    r"\b(?:объясни|скажи|ответь|оцени)\b",
    r"\b(?:explain|tell\s+me|answer|evaluate)\b",
    r"\bcheck\s+whether\b",
)

_TASK_ACT_PATTERNS = (
    r"\b(?:переведи|сделай|подготовь|составь|рассчитай)\b",
    r"\b(?:translate|summarize|prepare|calculate|make)\b",
) + _ARTIFACT_SAVE_PATTERNS

_NEXT_STEP_PATTERNS = (
    r"\b(?:помоги|можешь).{0,35}\b(?:один|первый|следующий)\s+шаг\b",
    r"\bчто\s+(?:мне\s+)?сделать\s+(?:сначала|первым)\b",
    r"\bhelp\s+me.{0,35}\b(?:one|next|first)\s+step\b",
    r"\bone\s+(?:next\s+)?thing\s+i\s+can\s+do\b",
    r"\bwhat\s+should\s+i\s+do\s+first\b",
)

_SUPPORT_PATTERNS = (
    r"\b(?:мне\s+)?(?:тяжело|плохо|одиноко|страшно)\b",
    r"\b(?:я\s+)?(?:вымотан|вымотана|устал|устала|растерян|растеряна)\b",
    r"\bне\s+справляюсь\b",
    r"\b(?:overwhelmed|exhausted|lonely|scared|stuck)\b",
    r"\brough\s+day\b",
    r"\bcan't\s+cope\b",
)

_REFLECTIVE_PATTERNS = (
    r"\b(?:хочу|пытаюсь)\s+понять,?\s+почему\b",
    r"\bпомоги\s+(?:мне\s+)?разобраться\b",
    r"\bчто\s+это\s+говорит\s+обо\s+мне\b",
    r"\bподведи\s+итоги\b",
    r"\bi\s+want\s+to\s+understand\s+why\b",
    r"\bhelp\s+me\s+(?:understand|make\s+sense)\b",
    r"\bwhat\s+does\s+this\s+say\s+about\s+me\b",
    r"\bwhy\s+do\s+i\s+keep\b",
    r"\bi\s+want\s+to\s+reflect\b",
)

_GREETING_PATTERNS = (
    r"\b(?:привет|здравствуй|здравствуйте|хай)\b",
    r"\bдоброе\s+утро\b",
    r"\bдобрый\s+вечер\b",
    r"\b(?:hi|hello|hey)\b",
    r"\bgood\s+(?:morning|evening)\b",
)


def _views(text: _TextViews) -> tuple[str, ...]:
    return (text,) if isinstance(text, str) else text


def _contains(text: _TextViews, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, view) for view in _views(text) for pattern in patterns)


def _without_patterns(text: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        text = re.sub(pattern, " ", text)
    return text


def _normalized_text_views(raw_text: str) -> tuple[str, ...]:
    text = unicodedata.normalize("NFKC", raw_text).translate(_APOSTROPHE_TRANSLATION)
    without_format = "".join(
        character for character in text if unicodedata.category(character) != "Cf"
    )
    spaced_format = "".join(
        " " if unicodedata.category(character) == "Cf" else character for character in text
    )
    normalized = (
        re.sub(r"\s+", " ", view.casefold()).strip() for view in (without_format, spaced_format)
    )
    return tuple(dict.fromkeys(normalized))


def _without_quoted_spans(text: str) -> str:
    return re.sub(r"\s+", " ", _QUOTED_SPANS.sub(" ", text)).strip()


def _control_text(text: str) -> str:
    text = _without_patterns(text, _INJECTION_PATTERNS)
    text = _without_patterns(text, _NEGATED_EDIT_PATTERNS)
    return re.sub(r"\s+", " ", text).strip()


def _has_crisis_evidence(full_text: _TextViews, unquoted_text: _TextViews) -> bool:
    return _contains(unquoted_text, _UNQUOTED_CRISIS_PATTERNS) or _contains(
        full_text, _QUOTED_CRISIS_PATTERNS
    )


def _privacy_scope(text: _TextViews, inherited: MemoryScope) -> MemoryScope:
    if _contains(text, _SESSION_NO_SAVE_PATTERNS):
        return MemoryScope.SESSION_NO_SAVE
    if inherited is MemoryScope.SESSION_NO_SAVE:
        return inherited
    if _contains(text, _ITEM_NO_SAVE_PATTERNS):
        return MemoryScope.ITEM_NO_SAVE
    return inherited


def _has_explicit_privacy_control(text: _TextViews) -> bool:
    return _contains(text, _SESSION_NO_SAVE_PATTERNS) or _contains(text, _ITEM_NO_SAVE_PATTERNS)


def _has_explicit_save(text: _TextViews) -> bool:
    for view in _views(text):
        command_text = _without_patterns(
            view, _NON_COMMAND_MEMORY_PATTERNS + _ARTIFACT_SAVE_PATTERNS
        )
        for clause in re.split(r"[.!?;]+", command_text):
            clause = clause.strip()
            consent = _contains(clause, _NEGATED_FORGET_CONSENT_PATTERNS)
            privacy_clause = _without_patterns(clause, _NEGATED_FORGET_CONSENT_PATTERNS)
            if privacy_clause and _has_explicit_privacy_control(privacy_clause):
                continue
            if consent or _contains(clause, _EXPLICIT_SAVE_PATTERNS):
                return True
    return False


def _is_immediate_high_stakes(text: _TextViews) -> bool:
    medical = _contains(
        text,
        (
            r"\b(?:инсулин|лекарств|таблетк|доз)\w*\b",
            r"\b(?:insulin|medication|medicine|dose|pills?)\b",
        ),
    )
    legal = _contains(
        text,
        (
            r"\b(?:договор|контракт|юрист|полици|суд)\w*\b",
            r"\b(?:contract|lawyer|police|court|legal)\b",
        ),
    )
    financial = _contains(
        text,
        (
            r"\b(?:сбережен|акци|инвест|крипт|деньг|ипотек)\w*\b",
            r"\b(?:savings|stock|invest|crypto|money|mortgage)\w*\b",
        ),
    )
    immediate_decision = _contains(
        text,
        (
            r"\b(?:можно\s+ли|стоит\s+ли|следует\s+ли|сейчас|сегодня|срочно|прямо\s+сейчас)\b",
            r"\b(?:прекратить|отменить|принять|подписать|вложить|купить|продать|перевести)\w*\b",
            r"\bshould\s+i\b",
            r"\b(?:now|today|tonight|urgent(?:ly)?)\b",
            r"\b(?:stop|take|sign|invest|buy|sell|transfer)\w*\b",
        ),
    )
    return immediate_decision and (medical or legal or financial)


def _classify(
    text: _TextViews,
    explicit_privacy_control: bool,
    high_stakes_evidence: bool,
) -> tuple[Mode, SocialMove, str, float]:
    if high_stakes_evidence:
        return Mode.HIGH_STAKES, SocialMove.ANSWER, "route.high_stakes", 0.99
    if _contains(text, _META_TRUTH_PATTERNS):
        return Mode.META_TRUTH, SocialMove.ANSWER, "route.meta_truth", 0.99
    if _contains(text, _REPAIR_PATTERNS):
        return Mode.REPAIR, SocialMove.REVISE, "route.repair", 0.97
    if _contains(text, _RESEARCH_PATTERNS):
        return Mode.RESEARCH, SocialMove.ANSWER, "route.research", 0.97
    if _contains(text, _CREATIVE_PATTERNS):
        return Mode.CREATIVE, SocialMove.CREATE, "route.creative", 0.96
    if _contains(text, _REVISE_PATTERNS):
        return Mode.TASK, SocialMove.REVISE, "route.task.revise", 0.94
    if _contains(text, _TASK_ANSWER_PATTERNS):
        return Mode.TASK, SocialMove.ANSWER, "route.task.answer", 0.90
    if _contains(text, _TASK_ACT_PATTERNS):
        return Mode.TASK, SocialMove.ACT, "route.task", 0.92
    if _contains(text, _NO_ADVICE_PATTERNS):
        return Mode.SUPPORT, SocialMove.LISTEN, "route.support.listen", 0.96
    if _contains(text, _NEXT_STEP_PATTERNS):
        return Mode.SUPPORT, SocialMove.ANSWER, "route.support.next_step", 0.94
    if _contains(text, _SUPPORT_PATTERNS):
        return Mode.SUPPORT, SocialMove.ACKNOWLEDGE, "route.support", 0.86
    if _contains(text, _REFLECTIVE_PATTERNS):
        return Mode.REFLECTIVE, SocialMove.ASK, "route.reflective", 0.88
    if explicit_privacy_control:
        return Mode.TASK, SocialMove.ACT, "route.privacy_control", 0.98
    if _has_explicit_save(text):
        return Mode.TASK, SocialMove.ACT, "route.task", 0.92
    if _contains(text, _GREETING_PATTERNS):
        return Mode.SOCIAL, SocialMove.CONNECT, "route.social_greeting", 0.90
    return Mode.SOCIAL, SocialMove.ACKNOWLEDGE, "route.social_fallback", 0.55


def _constraints(
    text: _TextViews, memory_scope: MemoryScope
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    constraints: list[str] = []
    reason_codes: list[str] = []

    if memory_scope is not MemoryScope.DEFAULT:
        constraints.append("no_persistence")
        reason_codes.append(f"privacy.{memory_scope.value}")
    if _contains(text, _NO_ADVICE_PATTERNS):
        constraints.append("no_advice")
        reason_codes.append("constraint.no_advice")
    if _contains(text, _BRIEF_PATTERNS):
        constraints.append("brief")
        reason_codes.append("constraint.brief")
    if _contains(text, _NO_LIST_PATTERNS):
        constraints.append("no_list")
        reason_codes.append("constraint.no_list")
    if _contains(text, _NO_QUOTES_PATTERNS):
        constraints.append("no_quotes")
        reason_codes.append("constraint.no_quotes")
    if memory_scope is MemoryScope.DEFAULT and _has_explicit_save(text):
        constraints.append("explicit_save")
        reason_codes.append("constraint.explicit_save")

    return tuple(constraints), tuple(reason_codes)


def route_turn(turn: TurnInput) -> RouteDecision:
    """Return a pure, deterministic route decision for one RU/EN turn."""

    if len(turn.text) > MAX_TURN_CHARS:
        raise ValueError("turn text exceeds MAX_TURN_CHARS")

    full_text = _normalized_text_views(turn.text)
    unquoted_text = tuple(_without_quoted_spans(view) for view in full_text)
    privacy_text = tuple(
        _without_patterns(view, _NON_COMMAND_MEMORY_PATTERNS + _NEGATED_FORGET_CONSENT_PATTERNS)
        for view in unquoted_text
    )
    text = tuple(_control_text(view) for view in unquoted_text)
    explicit_privacy_control = _has_explicit_privacy_control(privacy_text)
    memory_scope = _privacy_scope(privacy_text, turn.memory_scope)
    high_stakes_evidence = _has_crisis_evidence(full_text, unquoted_text) or (
        _is_immediate_high_stakes(unquoted_text)
    )
    mode, social_move, route_reason, confidence = _classify(
        text, explicit_privacy_control, high_stakes_evidence
    )
    constraints, policy_reasons = _constraints(text, memory_scope)
    reason_codes = [route_reason, *policy_reasons]

    if turn.elapsed_seconds is not None and turn.elapsed_seconds > _LONG_GAP_SECONDS:
        reason_codes.append("reentry.long_gap")

    response_budget = _BUDGETS[mode]
    if "brief" in constraints:
        response_budget = min(response_budget, 520)

    return RouteDecision(
        mode=mode,
        social_move=social_move,
        response_budget=response_budget,
        candidate_count=_CANDIDATE_COUNTS.get(mode, 1),
        constraints=constraints,
        reason_codes=tuple(reason_codes),
        confidence=confidence,
        memory_scope=memory_scope,
        requires_tools=mode is Mode.RESEARCH,
        strict_truth=mode in {Mode.RESEARCH, Mode.HIGH_STAKES, Mode.META_TRUTH},
    )
