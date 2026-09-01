import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def _run(
    command: list[str],
    *,
    cwd: Path,
    extra_environment: dict[str, str] | None = None,
    process_umask: int | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(extra_environment or {})
    previous_umask = os.umask(process_umask) if process_umask is not None else None
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    finally:
        if previous_umask is not None:
            os.umask(previous_umask)


def _payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def test_packaged_runtime_data_matches_the_reviewed_repository_sources() -> None:
    repository = Path(__file__).parents[1]
    package_data = repository / "src" / "humanlike_agent" / "data"
    pairs = (
        (repository / "evals" / "cases" / "en.jsonl", package_data / "evals" / "en.jsonl"),
        (repository / "evals" / "cases" / "ru.jsonl", package_data / "evals" / "ru.jsonl"),
        (
            repository / "packs" / "foundation" / "anti-patterns.json",
            package_data / "foundation" / "anti-patterns.json",
        ),
        (
            repository / "packs" / "foundation" / "manifest.json",
            package_data / "foundation" / "manifest.json",
        ),
        (
            repository / "packs" / "foundation" / "rubric.json",
            package_data / "foundation" / "rubric.json",
        ),
    )

    assert all(reviewed.read_bytes() == packaged.read_bytes() for reviewed, packaged in pairs)


def test_wheel_contains_runtime_data_and_installed_cli_smokes(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    built = _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheelhouse),
        ],
        cwd=repository,
    )
    assert built.returncode == 0, built.stderr or built.stdout
    wheel = next(wheelhouse.glob("humanlike_agent_kit-*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert {
        "humanlike_agent/data/evals/en.jsonl",
        "humanlike_agent/data/evals/ru.jsonl",
        "humanlike_agent/data/foundation/anti-patterns.json",
        "humanlike_agent/data/foundation/manifest.json",
        "humanlike_agent/data/foundation/rubric.json",
    } <= names

    uv = shutil.which("uv")
    assert uv is not None
    environment = tmp_path / "installed"
    created = _run(
        [uv, "venv", "--python", sys.executable, str(environment)],
        cwd=tmp_path,
    )
    assert created.returncode == 0, created.stderr or created.stdout
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        cwd=tmp_path,
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SOUL.md").write_text(
        "# Identity\nA portable, truthful AI collaborator.\n"
        "# Voice\nWarm and direct.\n"
        "# Values\nTruth and autonomy.\n"
        "# Hard boundaries\nProtect privacy.\n",
        encoding="utf-8",
    )
    config = profile / "humanlike.toml"
    config.write_text(
        'schema = "humanlike-hermes/v1"\n'
        'profile_id = "wheel-smoke"\n'
        'persona_path = "SOUL.md"\n'
        "memory_enabled = false\n",
        encoding="utf-8",
    )

    route = _payload(
        _run(
            [str(python), "-m", "humanlike_agent", "route", "--text", "Hello"],
            cwd=profile,
        )
    )
    evaluation = _payload(
        _run([str(python), "-m", "humanlike_agent", "eval"], cwd=profile)
    )
    doctor = _payload(
        _run(
            [str(python), "-m", "humanlike_agent", "doctor", "--config", str(config)],
            cwd=profile,
        )
    )

    assert route["ok"] is True
    assert evaluation["summary"] == {"failed": 0, "passed": 40, "total": 40}
    assert doctor == {
        "command": "doctor",
        "memory_enabled": False,
        "ok": True,
        "profile_id": "wheel-smoke",
        "schema": "humanlike-hermes/v1",
    }


def test_sdist_is_reproducible_owner_neutral_and_complete(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    epoch = 1_767_225_600
    archives: list[Path] = []
    for name, process_umask in (("first", 0o022), ("second", 0o077)):
        destination = tmp_path / name
        destination.mkdir()
        built = _run(
            [
                sys.executable,
                "-m",
                "build",
                "--sdist",
                "--no-isolation",
                "--outdir",
                str(destination),
            ],
            cwd=repository,
            extra_environment={"SOURCE_DATE_EPOCH": str(epoch)},
            process_umask=process_umask,
        )
        assert built.returncode == 0, built.stderr or built.stdout
        archives.append(next(destination.glob("humanlike_agent_kit-*.tar.gz")))

    assert archives[0].read_bytes() == archives[1].read_bytes()
    with tarfile.open(archives[0], "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}

    assert all(member.uid == member.gid == 0 for member in members)
    assert all(member.uname == member.gname == "" for member in members)
    assert all(member.mtime == epoch for member in members)
    required_suffixes = {
        "/CHANGELOG.md",
        "/README.md",
        "/SECURITY.md",
        "/__init__.py",
        "/build_backend.py",
        "/docs/PRIVACY.md",
        "/evals/cases/en.jsonl",
        "/examples/hermes-humanlike/humanlike.toml",
        "/packs/foundation/manifest.json",
        "/plugin.yaml",
        "/scripts/privacy_gate.py",
        "/tests/fixtures/router_cases.json",
    }
    assert all(any(name.endswith(suffix) for name in names) for suffix in required_suffixes)
