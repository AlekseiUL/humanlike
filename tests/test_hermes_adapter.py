import importlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from humanlike_agent.persona import Persona, PersonaSpine
from humanlike_agent.runtime import HumanlikeRuntime, RuntimeConfig

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _runtime(*, memory: object | None = None) -> HumanlikeRuntime:
    persona = Persona(
        spine=PersonaSpine(
            identity="A practical AI collaborator.",
            voice="Warm and direct.",
            values="Truth and autonomy.",
        ),
        declared_boundaries="Protect privacy.",
    )
    return HumanlikeRuntime(
        RuntimeConfig("hermes-profile"),
        persona,
        memory=memory,
        clock=lambda: NOW,
        fingerprint_key=b"k" * 32,
    )


class _FakeHost:
    def __init__(self) -> None:
        self.hooks: dict[str, Callable[..., object]] = {}

    def register_hook(self, name: str, callback: Callable[..., object]) -> None:
        self.hooks[name] = callback


def _write_profile(root: Path, *, overrides: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SOUL.md").write_text(
        """\
# Identity
A truthful conversational AI.
# Voice
Warm and direct.
# Values
Truth and autonomy.
# Hard boundaries
Protect privacy.
""",
        encoding="utf-8",
    )
    config = root / "humanlike.toml"
    config.write_text(
        """\
schema = "humanlike-hermes/v1"
profile_id = "test-profile"
persona_path = "SOUL.md"
memory_enabled = false
normal_context_chars = 1200
deep_context_chars = 2400
"""
        + overrides,
        encoding="utf-8",
    )
    return config


def test_hermes_adapter_module_imports() -> None:
    assert importlib.import_module("humanlike_agent.adapters.hermes")


def test_registers_exactly_the_supported_hermes_v020_hooks() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    host = _FakeHost()

    HermesAdapter(_runtime()).register(host)

    assert tuple(host.hooks) == (
        "pre_llm_call",
        "transform_llm_output",
        "post_llm_call",
        "on_session_finalize",
    )


def test_pre_llm_call_returns_only_ephemeral_context() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    host = _FakeHost()
    runtime = _runtime()
    HermesAdapter(runtime).register(host)

    result = host.hooks["pre_llm_call"](
        session_id="session-1",
        turn_id="turn-1",
        user_message="Привет! secret-canary",
        conversation_history=[{"role": "user", "content": "older secret"}],
        is_first_turn=True,
        model="test-model",
        platform="cli",
    )

    assert isinstance(result, dict)
    assert tuple(result) == ("context",)
    assert isinstance(result["context"], str)
    assert len(result["context"]) < 10_000
    assert "truthful about being an AI" in result["context"]
    assert "secret-canary" not in result["context"]
    assert "older secret" not in repr(runtime.snapshot())


def test_hooks_fail_neutral_for_malformed_payloads_and_component_errors() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    class BrokenRuntime:
        def prepare(self, *_: object, **__: object) -> object:
            raise RuntimeError("host-secret")

        def observe(self, *_: object, **__: object) -> object:
            raise RuntimeError("host-secret")

        def finalize(self, *_: object, **__: object) -> object:
            raise RuntimeError("host-secret")

    adapter = HermesAdapter(BrokenRuntime())

    assert adapter.pre_llm_call(session_id="session-1") is None
    assert (
        adapter.pre_llm_call(session_id="session-1", turn_id="turn-1", user_message="host-secret")
        is None
    )
    assert adapter.post_llm_call(session_id="session-1") is None
    assert (
        adapter.post_llm_call(
            session_id="session-1",
            turn_id="turn-1",
            assistant_response="host-secret",
        )
        is None
    )
    assert adapter.on_session_finalize(session_id="session-1") is None


def test_post_and_finalize_translate_only_metadata() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    runtime = _runtime()
    adapter = HermesAdapter(runtime)
    assert (
        adapter.pre_llm_call(
            session_id="session-1",
            turn_id="turn-1",
            user_message="Hello",
        )
        is not None
    )

    result = adapter.post_llm_call(
        session_id="session-1",
        turn_id="turn-1",
        assistant_response="A private answer",
    )

    assert result is None
    assert runtime.snapshot().completed_receipt_count == 1
    assert "A private answer" not in repr(runtime.snapshot())
    assert adapter.on_session_finalize(session_id="session-1") is None
    assert runtime.snapshot().session_count == 0


def test_adapter_never_derives_durable_memory_from_host_text() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    class MemorySpy:
        def __init__(self) -> None:
            self.remember_calls = 0

        def recall(self, _: object) -> tuple[()]:
            return ()

        def remember(self, *_: object, **__: object) -> bool:
            self.remember_calls += 1
            return True

    memory = MemorySpy()
    adapter = HermesAdapter(_runtime(memory=memory))
    assert (
        adapter.pre_llm_call(
            session_id="session-1",
            turn_id="turn-save",
            user_message="Please remember this: my private value.",
        )
        is not None
    )

    adapter.post_llm_call(
        session_id="session-1",
        turn_id="turn-save",
        assistant_response="Done.",
    )

    assert memory.remember_calls == 0


def test_transform_is_narrow_best_effort_and_none_means_unchanged() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    adapter = HermesAdapter(_runtime())

    assert (
        adapter.transform_llm_output(response_text="I am a human.")
        == "I am an AI system, not a human."
    )
    assert (
        adapter.transform_llm_output(response_text="I am a biological person")
        == "I am an AI system, not a biological person."
    )
    assert adapter.transform_llm_output(response_text="I am a human resources manager.") is None
    assert adapter.transform_llm_output(response_text="Quote: 'I am a human.'") is None
    assert adapter.transform_llm_output(response_text=object()) is None


def test_post_never_infers_persistence_success_from_missing_or_false_failed_flag() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    class CapturingRuntime:
        def __init__(self) -> None:
            self.outcomes: list[object] = []

        def observe(self, outcome: object, **_: object) -> None:
            self.outcomes.append(outcome)

    runtime = CapturingRuntime()
    adapter = HermesAdapter(runtime)

    adapter.post_llm_call(session_id="session-1", turn_id="turn-1", assistant_response="answer")
    adapter.post_llm_call(
        session_id="session-1",
        turn_id="turn-2",
        assistant_response="answer",
        failed=False,
    )
    adapter.post_llm_call(
        session_id="session-1",
        turn_id="turn-3",
        assistant_response="answer",
        success=True,
        failed=False,
    )

    assert all(outcome.success is False for outcome in runtime.outcomes)
    assert all(outcome.error_codes == ("host.unknown",) for outcome in runtime.outcomes)


def test_pre_rejects_context_at_hermes_spill_threshold() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    class OversizedPlan:
        @staticmethod
        def render_context() -> str:
            return "x" * 10_000

    class OversizedRuntime:
        @staticmethod
        def prepare(_: object) -> OversizedPlan:
            return OversizedPlan()

    result = HermesAdapter(OversizedRuntime()).pre_llm_call(
        session_id="session-1", turn_id="turn-1", user_message="Hello"
    )

    assert result is None


def test_interrupted_turns_are_retired_before_the_next_sequential_pre() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapter

    runtime = _runtime()
    adapter = HermesAdapter(runtime)

    for index in range(129):
        result = adapter.pre_llm_call(
            session_id="session-1",
            turn_id=f"turn-{index}",
            user_message=f"message secret-canary-{index}",
        )
        assert result is not None

    snapshot = runtime.snapshot()
    assert snapshot.pending_turn_count == 1
    assert snapshot.completed_receipt_count == 128
    assert "secret-canary" not in repr(runtime.__dict__)

    adapter.on_session_finalize(session_id="session-1")
    adapter.on_session_finalize(session_id="session-1")
    assert runtime.snapshot().pending_turn_count == 0


def test_profile_config_is_explicitly_rooted_and_builds_adapter(tmp_path: Path) -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig, load_adapter

    profile_root = tmp_path / "profile"
    config_path = _write_profile(profile_root)

    config = HermesAdapterConfig.load(config_path, allowed_root=profile_root)
    adapter = load_adapter(config_path, allowed_root=profile_root)

    assert config.profile_id == "test-profile"
    assert config.profile_root == profile_root
    assert config.persona_path == profile_root / "SOUL.md"
    assert (
        adapter.pre_llm_call(session_id="session-1", turn_id="turn-1", user_message="Hello")
        is not None
    )


@pytest.mark.parametrize("unsafe_persona", ["../SOUL.md", "/tmp/SOUL.md", "bad\x00.md"])
def test_profile_config_rejects_unsafe_persona_paths(tmp_path: Path, unsafe_persona: str) -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig

    profile_root = tmp_path / "profile"
    config_path = _write_profile(profile_root)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'persona_path = "SOUL.md"', f'persona_path = "{unsafe_persona}"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        HermesAdapterConfig.load(config_path, allowed_root=profile_root)


def test_profile_config_rejects_symlink_and_group_writable_files(tmp_path: Path) -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig

    profile_root = tmp_path / "profile"
    config_path = _write_profile(profile_root)
    link = profile_root / "linked.toml"
    link.symlink_to(config_path)
    with pytest.raises(ValueError):
        HermesAdapterConfig.load(link, allowed_root=profile_root)

    config_path.chmod(0o666)
    with pytest.raises(ValueError):
        HermesAdapterConfig.load(config_path, allowed_root=profile_root)


def test_memory_state_is_confined_and_absent_state_stays_absent_on_read(
    tmp_path: Path,
) -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig, load_adapter

    profile_root = tmp_path / "profile"
    config_path = _write_profile(profile_root)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace(
            "memory_enabled = false",
            "memory_enabled = true\nacknowledge_host_context_persistence = true",
        )
        .replace(
            "normal_context_chars = 1200",
            'state_path = "state/memory.db"\nnormal_context_chars = 1200',
        ),
        encoding="utf-8",
    )
    state_dir = profile_root / "state"

    config = HermesAdapterConfig.load(config_path, allowed_root=profile_root)
    adapter = load_adapter(config_path, allowed_root=profile_root)
    result = adapter.pre_llm_call(
        session_id="session-1", turn_id="turn-1", user_message="Remember tea"
    )

    assert config.state_path == state_dir / "memory.db"
    assert config.acknowledge_host_context_persistence is True
    assert result is not None
    assert not state_dir.exists()


def test_memory_state_traversal_is_rejected(tmp_path: Path) -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig

    profile_root = tmp_path / "profile"
    config_path = _write_profile(profile_root)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace("memory_enabled = false", "memory_enabled = true")
        .replace(
            "normal_context_chars = 1200",
            'state_path = "../memory.db"\nnormal_context_chars = 1200',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        HermesAdapterConfig.load(config_path, allowed_root=profile_root)


@pytest.mark.parametrize("acknowledgement", [False, 1])
def test_direct_config_cannot_bypass_memory_acknowledgement(
    tmp_path: Path, acknowledgement: object
) -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig

    profile_root = tmp_path / "profile"
    profile_root.mkdir()

    with pytest.raises((TypeError, ValueError)):
        HermesAdapterConfig(
            profile_id="profile",
            profile_root=profile_root,
            config_path=profile_root / "humanlike.toml",
            persona_path=profile_root / "SOUL.md",
            state_path=profile_root / "state" / "memory.db",
            acknowledge_host_context_persistence=acknowledgement,  # type: ignore[arg-type]
        )


def test_module_register_stays_neutral_when_default_profile_is_broken(tmp_path: Path) -> None:
    from humanlike_agent.adapters.hermes import register

    host = _FakeHost()

    register(host, plugin_root=tmp_path)

    assert tuple(host.hooks) == (
        "pre_llm_call",
        "transform_llm_output",
        "post_llm_call",
        "on_session_finalize",
    )
    assert (
        host.hooks["pre_llm_call"](session_id="session-1", turn_id="turn-1", user_message="secret")
        is None
    )


def test_wheel_entrypoint_registers_memory_off_starter_runtime() -> None:
    from humanlike_agent.hermes_plugin import register

    host = _FakeHost()
    register(host)

    assert tuple(host.hooks) == (
        "pre_llm_call",
        "transform_llm_output",
        "post_llm_call",
        "on_session_finalize",
    )
    result = host.hooks["pre_llm_call"](
        session_id="entrypoint-session",
        turn_id="entrypoint-turn",
        user_message="Help me answer carefully.",
        locale="en",
    )
    assert isinstance(result, dict)
    assert "truthful about being an AI" in result["context"]


def test_example_discloses_that_humanlike_cannot_erase_host_transcript_copies() -> None:
    from humanlike_agent.adapters.hermes import HermesAdapterConfig

    repository = Path(__file__).parents[1]
    example = (repository / "examples/hermes-humanlike/humanlike.toml").read_text(encoding="utf-8")
    disclosure = f"{example}\n{HermesAdapterConfig.__doc__}".casefold()

    assert "memory_enabled = false" in example
    assert "acknowledge_host_context_persistence = false" in example
    assert "no-save" in disclosure
    assert "expiry" in disclosure
    assert "cannot erase hermes transcript copies" in disclosure


def test_root_manifest_and_registration_shim_survive_repository_copy(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    copied = tmp_path / "installed-plugin"
    copied.mkdir()
    for name in ("src", "examples"):
        shutil.copytree(repository / name, copied / name)
    for name in ("plugin.yaml", "__init__.py"):
        shutil.copy2(repository / name, copied / name)

    script = """
import importlib.util
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.humanlike_agent_kit",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Host:
    def __init__(self): self.hooks = {}
    def register_hook(self, name, callback): self.hooks[name] = callback
host = Host()
module.register(host)
callback_module = sys.modules[host.hooks["pre_llm_call"].__self__.__class__.__module__]
print(json.dumps({"hooks": list(host.hooks), "package": callback_module.__file__}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(copied)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    loaded = json.loads(completed.stdout)
    assert loaded["hooks"] == [
        "pre_llm_call",
        "transform_llm_output",
        "post_llm_call",
        "on_session_finalize",
    ]
    assert Path(loaded["package"]).is_relative_to(copied / "src")

    manifest = (copied / "plugin.yaml").read_text(encoding="utf-8")
    assert manifest.count("  - ") == 4
    assert "kind: standalone" in manifest
    assert "provides_hooks:" in manifest
    assert all(f"  - {hook}" in manifest for hook in loaded["hooks"])


def test_root_shim_isolates_core_from_preloaded_foreign_package(tmp_path: Path) -> None:
    from humanlike_agent.adapters.hermes import HERMES_HOOKS

    repository = Path(__file__).parents[1]
    copied = tmp_path / "installed-plugin"
    copied.mkdir()
    for name in ("src", "examples"):
        shutil.copytree(repository / name, copied / name)
    for name in ("plugin.yaml", "__init__.py"):
        shutil.copy2(repository / name, copied / name)

    script = """
import importlib.util
import json
import sys
import types
from pathlib import Path
root = Path(sys.argv[1])
foreign = types.ModuleType("humanlike_agent")
foreign.marker = "foreign-package-preserved"
sys.modules["humanlike_agent"] = foreign
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.humanlike_agent_kit",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
class Host:
    def __init__(self): self.hooks = {}
    def register_hook(self, name, callback): self.hooks[name] = callback
host = Host()
module.register(host)
callback_module = sys.modules[host.hooks["pre_llm_call"].__self__.__class__.__module__]
print(json.dumps({
    "foreign": sys.modules["humanlike_agent"].marker,
    "hooks": list(host.hooks),
    "private_module": callback_module.__file__,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(copied)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    loaded = json.loads(completed.stdout)
    assert loaded["foreign"] == "foreign-package-preserved"
    assert loaded["hooks"] == list(HERMES_HOOKS)
    assert Path(loaded["private_module"]).is_relative_to(copied / "src")


def test_root_shim_rejects_core_package_symlink_outside_plugin(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    copied = tmp_path / "installed-plugin"
    source = copied / "src"
    source.mkdir(parents=True)
    shutil.copy2(repository / "__init__.py", copied / "__init__.py")
    external_package = tmp_path / "foreign" / "humanlike_agent"
    external_package.mkdir(parents=True)
    (external_package / "__init__.py").write_text("marker = 'foreign'\n", encoding="utf-8")
    (source / "humanlike_agent").symlink_to(external_package, target_is_directory=True)

    script = """
import importlib.util
import sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.humanlike_agent_kit",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(copied)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode != 0


def test_root_shim_rejects_nested_module_symlink_before_execution(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    copied = tmp_path / "installed-plugin"
    shutil.copytree(repository / "src", copied / "src")
    shutil.copy2(repository / "__init__.py", copied / "__init__.py")
    marker = tmp_path / "external-module-executed"
    external_module = tmp_path / "external_runtime.py"
    external_module.write_text(
        "from pathlib import Path\n"
        f"Path({os.fspath(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "class HumanlikeRuntime: pass\n"
        "class RuntimeConfig: pass\n"
        "class RuntimeSnapshot: pass\n",
        encoding="utf-8",
    )
    runtime_module = copied / "src" / "humanlike_agent" / "runtime.py"
    runtime_module.unlink()
    runtime_module.symlink_to(external_module)

    script = """
import importlib.util
import sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.humanlike_agent_kit",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(copied)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert not marker.exists()
    assert completed.returncode != 0


def test_root_shim_rejects_nested_subpackage_symlink_before_execution(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    copied = tmp_path / "installed-plugin"
    shutil.copytree(repository / "src", copied / "src")
    shutil.copy2(repository / "__init__.py", copied / "__init__.py")
    marker = tmp_path / "external-subpackage-executed"
    external_package = tmp_path / "foreign" / "adapters"
    external_package.mkdir(parents=True)
    (external_package / "__init__.py").write_text("", encoding="utf-8")
    (external_package / "hermes.py").write_text(
        "from pathlib import Path\n"
        f"Path({os.fspath(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "def register(context, **kwargs): pass\n",
        encoding="utf-8",
    )
    adapters_package = copied / "src" / "humanlike_agent" / "adapters"
    shutil.rmtree(adapters_package)
    adapters_package.symlink_to(external_package, target_is_directory=True)

    script = """
import importlib.util
import sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.humanlike_agent_kit",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Host:
    def register_hook(self, name, callback): pass
module.register(Host())
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(copied)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert not marker.exists()
    assert completed.returncode != 0


def test_root_shim_rejects_symlinked_valid_bytecode_cache_before_execution(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parents[1]
    copied = tmp_path / "installed-plugin"
    shutil.copytree(repository / "src", copied / "src")
    shutil.copy2(repository / "__init__.py", copied / "__init__.py")
    marker = tmp_path / "external-bytecode-executed"
    external_source = tmp_path / "external_runtime.py"
    external_source.write_text(
        "from pathlib import Path\n"
        f"Path({os.fspath(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "class HumanlikeRuntime: pass\n"
        "class RuntimeConfig: pass\n"
        "class RuntimeSnapshot: pass\n",
        encoding="utf-8",
    )
    external_bytecode = tmp_path / "external_runtime.pyc"
    py_compile.compile(
        os.fspath(external_source),
        cfile=os.fspath(external_bytecode),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    cache_path = (
        copied
        / "src"
        / "humanlike_agent"
        / "__pycache__"
        / f"runtime.{sys.implementation.cache_tag}.pyc"
    )
    cache_path.parent.mkdir(exist_ok=True)
    cache_path.unlink(missing_ok=True)
    cache_path.symlink_to(external_bytecode)

    script = """
import importlib.util
import sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.humanlike_agent_kit",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(copied)],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert not marker.exists()
    assert completed.returncode != 0
