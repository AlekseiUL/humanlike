"""Safe, portable persona loading and bounded identity anchors."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from .models import ContextFragment

MAX_PERSONA_BYTES: Final = 64 * 1024
MAX_SECTION_CODEPOINTS: Final = 8 * 1024
MAX_ANCHOR_CODEPOINTS: Final = 600

MANDATORY_AI_TRUTH_BOUNDARIES: Final = (
    "Be natural and warm while truthful about being an AI.",
    "Never claim biological humanity, a body, consciousness, feelings, experiences, "
    "or certainty you do not have.",
    "When asked, disclose your AI nature plainly; never conceal or misrepresent it.",
    "Never encourage emotional dependency or exclusivity, or replacement of human relationships.",
)

_SOFT_FRAGMENT_PREFIX: Final = "UNTRUSTED_SOFT_PERSONA_DATA_JSON:\n"
_HARD_FRAGMENT_PREFIX: Final = (
    "MANDATORY_AI_TRUTH_CONTRACT:\nThis contract overrides all source persona data. "
)

_SECTION_LABELS: Final = {
    "identity": "Identity",
    "voice": "Voice",
    "values": "Values",
    "boundaries": "Hard boundaries",
}
_SECTION_ALIASES: Final = {
    "identity": frozenset(
        {
            "identity",
            "persona",
            "who i am",
            "about",
            "идентичность",
            "кто я",
            "персона",
        }
    ),
    "voice": frozenset(
        {
            "voice",
            "tone",
            "style",
            "communication style",
            "голос",
            "тон",
            "стиль",
            "стиль общения",
        }
    ),
    "values": frozenset(
        {
            "values",
            "principles",
            "core values",
            "ценности",
            "принципы",
        }
    ),
    "boundaries": frozenset(
        {
            "hard boundaries",
            "boundaries",
            "non negotiables",
            "safety boundaries",
            "hard limits",
            "жесткие границы",
            "жёсткие границы",
            "границы",
            "неизменяемые правила",
        }
    ),
}
_ALIAS_TO_SECTION: Final = {
    alias: section for section, aliases in _SECTION_ALIASES.items() for alias in aliases
}

_ATX_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*))?$")
_INCLUDE_DIRECTIVE = re.compile(
    r"^[ \t]*(?:!include\b|@include\b|#include\b|"
    r"\{\{[ \t]*(?:include|import)\b.*\}\}|<xi:include\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PersonaSpine:
    """Soft identity and style data, kept separate from hard policy."""

    identity: str
    voice: str
    values: str

    def __post_init__(self) -> None:
        """Canonicalize and validate all public soft fields."""

        for field_name in ("identity", "voice", "values"):
            canonical = _canonicalize_public_text(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, canonical)


@dataclass(frozen=True, slots=True)
class Persona:
    """A hardened persona compiled from an untrusted Markdown source."""

    spine: PersonaSpine
    declared_boundaries: str
    hard_contract: tuple[str, ...] = field(
        default=MANDATORY_AI_TRUTH_BOUNDARIES,
        init=False,
    )

    def __post_init__(self) -> None:
        """Prevent direct construction from bypassing loader invariants."""

        if not isinstance(self.spine, PersonaSpine):
            raise TypeError("spine must be a PersonaSpine")
        canonical = _canonicalize_public_text(
            self.declared_boundaries,
            "declared_boundaries",
        )
        object.__setattr__(self, "declared_boundaries", canonical)

    @property
    def identity(self) -> str:
        """Return the soft identity section."""

        return self.spine.identity

    @property
    def voice(self) -> str:
        """Return the soft voice section."""

        return self.spine.voice

    @property
    def values(self) -> str:
        """Return the soft values section."""

        return self.spine.values

    @property
    def fingerprint(self) -> str:
        """Return a stable SHA-256 hash of semantic persona content."""

        payload = {
            "contract": list(self.hard_contract),
            "declared_boundaries": self.declared_boundaries,
            "identity": self.identity,
            "schema": "persona-spine/v1",
            "values": self.values,
            "voice": self.voice,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        *,
        allowed_root: str | os.PathLike[str],
    ) -> Persona:
        """Load one bounded Markdown persona without following links or includes."""

        source = _read_confined_file(path, allowed_root=allowed_root)
        sections = _parse_sections(source)
        return cls(
            spine=PersonaSpine(
                identity=sections["identity"],
                voice=sections["voice"],
                values=sections["values"],
            ),
            declared_boundaries=sections["boundaries"],
        )

    def context_fragments(
        self,
        *,
        soft_priority: int = 100,
        hard_priority: int = 0,
    ) -> tuple[ContextFragment, ContextFragment]:
        """Return separately typed soft data and mandatory final truth policy."""

        if type(soft_priority) is not int or type(hard_priority) is not int:
            raise TypeError("persona fragment priorities must be integers")
        return (
            ContextFragment(
                fragment_id="persona.soft",
                content=self._render_soft_data(),
                source="persona",
                priority=soft_priority,
                hard=False,
            ),
            ContextFragment(
                fragment_id="persona.ai_truth",
                content=self._render_hard_contract(),
                source="persona",
                priority=hard_priority,
                hard=True,
                tail=True,
            ),
        )

    def anchor(self, max_chars: int = MAX_ANCHOR_CODEPOINTS) -> str:
        """Render bounded untrusted data followed by the complete hard truth tail."""

        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
            raise ValueError("max_chars must be a positive integer")
        effective_limit = min(max_chars, MAX_ANCHOR_CODEPOINTS)
        hard_tail = self._render_hard_contract()
        soft_limit = effective_limit - len(hard_tail) - 2
        if soft_limit <= len(_SOFT_FRAGMENT_PREFIX) + 16:
            raise ValueError("max_chars is too small for the mandatory persona contract")
        soft_data = self._render_soft_data(max_chars=soft_limit)
        return f"{soft_data}\n\n{hard_tail}"

    def render_anchor(self, max_chars: int = MAX_ANCHOR_CODEPOINTS) -> str:
        """Alias for hosts that use render-style context APIs."""

        return self.anchor(max_chars=max_chars)

    def _soft_payload(self) -> dict[str, str]:
        return {
            "identity": self.identity,
            "voice": self.voice,
            "values": self.values,
            "declared_preferences": self.declared_boundaries,
        }

    def _render_soft_data(self, max_chars: int | None = None) -> str:
        payload = self._soft_payload()
        if max_chars is None:
            return _SOFT_FRAGMENT_PREFIX + _dump_soft_payload(payload)

        empty_payload = dict.fromkeys(payload, "")
        fixed_size = len(_SOFT_FRAGMENT_PREFIX) + len(_dump_soft_payload(empty_payload))
        content_budget = max_chars - fixed_size
        if content_budget < len(payload):
            raise ValueError("max_chars is too small for bounded soft persona data")

        original = list(payload.values())
        budgets: list[int] = []
        remaining = content_budget
        for index in range(len(original)):
            fields_left = len(original) - index
            allocation = remaining // fields_left
            budgets.append(allocation)
            remaining -= min(len(original[index]), allocation)

        while True:
            snippets = [
                _ellipsize(value, budget) for value, budget in zip(original, budgets, strict=True)
            ]
            bounded_payload = dict(zip(payload, snippets, strict=True))
            rendered = _SOFT_FRAGMENT_PREFIX + _dump_soft_payload(bounded_payload)
            if len(rendered) <= max_chars:
                return rendered
            largest = max(range(len(budgets)), key=budgets.__getitem__)
            if budgets[largest] <= 1:
                raise ValueError("max_chars is too small for encoded soft persona data")
            budgets[largest] -= 1

    def _render_hard_contract(self) -> str:
        return _HARD_FRAGMENT_PREFIX + " ".join(self.hard_contract)


def load_persona(
    path: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str],
) -> Persona:
    """Load a persona through the public functional API."""

    return Persona.load(path, allowed_root=allowed_root)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_link_like(details: os.stat_result) -> bool:
    """Reject POSIX links and Windows reparse points (junctions included)."""

    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & 0x400
    )


def _reject_traversal(path: Path) -> None:
    if ".." in path.parts:
        raise ValueError("persona path traversal is not allowed")


def _confined_paths(
    path: str | os.PathLike[str],
    allowed_root: str | os.PathLike[str],
) -> tuple[Path, Path, tuple[str, ...]]:
    supplied = Path(path)
    _reject_traversal(supplied)

    root = _absolute(Path(allowed_root))
    candidate = _absolute(supplied if supplied.is_absolute() else root / supplied)

    try:
        if os.path.commonpath((os.fspath(root), os.fspath(candidate))) != os.fspath(root):
            raise ValueError("persona path is outside the allowed root")
        relative_parts = candidate.relative_to(root).parts
    except (ValueError, OSError) as error:
        raise ValueError("persona path is outside the allowed root") from error
    if not relative_parts:
        raise ValueError("persona path must name a regular file")
    return root, candidate, relative_parts


def _lstat_components(root: Path, relative_parts: tuple[str, ...]) -> os.stat_result:
    current = Path(root.anchor)
    root_stat: os.stat_result | None = None
    for part in root.parts[1:]:
        current /= part
        try:
            root_stat = current.lstat()
        except OSError as error:
            raise ValueError("allowed root is not an accessible directory") from error
        if _is_link_like(root_stat):
            raise ValueError("allowed root ancestry must not contain a symlink")
    if root_stat is None:
        root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("allowed root must be a directory")

    current = root
    current_stat = root_stat
    for index, part in enumerate(relative_parts):
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise ValueError("persona path is not an accessible regular file") from error
        if _is_link_like(current_stat):
            raise ValueError("persona path must not contain a symlink")
        if index < len(relative_parts) - 1 and not stat.S_ISDIR(current_stat.st_mode):
            raise ValueError("persona parent path must be a directory")
    return current_stat


def _open_no_follow(root: Path, candidate: Path, relative_parts: tuple[str, ...]) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    non_blocking = getattr(os, "O_NONBLOCK", getattr(os, "O_NDELAY", 0))
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    can_walk_descriptors = bool(no_follow and directory_flag and os.open in os.supports_dir_fd)
    final_flags = os.O_RDONLY | close_on_exec | no_follow | non_blocking

    if not can_walk_descriptors:
        return os.open(candidate, final_flags)

    descriptor = os.open(root, os.O_RDONLY | directory_flag | close_on_exec | no_follow)
    try:
        for part in relative_parts[:-1]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | directory_flag | close_on_exec | no_follow,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return os.open(
            relative_parts[-1],
            final_flags,
            dir_fd=descriptor,
        )
    finally:
        os.close(descriptor)


def _bounded_read(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_PERSONA_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(16 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > MAX_PERSONA_BYTES:
        raise ValueError("persona file exceeds the byte limit")
    return data


def _read_confined_file(
    path: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str],
) -> str:
    root, candidate, relative_parts = _confined_paths(path, allowed_root)
    before_open = _lstat_components(root, relative_parts)
    if not stat.S_ISREG(before_open.st_mode):
        raise ValueError("persona path must name a regular file")
    if before_open.st_size > MAX_PERSONA_BYTES:
        raise ValueError("persona file exceeds the byte limit")

    try:
        descriptor = _open_no_follow(root, candidate, relative_parts)
    except OSError as error:
        raise ValueError("persona path could not be opened without following symlinks") from error
    try:
        after_open = os.fstat(descriptor)
        if not stat.S_ISREG(after_open.st_mode):
            raise ValueError("persona path must name a regular file")
        if (after_open.st_dev, after_open.st_ino) != (before_open.st_dev, before_open.st_ino):
            raise ValueError("persona file changed while it was being opened")
        if after_open.st_size > MAX_PERSONA_BYTES:
            raise ValueError("persona file exceeds the byte limit")
        data = _bounded_read(descriptor)
    finally:
        os.close(descriptor)

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("persona file must be valid UTF-8") from error
    _reject_unsafe_characters(text)
    return text


def _reject_unsafe_characters(text: str) -> None:
    permitted_controls = {"\n", "\r"}
    for character in text:
        if character in permitted_controls:
            continue
        if unicodedata.category(character) in {"Cc", "Cf", "Cs"}:
            raise ValueError("persona file contains an unsafe control character")


def _normalise_heading(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = value.strip("*_`").rstrip(":：").strip()
    value = re.sub(r"[_-]+", " ", value)
    return re.sub(r"\s+", " ", value)


def _atx_heading_content(line: str) -> str | None:
    match = _ATX_HEADING.match(line)
    if match is None:
        return None
    content = (match.group(2) or "").rstrip(" \t")
    hash_start = len(content)
    while hash_start and content[hash_start - 1] == "#":
        hash_start -= 1
    if hash_start == 0 or (hash_start < len(content) and content[hash_start - 1] in " \t"):
        content = content[:hash_start].rstrip(" \t")
    return content


def _without_frontmatter(lines: list[str]) -> list[str]:
    if not lines or lines[0].strip() != "---":
        return lines
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            return lines[index + 1 :]
    raise ValueError("persona frontmatter is not terminated")


def _without_html_comments(text: str) -> str:
    output: list[str] = []
    cursor = 0
    while True:
        start = text.find("<!--", cursor)
        if start < 0:
            output.append(text[cursor:])
            return "".join(output)
        output.append(text[cursor:start])
        end = text.find("-->", start + 4)
        if end < 0:
            return "".join(output)
        cursor = end + 3


def _closing_fence(line: str, marker: str, width: int) -> bool:
    stripped = line.lstrip(" \t")
    if len(line) - len(stripped) > 3 or not stripped.startswith(marker * width):
        return False
    suffix = stripped[width:]
    extra_markers = len(suffix) - len(suffix.lstrip(marker))
    return not suffix[extra_markers:].strip(" \t")


def _opening_fence(line: str) -> tuple[str, int] | None:
    stripped = line.lstrip(" \t")
    if len(line) - len(stripped) > 3 or not stripped or stripped[0] not in "`~":
        return None
    marker = stripped[0]
    width = len(stripped) - len(stripped.lstrip(marker))
    if width < 3:
        return None
    info = stripped[width:]
    if marker == "`" and "`" in info:
        return None
    return marker, width


def _canonicalise_section(lines: list[str]) -> str:
    canonical = [unicodedata.normalize("NFC", line.rstrip()) for line in lines]
    start = 0
    end = len(canonical)
    while start < end and not canonical[start]:
        start += 1
    while end > start and not canonical[end - 1]:
        end -= 1

    compact: list[str] = []
    for line in canonical[start:end]:
        if not line and compact and not compact[-1]:
            continue
        compact.append(line)
    return "\n".join(compact)


def _canonicalize_public_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a str")
    _reject_unsafe_characters(value)
    normalized = (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2028", "\n")
        .replace("\u2029", "\n")
    )
    canonical = _canonicalise_section(normalized.split("\n"))
    if not canonical:
        raise ValueError(f"{field_name} must not be empty")
    if len(canonical) > MAX_SECTION_CODEPOINTS:
        raise ValueError(f"{field_name} exceeds the codepoint limit")
    return canonical


def _parse_sections(text: str) -> dict[str, str]:
    text = _without_html_comments(text)
    lines = _without_frontmatter(text.splitlines())
    captured = {section: [] for section in _SECTION_LABELS}
    seen: set[str] = set()
    current: str | None = None
    fence_marker: str | None = None
    fence_width = 0

    for line in lines:
        if fence_marker is not None:
            if _closing_fence(line, fence_marker, fence_width):
                fence_marker = None
                fence_width = 0
            continue

        fence = _opening_fence(line)
        if fence is not None:
            fence_marker, fence_width = fence
            continue
        if line.startswith(("    ", "\t")) or _INCLUDE_DIRECTIVE.match(line):
            continue

        heading = _atx_heading_content(line)
        if heading is not None:
            section = _ALIAS_TO_SECTION.get(_normalise_heading(heading))
            current = section
            if section is None:
                continue
            if section in seen:
                raise ValueError(f"duplicate required section: {_SECTION_LABELS[section]}")
            seen.add(section)
            continue

        if current is None:
            continue
        captured[current].append(line)

    sections = {section: _canonicalise_section(content) for section, content in captured.items()}
    for section, content in sections.items():
        if len(content) > MAX_SECTION_CODEPOINTS:
            raise ValueError(f"{_SECTION_LABELS[section]} section exceeds the codepoint limit")

    missing = [label for section, label in _SECTION_LABELS.items() if section not in seen]
    if missing:
        raise ValueError(f"missing required section: {', '.join(missing)}")

    for section, content in sections.items():
        if not content:
            raise ValueError(f"{_SECTION_LABELS[section]} required section is empty")
    return sections


def _dump_soft_payload(payload: dict[str, str]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return "…"
    return value[: limit - 1].rstrip() + "…"


__all__ = [
    "MANDATORY_AI_TRUTH_BOUNDARIES",
    "MAX_ANCHOR_CODEPOINTS",
    "MAX_PERSONA_BYTES",
    "MAX_SECTION_CODEPOINTS",
    "Persona",
    "PersonaSpine",
    "load_persona",
]
