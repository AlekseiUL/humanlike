#!/usr/bin/env python3
"""Fail closed when a release tree or its reachable HEAD history leaks local data."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_IGNORED_WORKTREE_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
    }
)
_FORBIDDEN_TREE_PARTS = _IGNORED_WORKTREE_DIRECTORIES - {".git"} | frozenset(
    {"eval-runs", "private-packs", "state"}
)
_FORBIDDEN_SUFFIXES = frozenset(
    {
        ".bak",
        ".db",
        ".jks",
        ".key",
        ".keystore",
        ".log",
        ".orig",
        ".p12",
        ".pem",
        ".pfx",
        ".sqlite",
        ".sqlite3",
    }
)
_MAX_SCANNED_BYTES = 8 * 1_024 * 1_024
_APPROVED_BINARY_ASSETS = {
    "docs/assets/humanlike-hero.jpg": (
        "d73b67fc9565409eada12c344694c95149f8df8c6277b4b2fbe64c5121636814"
    ),
}


def _private_identifiers() -> tuple[str, ...]:
    # Split literals keep the gate from reporting its own denylist.
    return (
        "Алек" + "сей",
        "Хэ" + "нк",
        "Quote " + "Atlas",
        "MIKE" + "_CENTER",
        "aleksej" + "ulanov",
    )


def _content_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    local_home = (
        r"(?:/"
        + "Users"
        + r"/[^/\s]+|/"
        + "home"
        + r"/[^/\s]+|[A-Za-z]:[\\/]"
        + "Users"
        + r"[\\/][^\\/\s]+)"
    )
    private_key = "-----BEGIN " + r"(?:[A-Z0-9]+ )?PRIVATE KEY-----"
    return (
        ("local-home-path", re.compile(local_home)),
        ("private-key", re.compile(private_key)),
        (
            "credential",
            re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}(?![A-Za-z0-9])"),
        ),
        (
            "credential",
            re.compile(r"(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}(?![A-Za-z0-9_])"),
        ),
        ("credential", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
        (
            "credential",
            re.compile(r"(?<![A-Za-z0-9])(?:sk|xox[baprs])[-_][A-Za-z0-9_-]{20,}"),
        ),
        (
            "credential",
            re.compile(
                r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
                r"password|private[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9/+_.-]{16,}"
            ),
        ),
    )


@dataclass(frozen=True, order=True)
class Finding:
    scope: str
    path: str
    line: int
    rule: str

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.scope}:{location}: {self.rule}"


def _path_rules(path: PurePosixPath) -> list[str]:
    rules: list[str] = []
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if parts & _FORBIDDEN_TREE_PARTS:
        rules.append("forbidden-artifact")
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        rules.append("forbidden-artifact")
    if any(name.endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES) or ".db-" in name:
        rules.append("forbidden-artifact")
    if name == "coverage.xml" or name == ".ds_store" or name.endswith(".egg-info"):
        rules.append("forbidden-artifact")
    lowered = path.as_posix().casefold()
    if any(identifier.casefold() in lowered for identifier in _private_identifiers()):
        rules.append("private-identifier")
    return sorted(set(rules))


def _content_findings(data: bytes, *, scope: str, path: str) -> list[Finding]:
    if len(data) > _MAX_SCANNED_BYTES:
        return [Finding(scope, path, 0, "oversized-artifact")]
    approved_digest = _APPROVED_BINARY_ASSETS.get(path)
    if (
        approved_digest is not None
        and data.startswith(b"\xff\xd8\xff")
        and data.endswith(b"\xff\xd9")
        and hashlib.sha256(data).hexdigest() == approved_digest
    ):
        return []
    if b"\0" in data:
        return [Finding(scope, path, 0, "binary-artifact")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Finding(scope, path, 0, "binary-artifact")]

    findings: list[Finding] = []
    for rule, pattern in _content_patterns():
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(scope, path, line, rule))
    folded = text.casefold()
    for identifier in _private_identifiers():
        start = 0
        needle = identifier.casefold()
        while True:
            position = folded.find(needle, start)
            if position < 0:
                break
            line = text.count("\n", 0, position) + 1
            findings.append(Finding(scope, path, line, "private-identifier"))
            start = position + len(needle)
    return findings


def _worktree_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        retained_directories: list[str] = []
        for name in directory_names:
            child = current_path / name
            if child.is_symlink():
                relative = child.relative_to(root).as_posix()
                findings.append(Finding("worktree", relative, 0, "symlink"))
            elif name in _IGNORED_WORKTREE_DIRECTORIES or name.endswith(".egg-info"):
                continue
            else:
                retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in file_names:
            candidate = current_path / name
            relative = candidate.relative_to(root)
            portable = PurePosixPath(relative.as_posix())
            for rule in _path_rules(portable):
                findings.append(Finding("worktree", portable.as_posix(), 0, rule))
            if candidate.is_symlink():
                findings.append(Finding("worktree", portable.as_posix(), 0, "symlink"))
                continue
            try:
                data = candidate.read_bytes()
            except OSError:
                findings.append(Finding("worktree", portable.as_posix(), 0, "unreadable"))
                continue
            findings.extend(
                _content_findings(data, scope="worktree", path=portable.as_posix())
            )
    return findings


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
    )


def _reachable_head_entries(root: Path) -> set[tuple[str, str, str, str]]:
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != b"true":
        return set()
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        return set()
    commits = _git(root, "rev-list", "HEAD")
    if commits.returncode != 0:
        raise RuntimeError("unable to enumerate reachable HEAD commits")
    result: set[tuple[str, str, str, str]] = set()
    for raw_commit in commits.stdout.splitlines():
        try:
            commit = raw_commit.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Git returned an invalid commit identifier") from error
        tree = _git(root, "ls-tree", "-r", "-z", "--full-tree", commit)
        if tree.returncode != 0:
            raise RuntimeError("unable to enumerate a reachable Git tree")
        for raw_entry in tree.stdout.split(b"\0"):
            if not raw_entry:
                continue
            metadata, separator, raw_path = raw_entry.partition(b"\t")
            fields = metadata.split(b" ")
            if not separator or len(fields) != 3:
                raise RuntimeError("Git returned an invalid tree entry")
            raw_mode, raw_type, raw_object_id = fields
            try:
                mode = raw_mode.decode("ascii")
                object_type = raw_type.decode("ascii")
                object_id = raw_object_id.decode("ascii")
                path = raw_path.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RuntimeError("reachable Git history contains a non-UTF-8 path") from error
            result.add((object_id, object_type, mode, path))
    return result


def _history_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    blob_cache: dict[str, bytes] = {}
    for object_id, object_type, mode, path in _reachable_head_entries(root):
        portable = PurePosixPath(path)
        for rule in _path_rules(portable):
            findings.append(Finding("history", path, 0, rule))
        if mode == "120000":
            findings.append(Finding("history", path, 0, "symlink"))
            continue
        if object_type != "blob":
            continue
        if object_id not in blob_cache:
            blob = _git(root, "cat-file", "blob", object_id)
            if blob.returncode != 0:
                raise RuntimeError("unable to inspect a reachable Git blob")
            blob_cache[object_id] = blob.stdout
        findings.extend(_content_findings(blob_cache[object_id], scope="history", path=path))
    return findings


def scan(root: Path) -> list[Finding]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("scan root must be a directory")
    return sorted(set(_worktree_findings(resolved) + _history_findings(resolved)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        findings = scan(arguments.root)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"privacy gate error: {error}")
        return 2
    if findings:
        print(f"privacy gate failed: {len(findings)} finding(s)")
        for finding in findings:
            print(f"- {finding.render()}")
        return 1
    print("privacy gate passed: worktree and reachable HEAD history are clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
