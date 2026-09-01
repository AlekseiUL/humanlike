# Humanlike Agent Kit

Humanlike Agent Kit is a deterministic behavioral planning layer for conversational AI agents. It classifies each turn, assembles bounded guidance, and returns privacy-aware metadata while leaving model calls, tools, transport, and transcript storage to the host.

> **Status: private beta (`0.1.0`).** The API, configuration schema, and integration behavior may change before a public release. Access to this repository does not grant an open-source license.

The core package does **not** call an LLM and does **not** access the network. It can be evaluated completely offline.

## What it provides

- Deterministic RU/EN routing across cognitive modes and social moves.
- Bounded context plans with mandatory truth and privacy tails.
- Persona anchoring, discourse repetition control, calibrated stance, and drift signals.
- Optional evidence-aware memory behind an explicit host-controlled write contract.
- Deterministic offline conformance checks across route, social move, privacy, context budget, policy, disclosure, stance, memory, and drift.
- A reference Hermes directory plugin with four hooks: `pre_llm_call`, `transform_llm_output`, `post_llm_call`, and `on_session_finalize`.

Humanlike Agent Kit is not a model, chatbot UI, autonomous agent host, network service, or general-purpose model safety system.

## 10-minute quickstart

### 1. Install from the repository

Requirements: Python 3.11 or newer and access to this private repository.

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, the routing API can be explored from PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Native Windows is not a supported target for the hardened profile loader or SQLite memory backend in `0.1.0`; see [Compatibility](docs/COMPATIBILITY.md).

### 2. Route one turn

```bash
humanlike route --text "Rewrite this paragraph in a neutral tone." --locale en
```

The command prints one stable JSON object. The `route` object includes the selected mode, social move, response budget, candidate count, constraints, and reason codes. Use `python -m humanlike_agent` instead of `humanlike` if the virtual environment's script directory is not on `PATH`.

### 3. Run the offline conformance suite

```bash
humanlike eval
```

The installed package includes the official 40-case RU/EN suite. Pass `--cases-dir PATH` to evaluate a reviewed custom suite instead. The report contains per-case results, per-dimension coverage, and a summary. Exit status `0` means every case and every required dimension passed; `1` means a conformance expectation failed; `2` means the suite or CLI input was invalid.

### 4. Validate the Hermes reference profile

```bash
humanlike doctor --config examples/hermes-humanlike/humanlike.toml
```

A valid profile returns JSON with `"ok":true`. The example keeps durable memory disabled.

### 5. Smoke-test the Hermes reference adapter

The following is a host-independent contract check. It loads the same profile that the directory plugin uses and confirms the four callbacks without calling a model or network service.

```python
from pathlib import Path

from humanlike_agent.adapters.hermes import load_adapter


class ReferenceHost:
    def __init__(self) -> None:
        self.hooks = {}

    def register_hook(self, name, callback) -> None:
        self.hooks[name] = callback


profile = Path("examples/hermes-humanlike").resolve()
adapter = load_adapter(profile / "humanlike.toml", allowed_root=profile)
host = ReferenceHost()
adapter.register(host)

result = host.hooks["pre_llm_call"](
    session_id="quickstart-session",
    turn_id="quickstart-turn",
    user_message="Help me plan a careful reply.",
    locale="en",
)

assert tuple(host.hooks) == (
    "pre_llm_call",
    "transform_llm_output",
    "post_llm_call",
    "on_session_finalize",
)
assert result and result["context"]
print("Hermes reference adapter OK")
```

For a Hermes directory-plugin installation, point the host's supported plugin installer or loader at the **repository root**. The root-level `plugin.yaml` and `__init__.py` are required; installing only `src/` is not sufficient. Installer syntax varies by Hermes distribution, so confirm the command with the version deployed in your environment.

## Core API

Hosts can use the runtime without Hermes:

```python
from pathlib import Path

from humanlike_agent import (
    HumanlikeRuntime,
    Persona,
    RuntimeConfig,
    SessionRef,
    TurnInput,
    TurnOutcome,
)

profile = Path("examples/hermes-humanlike").resolve()
persona = Persona.load(profile / "SOUL.md", allowed_root=profile)
runtime = HumanlikeRuntime(RuntimeConfig("example-profile"), persona)

plan = runtime.prepare(
    TurnInput(
        text="Give me three distinct approaches.",
        turn_id="turn-1",
        session_id="session-1",
        locale="en",
    )
)
context_for_host_prompt = plan.render_context()

# The host calls its model, then reports bounded metadata back.
receipt = runtime.observe(
    TurnOutcome(
        turn_id="turn-1",
        session_id="session-1",
        success=True,
        response_chars=240,
    )
)
runtime.finalize(SessionRef(session_id="session-1"))
```

`context_for_host_prompt` is guidance for the host's prompt assembly. The host remains responsible for the model request, tool execution, output delivery, transcript retention, and enforcement outside this runtime.

## Hermes profile configuration

The reference profile is split between:

- `examples/hermes-humanlike/humanlike.toml` — schema, profile identifier, persona path, memory choice, and context budgets.
- `examples/hermes-humanlike/SOUL.md` — bounded identity, voice, values, and hard boundaries.

Keep `persona_path` and any `state_path` relative to the profile directory. Symlinks, path traversal, unsafe ownership, and group/other-writable profile files are rejected by the hardened loader.

Memory is off by default. Enabling it requires both `memory_enabled = true` and `acknowledge_host_context_persistence = true`, plus a relative `state_path`. This acknowledgement matters because the runtime cannot erase context or messages already copied into a host transcript. The reference Hermes adapter also does not infer durable memory records from message text; a richer host integration must supply validated records explicitly through the core API.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
ruff check .
```

The runtime package has no third-party runtime dependencies. Test, lint, and build tools are development-only extras.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Privacy](docs/PRIVACY.md)
- [Compatibility](docs/COMPATIBILITY.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## License

This private beta is proprietary and all rights are reserved. See [LICENSE](LICENSE).
