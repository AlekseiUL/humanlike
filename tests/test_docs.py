from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import humanlike_agent

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCUMENTS = (
    "README.md",
    "SECURITY.md",
    "LICENSE",
    "CHANGELOG.md",
    "ACKNOWLEDGEMENTS.md",
    "CONTRIBUTING.md",
    "docs/ARCHITECTURE.md",
    "docs/PRIVACY.md",
    "docs/COMPATIBILITY.md",
    "docs/HERMES_INSTALL.md",
    "docs/THREAT_MODEL.md",
)


def test_release_documents_are_complete_and_local_links_resolve() -> None:
    for relative_name in REQUIRED_DOCUMENTS:
        path = REPOSITORY_ROOT / relative_name
        source = path.read_text(encoding="utf-8")
        assert len(source) >= 300, relative_name
        assert source.count("```") % 2 == 0, relative_name
        assert not re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", source, re.IGNORECASE)
        if path.suffix != ".md":
            continue
        prose = re.sub(r"```.*?```", "", source, flags=re.DOTALL)
        for raw_target in re.findall(r"\[[^]]+\]\(([^)]+)\)", prose):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            assert (path.parent / target).resolve(strict=True), (relative_name, target)


def test_release_version_and_mit_license_are_synchronized() -> None:
    metadata = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = metadata["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert metadata["build-system"]["requires"] == ["setuptools==84.0.0"]
    assert "setuptools==84.0.0" in project["optional-dependencies"]["dev"]

    plugin = (REPOSITORY_ROOT / "plugin.yaml").read_text(encoding="utf-8")
    match = re.search(r'^version:\s*"([^"]+)"$', plugin, re.MULTILINE)
    assert match is not None
    assert match.group(1) == humanlike_agent.__version__

    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{humanlike_agent.__version__}]" in changelog

    license_text = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 Aleksei Ulyanov" in license_text
    assert "Permission is hereby granted" in license_text
    assert "All rights reserved." not in license_text

    current_docs = "\n".join(
        (REPOSITORY_ROOT / name).read_text(encoding="utf-8")
        for name in REQUIRED_DOCUMENTS
        if name != "LICENSE"
    )
    assert "LicenseRef-Proprietary" not in current_docs
    assert "No open-source license is granted" not in current_docs


def test_readme_contains_bilingual_description_creator_links_and_attribution() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## English" in readme
    assert "## Русский" in readme
    assert "https://youtube.com/@alekseiulianov" in readme
    assert "https://t.me/Sprut_AI" in readme
    assert "https://t.me/+eH-qNIDmud8zNDZi" in readme
    assert "https://t.me/tribute/app?startapp=sJyg" in readme
    assert "ACKNOWLEDGEMENTS.md" in readme


def test_documented_platform_and_hermes_compatibility_are_explicit() -> None:
    compatibility = (REPOSITORY_ROOT / "docs" / "COMPATIBILITY.md").read_text(
        encoding="utf-8"
    )

    assert re.search(r"Hermes\s+`?v0\.21", compatibility)
    assert "Native Windows is **not supported" in compatibility
    assert "WSL" in compatibility

    design = (
        REPOSITORY_ROOT / "docs" / "plans" / "2026-09-01-humanlike-agent-kit-design.md"
    ).read_text(encoding="utf-8")
    assert "unsupported first-person/publication" not in design
    assert "точное полное утверждение о биологической человечности" in design


def test_hermes_wheel_install_uses_runtime_python_and_entrypoint_validation() -> None:
    install = (REPOSITORY_ROOT / "docs" / "HERMES_INSTALL.md").read_text(
        encoding="utf-8"
    )
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    install_commands = (
        'HERMES_PYTHON="$(dirname "$(command -v hermes)")/python"',
        'uv pip install --python "$HERMES_PYTHON"',
        "hermes plugins enable humanlike-agent-kit --no-allow-tool-override",
        "hermes plugins show humanlike-agent-kit",
    )
    lifecycle_commands = (
        "hermes plugins disable humanlike-agent-kit",
        'uv pip uninstall --python "$HERMES_PYTHON" humanlike-agent-kit',
    )
    for command in (*install_commands, *lifecycle_commands):
        assert command in install
    for command in install_commands:
        assert command in readme
    assert "<40-character-commit-sha>" in install
    assert "\nhermes plugins install AlekseiUL/humanlike" not in install
    assert "hermes plugins doctor . --ci" in install
    assert "hermes plugins doctor humanlike-agent-kit --ci" not in install
    assert "humanlike install" not in install
    assert "humanlike uninstall" not in install


def test_ci_uses_the_locked_build_toolchain_and_complete_history() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "fetch-depth: 0" in workflow
    assert "uv sync --locked --all-extras" in workflow
    assert "version: \"0.12.8\"" in workflow
    assert "uv build --no-build-isolation" in workflow
    assert "setuptools==84.0.0" in (
        REPOSITORY_ROOT / "pyproject.toml"
    ).read_text(encoding="utf-8")


def test_readme_quickstart_commands_execute_offline() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"^humanlike route ", readme, re.MULTILINE)
    assert re.search(r"^humanlike eval$", readme, re.MULTILINE)
    assert re.search(r"^humanlike doctor ", readme, re.MULTILINE)

    commands = (
        ("route", "--locale", "en", "--text", "Rewrite this paragraph in a neutral tone."),
        ("eval",),
        ("doctor", "--config", "examples/hermes-humanlike/humanlike.toml"),
    )
    for command in commands:
        completed = subprocess.run(
            [sys.executable, "-m", "humanlike_agent", *command],
            cwd=REPOSITORY_ROOT,
            env=os.environ | {"PYTHONPATH": os.fspath(REPOSITORY_ROOT / "src")},
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert completed.returncode == 0, (command, completed.stdout, completed.stderr)
        assert completed.stderr == ""
        assert completed.stdout.count("\n") == 1
        payload = json.loads(completed.stdout)
        if command[0] == "eval":
            assert payload["summary"] == {"failed": 0, "passed": 40, "total": 40}
        elif command[0] == "route":
            assert payload["ok"] is True
            assert payload["route"]["mode"] == "task"
            assert payload["route"]["social_move"] == "revise"
        else:
            assert payload["ok"] is True
