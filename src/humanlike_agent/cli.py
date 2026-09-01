"""Stable JSON command-line diagnostics for Humanlike Agent Kit."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .adapters.hermes import HermesAdapterConfig
from .evals import bundled_cases_dir, run_conformance
from .models import TurnInput
from .router import MAX_TURN_CHARS, route_turn


class _UsageError(ValueError):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError from None


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="humanlike", add_help=True)
    commands = parser.add_subparsers(dest="command", required=True)

    route = commands.add_parser("route", help="classify one bounded turn")
    route.add_argument("--text", required=True)
    route.add_argument("--locale", default="und")

    doctor = commands.add_parser("doctor", help="validate one rooted Hermes profile")
    doctor.add_argument("--config", required=True)

    evaluate = commands.add_parser("eval", help="run an offline conformance suite")
    evaluate.add_argument("--cases-dir")
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _run_route(arguments: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    text = arguments.text
    locale = arguments.locale
    if (
        not isinstance(text, str)
        or len(text) > MAX_TURN_CHARS
        or "\x00" in text
        or not isinstance(locale, str)
        or not 1 <= len(locale) <= 32
        or "\x00" in locale
    ):
        return 2, {"command": "route", "error": "invalid_input", "ok": False}
    try:
        decision = route_turn(TurnInput(text=text, locale=locale))
        return 0, {"command": "route", "ok": True, "route": decision.to_dict()}
    except Exception:
        return 2, {"command": "route", "error": "invalid_input", "ok": False}


def _run_doctor(arguments: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    raw_path = arguments.config
    try:
        if not isinstance(raw_path, str) or "\x00" in raw_path:
            raise ValueError("invalid path")
        lexical = Path(raw_path)
        if any(part == ".." for part in lexical.parts):
            raise ValueError("path traversal")
        config_path = Path(os.path.abspath(raw_path))
        config = HermesAdapterConfig.load(config_path, allowed_root=config_path.parent)
        config.build_runtime().snapshot()
    except Exception:
        return 2, {"command": "doctor", "error": "invalid_config", "ok": False}
    return 0, {
        "command": "doctor",
        "memory_enabled": config.state_path is not None,
        "ok": True,
        "profile_id": config.profile_id,
        "schema": "humanlike-hermes/v1",
    }


def _run_eval(arguments: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    raw_path = arguments.cases_dir
    try:
        if raw_path is None:
            cases_dir = bundled_cases_dir()
        else:
            if not isinstance(raw_path, str) or "\x00" in raw_path:
                raise ValueError("invalid path")
            lexical = Path(raw_path)
            if any(part == ".." for part in lexical.parts):
                raise ValueError("path traversal")
            cases_dir = Path(os.path.abspath(raw_path))
        report = run_conformance(cases_dir, allowed_root=cases_dir)
    except Exception:
        return 2, {"command": "eval", "error": "invalid_suite", "ok": False}
    passed = report["summary"]["failed"] == 0 and all(
        dimension["passed"] for dimension in report["dimensions"]
    )
    return (0 if passed else 1), report


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and emit exactly one stable JSON object."""

    try:
        arguments = _parser().parse_args(argv)
    except _UsageError:
        _emit({"command": "cli", "error": "invalid_arguments", "ok": False})
        return 2

    if arguments.command == "route":
        status, payload = _run_route(arguments)
    elif arguments.command == "doctor":
        status, payload = _run_doctor(arguments)
    elif arguments.command == "eval":
        status, payload = _run_eval(arguments)
    else:
        status = 2
        payload = {"command": "cli", "error": "invalid_arguments", "ok": False}
    _emit(payload)
    return status


__all__ = ["main"]
