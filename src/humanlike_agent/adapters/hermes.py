"""Thin adapter for the supported Hermes hook contract."""

from __future__ import annotations

import os
import re
import stat
import tomllib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Final

from ..memory import SQLiteMemoryLedger
from ..models import SessionRef, TurnInput, TurnOutcome
from ..persona import Persona
from ..router import MAX_TURN_CHARS
from ..runtime import HumanlikeRuntime, RuntimeConfig

HERMES_HOOKS: Final = (
    "pre_llm_call",
    "transform_llm_output",
    "post_llm_call",
    "on_session_finalize",
)
_MAX_RESPONSE_CHARS: Final = 1_048_576
_MAX_HOOK_CONTEXT_CHARS: Final = 9_999
_MAX_ACTIVE_SESSIONS: Final = 128
_MAX_CONFIG_BYTES: Final = 16 * 1024
_CONFIG_SCHEMA: Final = "humanlike-hermes/v1"
_CONFIG_FIELDS: Final = frozenset(
    {
        "schema",
        "profile_id",
        "persona_path",
        "memory_enabled",
        "acknowledge_host_context_persistence",
        "state_path",
        "normal_context_chars",
        "deep_context_chars",
    }
)
_IDENTITY_DECEPTION: Final = re.compile(
    r"\s*i\s+am\s+a\s+(human|biological\s+person)\s*[.!]?\s*",
    re.IGNORECASE,
)


def _host_string(payload: dict[str, Any], name: str, *, limit: int) -> str | None:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    return value


def _absolute_path(value: str | os.PathLike[str], field: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str):
        raise TypeError(f"{field} must be a text path")
    if "\x00" in raw:
        raise ValueError(f"{field} contains NUL")
    return Path(os.path.abspath(raw))


def _relative_profile_path(value: object, root: Path, field: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{field} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"{field} must stay within the profile root")
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{field} must stay within the profile root") from error
    return candidate


def _is_link_like(details: os.stat_result) -> bool:
    """Reject POSIX links and Windows reparse points (junctions included)."""

    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & 0x400
    )


def _validate_root(root: Path) -> None:
    current = Path(root.anchor)
    details: os.stat_result | None = None
    for part in root.parts[1:]:
        current /= part
        try:
            details = current.lstat()
        except OSError as error:
            raise ValueError("profile root is not accessible") from error
        if _is_link_like(details):
            raise ValueError("profile root ancestry must not contain symlinks")
    if details is None:
        details = root.lstat()
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError("profile root must be a directory")
    if os.name == "posix" and (
        details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) & 0o022
    ):
        raise ValueError("profile root permissions are unsafe")


def _secure_config_read(
    path: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str],
) -> tuple[Path, Path, bytes]:
    root = _absolute_path(allowed_root, "allowed_root")
    _validate_root(root)
    raw_path = os.fspath(path)
    if not isinstance(raw_path, str) or "\x00" in raw_path:
        raise ValueError("config path is invalid")
    lexical = Path(raw_path)
    if any(part == ".." for part in lexical.parts):
        raise ValueError("config path traversal is not allowed")
    candidate = _absolute_path(path, "config path") if lexical.is_absolute() else root / lexical
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("config path is outside the allowed root") from error
    if not relative.parts:
        raise ValueError("config path must name a regular file")

    current = root
    before: os.stat_result | None = None
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            before = current.lstat()
        except OSError as error:
            raise ValueError("config path is not accessible") from error
        if _is_link_like(before):
            raise ValueError("config path must not contain symlinks")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(before.st_mode):
            raise ValueError("config parent must be a directory")
    if before is None or not stat.S_ISREG(before.st_mode):
        raise ValueError("config path must name a regular file")
    if before.st_nlink != 1 or (
        os.name == "posix"
        and (before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) & 0o022)
    ):
        raise ValueError("config file permissions are unsafe")
    if before.st_size > _MAX_CONFIG_BYTES:
        raise ValueError("config file exceeds the size limit")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    for name in ("O_CLOEXEC", "O_NONBLOCK", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if os.name == "nt":
        file_descriptor = os.open(candidate, flags)
    else:
        descriptor = os.open(root, directory_flags)
        try:
            for part in relative.parts[:-1]:
                next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            file_descriptor = os.open(relative.parts[-1], flags, dir_fd=descriptor)
        except BaseException:
            os.close(descriptor)
            raise
        os.close(descriptor)
    try:
        opened = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_nlink != 1
            or (
                os.name == "posix"
                and (
                    opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) & 0o022
                )
            )
        ):
            raise ValueError("config file changed or is unsafe")
        data = os.read(file_descriptor, _MAX_CONFIG_BYTES + 1)
        if len(data) > _MAX_CONFIG_BYTES:
            raise ValueError("config file exceeds the size limit")
    except OSError as error:
        raise ValueError("config file could not be read safely") from error
    finally:
        os.close(file_descriptor)
    return root, candidate, data


def _check_existing_state_components(root: Path, state_path: Path) -> None:
    relative = state_path.relative_to(root)
    current = root
    for index, part in enumerate(relative.parts):
        current /= part
        try:
            details = current.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise ValueError("state path is not safely accessible") from error
        if _is_link_like(details):
            raise ValueError("state path must not contain symlinks")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(details.st_mode):
            raise ValueError("state parent must be a directory")
        if os.name == "posix" and (
            details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) & 0o022
        ):
            raise ValueError("state path permissions are unsafe")


@dataclass(frozen=True, slots=True)
class HermesAdapterConfig:
    """Rooted profile; no-save/expiry cannot erase Hermes transcript copies."""

    profile_id: str
    profile_root: Path
    config_path: Path
    persona_path: Path
    state_path: Path | None = None
    acknowledge_host_context_persistence: bool = False
    normal_context_chars: int = 1_200
    deep_context_chars: int = 2_400

    def __post_init__(self) -> None:
        runtime = RuntimeConfig(
            profile_id=self.profile_id,
            normal_context_chars=self.normal_context_chars,
            deep_context_chars=self.deep_context_chars,
        )
        object.__setattr__(self, "profile_id", runtime.profile_id)
        if type(self.acknowledge_host_context_persistence) is not bool:
            raise TypeError("acknowledge_host_context_persistence must be a boolean")
        if self.state_path is not None and not self.acknowledge_host_context_persistence:
            raise ValueError("memory state requires acknowledgement of host persistence")
        for field_name in ("profile_root", "config_path", "persona_path"):
            value = getattr(self, field_name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(f"{field_name} must be an absolute Path")
        if self.state_path is not None and (
            not isinstance(self.state_path, Path) or not self.state_path.is_absolute()
        ):
            raise ValueError("state_path must be an absolute Path or None")
        for field_name in ("config_path", "persona_path", "state_path"):
            value = getattr(self, field_name)
            if value is not None:
                try:
                    value.relative_to(self.profile_root)
                except ValueError as error:
                    raise ValueError(f"{field_name} is outside the profile root") from error

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        *,
        allowed_root: str | os.PathLike[str],
    ) -> HermesAdapterConfig:
        """Load a bounded TOML profile without following symlinks."""

        try:
            root, config_path, raw = _secure_config_read(path, allowed_root=allowed_root)
            text = raw.decode("utf-8", errors="strict")
            data = tomllib.loads(text)
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError("invalid Hermes profile config") from error
        if not isinstance(data, dict) or set(data) - _CONFIG_FIELDS:
            raise ValueError("config contains unsupported fields")
        if data.get("schema") != _CONFIG_SCHEMA:
            raise ValueError("unsupported config schema")
        profile_id = data.get("profile_id")
        persona_path = _relative_profile_path(data.get("persona_path"), root, "persona_path")
        memory_enabled = data.get("memory_enabled", False)
        if type(memory_enabled) is not bool:
            raise ValueError("memory_enabled must be a boolean")
        acknowledgement = data.get("acknowledge_host_context_persistence", False)
        if type(acknowledgement) is not bool:
            raise ValueError("host persistence acknowledgement must be a boolean")
        if memory_enabled and not acknowledgement:
            raise ValueError("memory requires explicit acknowledgement of host persistence")
        state_value = data.get("state_path")
        if memory_enabled:
            state_path = _relative_profile_path(state_value, root, "state_path")
            _check_existing_state_components(root, state_path)
        else:
            if state_value is not None:
                raise ValueError("state_path requires memory_enabled=true")
            state_path = None
        normal = data.get("normal_context_chars", 1_200)
        deep = data.get("deep_context_chars", 2_400)
        return cls(
            profile_id=profile_id,
            profile_root=root,
            config_path=config_path,
            persona_path=persona_path,
            state_path=state_path,
            acknowledge_host_context_persistence=acknowledgement,
            normal_context_chars=normal,
            deep_context_chars=deep,
        )

    def build_runtime(self) -> HumanlikeRuntime:
        """Build a provider-neutral runtime for this isolated profile."""

        persona = Persona.load(self.persona_path, allowed_root=self.profile_root)
        memory = SQLiteMemoryLedger(self.state_path) if self.state_path is not None else None
        return HumanlikeRuntime(
            RuntimeConfig(
                self.profile_id,
                normal_context_chars=self.normal_context_chars,
                deep_context_chars=self.deep_context_chars,
            ),
            persona,
            memory=memory,
        )


class HermesAdapter:
    """Translate supported Hermes hook payloads without retaining host text."""

    __slots__ = ("_active_turns", "_lock", "_runtime")

    def __init__(self, runtime: object) -> None:
        self._runtime = runtime
        self._active_turns: OrderedDict[str, str] = OrderedDict()
        self._lock = RLock()

    def __repr__(self) -> str:
        return "HermesAdapter(runtime=<private>)"

    def register(self, context: object) -> None:
        """Register exactly the four supported Hermes hooks used by the adapter."""

        register_hook = getattr(context, "register_hook", None)
        if not callable(register_hook):
            raise TypeError("Hermes plugin context must provide register_hook")
        callbacks = (
            self.pre_llm_call,
            self.transform_llm_output,
            self.post_llm_call,
            self.on_session_finalize,
        )
        for name, callback in zip(HERMES_HOOKS, callbacks, strict=True):
            register_hook(name, callback)

    def pre_llm_call(self, **payload: Any) -> dict[str, str] | None:
        """Prepare bounded context that Hermes may retain in its transcript."""

        session_id = _host_string(payload, "session_id", limit=128)
        turn_id = _host_string(payload, "turn_id", limit=128)
        user_message = _host_string(payload, "user_message", limit=MAX_TURN_CHARS)
        if session_id is None or turn_id is None or user_message is None:
            return None
        locale = payload.get("locale", "und")
        if not isinstance(locale, str) or not locale or len(locale) > 32:
            locale = "und"
        with self._lock:
            prior_turn = self._active_turns.get(session_id)
            if prior_turn == turn_id:
                return None
            if prior_turn is not None:
                try:
                    self._runtime.observe(
                        TurnOutcome(
                            turn_id=prior_turn,
                            session_id=session_id,
                            success=False,
                            error_codes=("host.cancelled",),
                        ),
                        memory_records=(),
                    )
                except Exception:
                    return None
                del self._active_turns[session_id]
            elif len(self._active_turns) >= _MAX_ACTIVE_SESSIONS:
                return None
            try:
                plan = self._runtime.prepare(
                    TurnInput(
                        text=user_message,
                        turn_id=turn_id,
                        session_id=session_id,
                        locale=locale,
                    )
                )
                context = plan.render_context()
                if (
                    not isinstance(context, str)
                    or not context
                    or len(context) > _MAX_HOOK_CONTEXT_CHARS
                ):
                    self._runtime.observe(
                        TurnOutcome(
                            turn_id=turn_id,
                            session_id=session_id,
                            success=False,
                            error_codes=("host.unknown",),
                        ),
                        memory_records=(),
                    )
                    return None
                self._active_turns[session_id] = turn_id
                return {"context": context}
            except Exception:
                return None

    def transform_llm_output(self, **payload: Any) -> str | None:
        """Best-effort delivery correction for one explicit false identity claim."""

        response = payload.get("response_text")
        if not isinstance(response, str) or len(response) > _MAX_RESPONSE_CHARS:
            return None
        match = _IDENTITY_DECEPTION.fullmatch(response)
        if match is None:
            return None
        identity = " ".join(match.group(1).casefold().split())
        return f"I am an AI system, not a {identity}."

    def post_llm_call(self, **payload: Any) -> None:
        """Report bounded metadata without inferring persistence-safe success."""

        session_id = _host_string(payload, "session_id", limit=128)
        turn_id = _host_string(payload, "turn_id", limit=128)
        response = _host_string(payload, "assistant_response", limit=_MAX_RESPONSE_CHARS)
        if session_id is None or turn_id is None or response is None:
            return None
        with self._lock:
            active_turn = self._active_turns.get(session_id)
            if active_turn is not None and active_turn != turn_id:
                return None
            try:
                self._runtime.observe(
                    TurnOutcome(
                        turn_id=turn_id,
                        session_id=session_id,
                        success=False,
                        response_chars=len(response),
                        error_codes=("host.unknown",),
                    ),
                    memory_records=(),
                )
            except Exception:
                return None
            if active_turn is not None:
                del self._active_turns[session_id]
        return None

    def on_session_finalize(self, **payload: Any) -> None:
        """Drop runtime-owned ephemeral metadata for one Hermes session."""

        session_id = _host_string(payload, "session_id", limit=128)
        if session_id is None:
            return None
        with self._lock:
            try:
                self._runtime.finalize(SessionRef(session_id=session_id))
            except Exception:
                return None
            finally:
                self._active_turns.pop(session_id, None)
        return None


class _NeutralRuntime:
    """Fail-neutral runtime used when an installed profile cannot be loaded."""

    @staticmethod
    def prepare(*_: object, **__: object) -> None:
        raise RuntimeError("neutral adapter")

    @staticmethod
    def observe(*_: object, **__: object) -> None:
        raise RuntimeError("neutral adapter")

    @staticmethod
    def finalize(*_: object, **__: object) -> None:
        raise RuntimeError("neutral adapter")


def load_adapter(
    config_path: str | os.PathLike[str],
    *,
    allowed_root: str | os.PathLike[str],
) -> HermesAdapter:
    """Load one explicitly rooted Hermes profile and its thin adapter."""

    config = HermesAdapterConfig.load(config_path, allowed_root=allowed_root)
    return HermesAdapter(config.build_runtime())


def register(
    context: object,
    *,
    plugin_root: str | os.PathLike[str] | None = None,
    runtime: object | None = None,
) -> None:
    """Hermes directory-plugin entry point; registration itself always stays neutral."""

    if runtime is not None:
        adapter = HermesAdapter(runtime)
    else:
        root = (
            _absolute_path(plugin_root, "plugin_root")
            if plugin_root is not None
            else Path(__file__).parents[3]
        )
        profile_root = root / "examples" / "hermes-humanlike"
        config_path = profile_root / "humanlike.toml"
        try:
            adapter = load_adapter(config_path, allowed_root=profile_root)
        except Exception:
            adapter = HermesAdapter(_NeutralRuntime())
    adapter.register(context)


__all__ = [
    "HERMES_HOOKS",
    "HermesAdapter",
    "HermesAdapterConfig",
    "load_adapter",
    "register",
]
