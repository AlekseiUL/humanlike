"""Export the installed runtime as a dependency-free native directory plugin."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

from . import __version__


def export_plugin(target: Path) -> None:
    """Create a NEW directory; never overwrite, install, enable or read host state.

    Copy only shipped Python and JSON resources, not bytecode, tests or local
    settings. The caller owns the parent directory. A failure leaves an explicitly
    incomplete new directory for inspection, never deletes an existing target.
    """
    target = Path(os.path.abspath(target))
    if target.parent.resolve(strict=True) != target.parent or target.is_symlink():
        raise ValueError("export parent must not contain symlinks")
    target.mkdir(mode=0o700, exist_ok=False)

    def copy_tree(source, destination):
        destination.mkdir(mode=0o700)
        for child in sorted(source.iterdir(), key=lambda p: p.name):
            if child.name.startswith(".") or child.name == "__pycache__":
                continue
            if child.is_dir():
                copy_tree(child, destination / child.name)
            elif child.name.endswith((".py", ".json", ".jsonl")):
                output = destination / child.name
                output.write_bytes(child.read_bytes())
                output.chmod(0o600)

    copy_tree(files("humanlike_agent"), target / "humanlike_agent")
    (target / "__init__.py").write_text(
        '"""Native Humanlike plugin; memory remains off until consent."""\n'
        "from .humanlike_agent.hermes_plugin import register\n",
        encoding="utf-8",
    )
    (target / "plugin.yaml").write_text(
        f'manifest_version: 1\nname: humanlike-agent-kit\nversion: "{__version__}"\n'
        "description: Local consented RU/EN memory and conversational behavior.\n"
        "kind: standalone\nprovides_hooks:\n  - pre_llm_call\n"
        "  - transform_llm_output\n  - post_llm_call\n  - on_session_finalize\n"
        "  - post_gateway_admission\n",
        encoding="utf-8",
    )
