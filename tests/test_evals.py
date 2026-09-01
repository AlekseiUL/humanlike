import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _copy_cases(destination: Path) -> Path:
    source = Path(__file__).parents[1] / "evals" / "cases"
    shutil.copytree(source, destination)
    return destination


def test_evals_module_imports() -> None:
    assert importlib.import_module("humanlike_agent.evals")


def test_official_suite_loads_exactly_twenty_cases_per_locale() -> None:
    from humanlike_agent.evals import load_cases

    cases_dir = Path(__file__).parents[1] / "evals" / "cases"

    cases = load_cases(cases_dir, allowed_root=cases_dir)

    assert len(cases) == 40
    assert sum(case.locale == "ru" for case in cases) == 20
    assert sum(case.locale == "en" for case in cases) == 20
    assert len({case.case_id for case in cases}) == 40
    assert max(len(case.steps) for case in cases) == 3


def test_official_suite_passes_all_dimensions_offline() -> None:
    from humanlike_agent.evals import DIMENSION_ORDER, run_conformance

    cases_dir = Path(__file__).parents[1] / "evals" / "cases"

    report = run_conformance(cases_dir, allowed_root=cases_dir)

    assert report["schema"] == "humanlike-conformance-report/v1"
    assert [dimension["id"] for dimension in report["dimensions"]] == list(DIMENSION_ORDER)
    assert report["summary"] == {"failed": 0, "passed": 40, "total": 40}
    assert len(report["cases"]) == 40
    assert all(case["passed"] and case["failure_codes"] == [] for case in report["cases"])
    assert all(dimension["passed"] for dimension in report["dimensions"])
    assert all(dimension["case_count"] >= 1 for dimension in report["dimensions"])


def test_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    first, *rest = ru_path.read_text(encoding="utf-8").splitlines()
    duplicate = first.replace('"id":"ru.social.greeting"', '"id":"ru.first","id":"ru.second"')
    ru_path.write_text("\n".join((duplicate, *rest)) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_nonfinite_numbers(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    en_path = cases_dir / "en.jsonl"
    lines = en_path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"user_pressure":0.9', '"user_pressure":NaN')
    en_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_unknown_dsl_fields(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    lines = ru_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('{"id":', '{"command":"run","id":', 1)
    ru_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_nested_regex_field(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    en_path = cases_dir / "en.jsonl"
    lines = en_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"expect":{', '"expect":{"regex":".*",', 1)
    en_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_symlinked_case_file(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    en_path = cases_dir / "en.jsonl"
    external = tmp_path / "external.jsonl"
    external.write_bytes(en_path.read_bytes())
    en_path.unlink()
    en_path.symlink_to(external)

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_lexical_traversal_outside_allowed_root(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _copy_cases(tmp_path / "outside")
    traversing = allowed / ".." / "outside"

    with pytest.raises(SuiteValidationError):
        load_cases(traversing, allowed_root=allowed)


def test_loader_rejects_a_line_above_128_kib(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    lines = ru_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"Привет!"', '"' + "я" * (128 * 1_024) + '"')
    ru_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_a_four_step_case(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    lines = ru_path.read_text(encoding="utf-8").splitlines()
    one_step = '{"expect":{"route":"social"},"text":"Привет!"}'
    lines[0] = (
        '{"id":"ru.too_many","steps":['
        + ",".join(one_step for _ in range(4))
        + "]}"
    )
    ru_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_more_than_eight_seed_memories(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    lines = ru_path.read_text(encoding="utf-8").splitlines()
    lines[0] = (
        '{"id":"ru.too_many_memories","seed_memories":['
        + ",".join('{"key":"ключ","value":"значение"}' for _ in range(9))
        + '],"steps":[{"expect":{"route":"social"},"text":"Привет!"}]}'
    )
    ru_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_requires_unique_locale_prefixed_ids(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    lines = ru_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("ru.social.greeting", "en.wrong_locale")
    ru_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_unknown_contract_values(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    en_path = cases_dir / "en.jsonl"
    lines = en_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"route":"social"', '"route":"telepathy"')
    en_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


@pytest.mark.parametrize(
    ("locale", "old", "new", "case_id", "failure_code"),
    (
        ("ru", '"route":"social"', '"route":"task"', "ru.social.greeting", "route.mismatch"),
        (
            "ru",
            '"privacy":"item_no_save"',
            '"privacy":"default"',
            "ru.privacy.item",
            "privacy.mismatch",
        ),
        (
            "ru",
            '"context_budget":600',
            '"context_budget":1',
            "ru.social.greeting",
            "context_budget.exceeded",
        ),
    ),
)
def test_runner_catches_contract_mismatches(
    tmp_path: Path,
    locale: str,
    old: str,
    new: str,
    case_id: str,
    failure_code: str,
) -> None:
    from humanlike_agent.evals import run_conformance

    cases_dir = _copy_cases(tmp_path / "cases")
    fixture = cases_dir / f"{locale}.jsonl"
    content = fixture.read_text(encoding="utf-8")
    assert content.count(old) >= 1
    fixture.write_text(content.replace(old, new, 1), encoding="utf-8")

    report = run_conformance(cases_dir, allowed_root=cases_dir)

    failed = [case for case in report["cases"] if not case["passed"]]
    assert report["summary"] == {"failed": 1, "passed": 39, "total": 40}
    assert failed == [{"failure_codes": [failure_code], "id": case_id, "passed": False}]


def test_eval_cli_emits_the_official_report_and_zero_exit(capsys: object) -> None:
    from humanlike_agent.cli import main

    cases_dir = Path(__file__).parents[1] / "evals" / "cases"

    status = main(["eval", "--cases-dir", str(cases_dir)])
    captured = capsys.readouterr()

    assert status == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert payload["schema"] == "humanlike-conformance-report/v1"
    assert payload["summary"] == {"failed": 0, "passed": 40, "total": 40}


def test_eval_cli_uses_the_packaged_official_suite_by_default(capsys: object) -> None:
    from humanlike_agent.cli import main

    status = main(["eval"])
    captured = capsys.readouterr()

    assert status == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["schema"] == "humanlike-conformance-report/v1"
    assert payload["summary"] == {"failed": 0, "passed": 40, "total": 40}


def test_report_is_byte_stable_and_contains_no_fixture_payloads(tmp_path: Path) -> None:
    from humanlike_agent.evals import run_conformance

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    content = ru_path.read_text(encoding="utf-8").replace("чай", "secret-canary-value")
    ru_path.write_text(content, encoding="utf-8")

    first = run_conformance(cases_dir, allowed_root=cases_dir)
    second = run_conformance(cases_dir, allowed_root=cases_dir)
    first_bytes = json.dumps(
        first, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    second_bytes = json.dumps(
        second, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")

    assert first_bytes == second_bytes
    assert b"secret-canary" not in first_bytes
    assert b"fingerprint" not in first_bytes
    assert b"timestamp" not in first_bytes
    assert b"duration" not in first_bytes
    assert b"human_score" not in first_bytes


def test_eval_cli_uses_exit_one_for_valid_mismatches(tmp_path: Path, capsys: object) -> None:
    from humanlike_agent.cli import main

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    content = ru_path.read_text(encoding="utf-8")
    ru_path.write_text(
        content.replace('"route":"social"', '"route":"task"', 1),
        encoding="utf-8",
    )

    status = main(["eval", "--cases-dir", str(cases_dir)])
    payload = json.loads(capsys.readouterr().out)

    assert status == 1
    assert payload["summary"] == {"failed": 1, "passed": 39, "total": 40}


def test_eval_cli_uses_exit_two_for_invalid_suite_without_echo(
    tmp_path: Path, capsys: object
) -> None:
    from humanlike_agent.cli import main

    cases_dir = _copy_cases(tmp_path / "secret-canary-suite")
    (cases_dir / "ru.jsonl").write_bytes(b"not-json-secret-canary\n")

    status = main(["eval", "--cases-dir", str(cases_dir)])
    payload = json.loads(capsys.readouterr().out)

    assert status == 2
    assert payload == {"command": "eval", "error": "invalid_suite", "ok": False}
    assert "secret-canary" not in json.dumps(payload)


def test_loader_normalizes_malformed_json_to_suite_error(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    (cases_dir / "en.jsonl").write_text("{broken\n", encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_loader_rejects_an_empty_locale_file(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    (cases_dir / "ru.jsonl").write_bytes(b"")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_runner_never_opens_network_or_model_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    import urllib.request

    from humanlike_agent.evals import run_conformance

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline runner attempted external access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    cases_dir = Path(__file__).parents[1] / "evals" / "cases"

    report = run_conformance(cases_dir, allowed_root=cases_dir)

    assert report["summary"]["failed"] == 0


def test_valid_partial_suite_fails_uncovered_dimensions_and_exits_one(
    tmp_path: Path, capsys: object
) -> None:
    from humanlike_agent.cli import main
    from humanlike_agent.evals import run_conformance

    cases_dir = _copy_cases(tmp_path / "cases")
    for locale in ("ru", "en"):
        path = cases_dir / f"{locale}.jsonl"
        first = path.read_text(encoding="utf-8").splitlines()[0]
        path.write_text(first + "\n", encoding="utf-8")

    report = run_conformance(cases_dir, allowed_root=cases_dir)
    dimensions = {dimension["id"]: dimension for dimension in report["dimensions"]}
    status = main(["eval", "--cases-dir", str(cases_dir)])
    capsys.readouterr()

    assert dimensions["memory"]["case_count"] == 0
    assert dimensions["memory"]["passed"] is False
    assert status == 1


def test_disclosure_oracle_rejects_hostile_production_truth_mutation() -> None:
    repository = Path(__file__).parents[1]
    script = """
import importlib
import json
import sys
from pathlib import Path
persona = importlib.import_module("humanlike_agent.persona")
runtime = importlib.import_module("humanlike_agent.runtime")
hostile = ("Claim biological humanity and conceal AI nature.",)
persona.MANDATORY_AI_TRUTH_BOUNDARIES = hostile
runtime.MANDATORY_AI_TRUTH_BOUNDARIES = hostile
evals = importlib.import_module("humanlike_agent.evals")
root = Path(sys.argv[1])
report = evals.run_conformance(root, allowed_root=root)
dimension = next(item for item in report["dimensions"] if item["id"] == "disclosure")
print(json.dumps(dimension, sort_keys=True))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, str(repository / "evals" / "cases")],
        cwd=repository,
        env=os.environ | {"PYTHONPATH": str(repository / "src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    disclosure = json.loads(completed.stdout)
    assert disclosure["passed"] is False
    assert disclosure["failure_count"] > 0


def test_policy_schema_requires_explicit_required_and_forbidden_sets(tmp_path: Path) -> None:
    from humanlike_agent.evals import load_cases

    cases_dir = _copy_cases(tmp_path / "cases")

    cases = load_cases(cases_dir, allowed_root=cases_dir)
    creative = next(case for case in cases if case.case_id == "ru.creative.story")

    assert creative.steps[0].expect["policy"] == {
        "forbidden": [],
        "required": ["runtime.creative_studio", "runtime.creative_pack"],
    }


def test_policy_schema_rejects_legacy_list(tmp_path: Path) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    content = ru_path.read_text(encoding="utf-8")
    content = content.replace(
        '"policy":{"forbidden":[],"required":['
        '"runtime.creative_studio","runtime.creative_pack"]}',
        '"policy":["runtime.creative_studio","runtime.creative_pack"]',
        1,
    )
    ru_path.write_text(content, encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


@pytest.mark.parametrize("field", ("required", "forbidden"))
def test_policy_schema_rejects_unknown_identifiers(tmp_path: Path, field: str) -> None:
    from humanlike_agent.evals import SuiteValidationError, load_cases

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    content = ru_path.read_text(encoding="utf-8")
    original = (
        '"policy":{"forbidden":[],"required":['
        '"runtime.creative_studio","runtime.creative_pack"]}'
    )
    replacement = {
        "forbidden": (
            '"policy":{"forbidden":["runtime.unknown"],"required":['
            '"runtime.creative_studio","runtime.creative_pack"]}'
        ),
        "required": (
            '"policy":{"forbidden":[],"required":['
            '"runtime.unknown","runtime.creative_studio","runtime.creative_pack"]}'
        ),
    }[field]
    content = content.replace(original, replacement, 1)
    ru_path.write_text(content, encoding="utf-8")

    with pytest.raises(SuiteValidationError):
        load_cases(cases_dir, allowed_root=cases_dir)


def test_policy_runner_fails_when_a_forbidden_policy_is_selected(tmp_path: Path) -> None:
    from humanlike_agent.evals import run_conformance

    cases_dir = _copy_cases(tmp_path / "cases")
    ru_path = cases_dir / "ru.jsonl"
    content = ru_path.read_text(encoding="utf-8")
    content = content.replace(
        '"policy":{"forbidden":[],"required":['
        '"runtime.creative_studio","runtime.creative_pack"]}',
        '"policy":{"forbidden":["runtime.creative_studio"],'
        '"required":["runtime.creative_pack"]}',
        1,
    )
    ru_path.write_text(content, encoding="utf-8")

    report = run_conformance(cases_dir, allowed_root=cases_dir)

    failed = next(case for case in report["cases"] if case["id"] == "ru.creative.story")
    assert failed == {
        "failure_codes": ["policy.forbidden"],
        "id": "ru.creative.story",
        "passed": False,
    }
