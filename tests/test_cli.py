import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

from humanlike_agent.router import MAX_TURN_CHARS


def _write_profile(root: Path, *, config_suffix: str = "") -> Path:
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
    path = root / "humanlike.toml"
    path.write_text(
        """\
schema = "humanlike-hermes/v1"
profile_id = "doctor-profile"
persona_path = "SOUL.md"
memory_enabled = false
normal_context_chars = 1200
deep_context_chars = 2400
"""
        + config_suffix,
        encoding="utf-8",
    )
    return path


def _json_stdout(capsys: object) -> dict[str, object]:
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.endswith("\n")
    assert output.out.count("\n") == 1
    return json.loads(output.out)


def test_cli_module_imports() -> None:
    assert importlib.import_module("humanlike_agent.cli")


def test_route_command_emits_stable_json(capsys: object) -> None:
    from humanlike_agent.cli import main

    first_status = main(["route", "--text", "Привет!", "--locale", "ru"])
    first_output = capsys.readouterr().out
    second_status = main(["route", "--text", "Привет!", "--locale", "ru"])
    second_output = capsys.readouterr().out

    assert first_status == second_status == 0
    assert first_output == second_output
    payload = json.loads(first_output)
    assert payload["command"] == "route"
    assert payload["ok"] is True
    assert payload["route"]["mode"] == "social"
    assert payload["route"]["social_move"] == "connect"


def test_route_rejects_oversized_input_without_echo_or_traceback(capsys: object) -> None:
    from humanlike_agent.cli import main

    secret = "secret-canary-" + "x" * MAX_TURN_CHARS
    status = main(["route", "--text", secret])
    payload = _json_stdout(capsys)

    assert status != 0
    assert payload == {"command": "route", "error": "invalid_input", "ok": False}
    assert "secret-canary" not in json.dumps(payload)


def test_invalid_arguments_are_stable_json_not_argparse_traceback(capsys: object) -> None:
    from humanlike_agent.cli import main

    status = main(["route", "--unknown", "secret-canary"])
    payload = _json_stdout(capsys)

    assert status != 0
    assert payload == {"command": "cli", "error": "invalid_arguments", "ok": False}
    assert "secret-canary" not in json.dumps(payload)


def test_doctor_validates_rooted_profile_without_exposing_paths(
    tmp_path: Path, capsys: object
) -> None:
    from humanlike_agent.cli import main

    config_path = _write_profile(tmp_path / "secret-canary-profile")

    status = main(["doctor", "--config", os.fspath(config_path)])
    payload = _json_stdout(capsys)

    assert status == 0
    assert payload == {
        "command": "doctor",
        "memory_enabled": False,
        "ok": True,
        "profile_id": "doctor-profile",
        "schema": "humanlike-hermes/v1",
    }
    assert "secret-canary" not in json.dumps(payload)


def test_doctor_failure_is_fixed_nonzero_json_without_secret(
    tmp_path: Path, capsys: object
) -> None:
    from humanlike_agent.cli import main

    config_path = _write_profile(tmp_path / "secret-canary", config_suffix="bad = [")

    status = main(["doctor", "--config", os.fspath(config_path)])
    payload = _json_stdout(capsys)

    assert status != 0
    assert payload == {"command": "doctor", "error": "invalid_config", "ok": False}
    assert "secret-canary" not in json.dumps(payload)


def test_doctor_rejects_memory_without_host_persistence_ack(tmp_path: Path, capsys: object) -> None:
    from humanlike_agent.cli import main

    config_path = _write_profile(tmp_path / "profile")
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace("memory_enabled = false", "memory_enabled = true")
        .replace(
            "normal_context_chars = 1200",
            'state_path = "state/memory.db"\nnormal_context_chars = 1200',
        ),
        encoding="utf-8",
    )

    status = main(["doctor", "--config", os.fspath(config_path)])
    payload = _json_stdout(capsys)

    assert status != 0
    assert payload == {"command": "doctor", "error": "invalid_config", "ok": False}


def test_eval_uses_the_bundled_cases_directory_by_default(capsys: object) -> None:
    from humanlike_agent.cli import main

    status = main(["eval"])
    payload = _json_stdout(capsys)

    assert status == 0
    assert payload["schema"] == "humanlike-conformance-report/v1"
    assert payload["summary"] == {"failed": 0, "passed": 40, "total": 40}


def test_doctor_json_is_ascii_safe_for_unicode_profile(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    config_path = _write_profile(tmp_path / "profile")
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("doctor-profile", "профиль"),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "humanlike_agent",
            "doctor",
            "--config",
            os.fspath(config_path),
        ],
        cwd=repository,
        env=os.environ
        | {
            "PYTHONIOENCODING": "ascii",
            "PYTHONPATH": os.fspath(repository / "src"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout.count("\n") == 1
    assert json.loads(completed.stdout)["profile_id"] == "профиль"


def test_module_entrypoint_and_pyproject_console_script_are_wired() -> None:
    repository = Path(__file__).parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "humanlike_agent",
            "route",
            "--text",
            "Hello!",
            "--locale",
            "en",
        ],
        cwd=repository,
        env=os.environ | {"PYTHONPATH": os.fspath(repository / "src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["route"]["mode"] == "social"
    pyproject = (repository / "pyproject.toml").read_text(encoding="utf-8")
    assert 'humanlike = "humanlike_agent.cli:main"' in pyproject
