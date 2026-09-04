from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_GATE = REPOSITORY_ROOT / "scripts" / "privacy_gate.py"


def _run_gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PRIVACY_GATE), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_privacy_gate_accepts_a_clean_source_tree(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text("VALUE = 'safe'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=replace-me\n", encoding="utf-8")

    result = _run_gate(tmp_path)

    assert result.returncode == 0
    assert "privacy gate passed" in result.stdout.lower()


def test_privacy_gate_rejects_secrets_and_local_home_paths_without_echoing_them(
    tmp_path: Path,
) -> None:
    secret = "gh" + "p_" + "A" * 36
    local_path = "/" + "Users" + "/private-owner/project"
    unsafe = tmp_path / "unsafe.txt"
    unsafe.write_text(f"token={secret}\nsource={local_path}\n", encoding="utf-8")

    result = _run_gate(tmp_path)

    assert result.returncode == 1
    assert "credential" in result.stdout.lower()
    assert "local-home-path" in result.stdout.lower()
    assert secret not in result.stdout
    assert local_path not in result.stdout


@pytest.mark.parametrize(
    "opaque",
    (
        b"\x00" + ("gh" + "p_" + "A" * 36).encode("ascii"),
        b"\xffopaque",
    ),
)
def test_privacy_gate_fails_closed_for_opaque_binary_files(
    tmp_path: Path,
    opaque: bytes,
) -> None:
    (tmp_path / "payload.bin").write_bytes(opaque)

    result = _run_gate(tmp_path)

    assert result.returncode == 1
    assert "binary-artifact" in result.stdout.lower()


def test_privacy_gate_accepts_only_the_reviewed_hero_asset(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "assets" / "humanlike-hero.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        (REPOSITORY_ROOT / "docs" / "assets" / "humanlike-hero.jpg").read_bytes()
    )

    accepted = _run_gate(tmp_path)
    assert accepted.returncode == 0, accepted.stdout

    target.write_bytes(target.read_bytes() + b"changed")
    rejected = _run_gate(tmp_path)
    assert rejected.returncode == 1
    assert "binary-artifact" in rejected.stdout.lower()


def test_privacy_gate_rejects_forbidden_artifacts_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SAFE_PLACEHOLDER=1\n", encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("safe\n", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    result = _run_gate(tmp_path)

    assert result.returncode == 1
    assert "forbidden-artifact" in result.stdout.lower()
    assert "symlink" in result.stdout.lower()


def test_privacy_gate_scans_reachable_head_history(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Privacy Gate Test")
    _git(tmp_path, "config", "user.email", "privacy-gate@example.invalid")
    historical = tmp_path / "historical.txt"
    historical.write_text("source=/" + "Users" + "/old-owner/project\n", encoding="utf-8")
    _git(tmp_path, "add", "historical.txt")
    _git(tmp_path, "commit", "-qm", "add historical fixture")
    historical.unlink()
    _git(tmp_path, "add", "-u")
    _git(tmp_path, "commit", "-qm", "remove historical fixture")

    result = _run_gate(tmp_path)

    assert result.returncode == 1
    assert "history:" in result.stdout.lower()
    assert "local-home-path" in result.stdout.lower()


def test_privacy_gate_checks_every_historical_path_for_a_shared_blob(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Privacy Gate Test")
    _git(tmp_path, "config", "user.email", "privacy-gate@example.invalid")
    safe = tmp_path / "a.txt"
    forbidden = tmp_path / "archived.key"
    safe.write_text("same harmless bytes\n", encoding="utf-8")
    forbidden.write_bytes(safe.read_bytes())
    _git(tmp_path, "add", "a.txt", "archived.key")
    _git(tmp_path, "commit", "-qm", "add shared blob")
    forbidden.unlink()
    _git(tmp_path, "add", "-u")
    _git(tmp_path, "commit", "-qm", "remove forbidden path")

    result = _run_gate(tmp_path)

    assert result.returncode == 1
    assert "history:archived.key: forbidden-artifact" in result.stdout.lower()
