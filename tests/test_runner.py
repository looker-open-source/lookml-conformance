from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

from lookml_conformance.cases import load_case
from lookml_conformance.judge import Outcome
from lookml_conformance.runner import (
    AdapterSpec,
    RegistryError,
    load_registry,
    parse_output,
    run_suite,
    select_adapters,
)
from tests.conftest import MakeCase

PASSING_OUTPUT = {
    "adapter": "fake",
    "version": "9.9",
    "models": {"m": {"views": {"orders": {"sql_table_name": "raw.orders"}}}},
}


def script(tmp_path: Path, body: str, name: str = "adapter.py") -> tuple[str, ...]:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return (sys.executable, str(path))


def printing(tmp_path: Path, output: object) -> tuple[str, ...]:
    return script(tmp_path, f"import json\nprint('noise')\nprint(json.dumps({output!r}))\n")


def test_parse_output_uses_the_last_line() -> None:
    output = parse_output("fake", "log line\n" + json.dumps(PASSING_OUTPUT) + "\n")

    assert output.version == "9.9"
    assert output.error is None


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("", "printed nothing on stdout; stderr: Traceback"),
        ("not json", "last stdout line is not JSON: 'not json'"),
        ('{"adapter": ""}', "output does not follow the protocol: 'adapter' must be a non-empty string"),
    ],
)
def test_parse_output_failures(stdout: str, message: str) -> None:
    output = parse_output("fake", stdout, "Traceback")

    assert output.adapter == "fake"
    assert output.error is not None
    assert output.error.startswith(message)


def test_invoke_passes_the_project_as_last_argument(tmp_path: Path) -> None:
    command = script(
        tmp_path, "import json, sys\nprint(json.dumps({'adapter': 'fake', 'version': sys.argv[-1]}))\n"
    )
    project = tmp_path / "project"
    project.mkdir()

    output = AdapterSpec("fake", command).invoke(project)

    assert output.version == str(project.resolve())


def test_invoke_sets_env_and_cwd(tmp_path: Path) -> None:
    body = (
        "import json, os\n"
        "print(json.dumps({'adapter': 'fake', 'version': os.environ['X'] + '|' + os.getcwd()}))\n"
    )
    spec = AdapterSpec("fake", script(tmp_path, body), env={"X": "value"}, cwd=tmp_path)

    assert spec.invoke(tmp_path).version == f"value|{tmp_path}"


def test_invoke_reports_missing_executable(tmp_path: Path) -> None:
    output = AdapterSpec("fake", ("/nonexistent/tool",)).invoke(tmp_path)

    assert output.error is not None
    assert output.error.startswith("cannot run '/nonexistent/tool'")


def test_invoke_reports_timeouts(tmp_path: Path) -> None:
    spec = AdapterSpec("fake", script(tmp_path, "import time\ntime.sleep(5)\n"), timeout=0.2)

    assert spec.invoke(tmp_path).error == "timed out after 0.2s"


def test_invoke_reports_crashes_with_stderr(tmp_path: Path) -> None:
    output = AdapterSpec("fake", script(tmp_path, "raise SystemExit('boom')\n")).invoke(tmp_path)

    assert output.error == "printed nothing on stdout; stderr: boom"


def test_load_registry(tmp_path: Path) -> None:
    registry = tmp_path / "adapters.json"
    registry.write_text(
        json.dumps(
            {
                "adapters": [
                    {
                        "name": "a",
                        "command": ["python", "-m", "x"],
                        "label": "A",
                        "kind": "Parser",
                        "language": "Python",
                        "url": "https://example.com",
                        "env": {"K": "V"},
                        "timeout": 10,
                    },
                    {"name": "b", "command": ["node", "b.js"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    a, b = load_registry(registry)

    assert a == AdapterSpec(
        name="a",
        command=("python", "-m", "x"),
        env={"K": "V"},
        cwd=tmp_path.resolve(),
        timeout=10,
        label="A",
        kind="Parser",
        language="Python",
        url="https://example.com",
    )
    assert b.display_name == "b"


@pytest.mark.parametrize("content", ["{", '{"adapters": [{"name": "a"}]}', "[]"])
def test_load_registry_errors(tmp_path: Path, content: str) -> None:
    registry = tmp_path / "adapters.json"
    registry.write_text(content, encoding="utf-8")

    with pytest.raises(RegistryError):
        load_registry(registry)


def test_select_adapters_keeps_registry_order() -> None:
    adapters = [AdapterSpec("a", ("a",)), AdapterSpec("b", ("b",)), AdapterSpec("c", ("c",))]

    assert [adapter.name for adapter in select_adapters(adapters, ["c", "a"])] == ["a", "c"]
    with pytest.raises(RegistryError, match="unknown adapter"):
        select_adapters(adapters, ["d"])


def test_run_suite_collects_verdicts_and_versions(tmp_path: Path, make_case: MakeCase) -> None:
    cases = [load_case(make_case(id="r01_a")), load_case(make_case(id="r02_b"))]
    good = AdapterSpec("good", printing(tmp_path, PASSING_OUTPUT))
    bad_output = {"adapter": "bad", "version": "1.0", "models": {}}
    bad = AdapterSpec("bad", script(tmp_path, f"import json\nprint(json.dumps({bad_output!r}))\n", "bad.py"))
    seen: list[tuple[str, str, Outcome]] = []

    scorecard = run_suite(
        cases,
        [good, bad],
        jobs=4,
        date=dt.date(2026, 1, 2),
        progress=lambda case, adapter, verdict: seen.append((case.id, adapter.name, verdict.outcome)),
    )

    assert scorecard.date == "2026-01-02"
    assert [(run.name, run.version) for run in scorecard.adapters] == [("good", "9.9"), ("bad", "1.0")]
    assert [result.case_id for result in scorecard.results] == ["r01_a", "r02_b"]
    assert {result.verdicts["good"].outcome for result in scorecard.results} == {Outcome.PASS}
    assert {result.verdicts["bad"].outcome for result in scorecard.results} == {Outcome.FAIL}
    assert sorted(seen) == [
        ("r01_a", "bad", Outcome.FAIL),
        ("r01_a", "good", Outcome.PASS),
        ("r02_b", "bad", Outcome.FAIL),
        ("r02_b", "good", Outcome.PASS),
    ]
    assert scorecard.failed


def test_run_suite_version_is_none_when_every_run_fails(tmp_path: Path, make_case: MakeCase) -> None:
    scorecard = run_suite([load_case(make_case())], [AdapterSpec("x", ("/nonexistent",))])

    assert scorecard.adapters[0].version is None
    assert scorecard.results[0].verdicts["x"].outcome is Outcome.ERROR
