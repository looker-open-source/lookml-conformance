# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
    parse_outputs,
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


BATCH_ADAPTER = """\
import json, sys
log, crash_after = {log!r}, {crash_after!r}
with open(log, "a") as handle:
    handle.write(str(len(sys.argv) - 1) + "\\n")
print("tool log line")
for index, project in enumerate(sys.argv[1:]):
    if crash_after is not None and index >= crash_after and len(sys.argv) > 2:
        raise SystemExit("crashed part-way")
    print(json.dumps({{"adapter": "fake", "version": "2", "project": project,
                      "models": {{"m": {{"views": {{"orders": {{"sql_table_name": "raw.orders"}}}}}}}}}}))
"""


def batch_adapter(tmp_path: Path, crash_after: int | None = None) -> tuple[AdapterSpec, Path]:
    log = tmp_path / "calls.log"
    body = BATCH_ADAPTER.format(log=str(log), crash_after=crash_after)
    return AdapterSpec("fake", script(tmp_path, body, "batch.py")), log


def calls(log: Path) -> list[int]:
    return [int(line) for line in log.read_text(encoding="utf-8").split()]


def projects(tmp_path: Path, count: int) -> list[Path]:
    paths = [tmp_path / f"p{index}" for index in range(count)]
    for path in paths:
        path.mkdir()
    return paths


def test_invoke_many_pairs_lines_with_projects(tmp_path: Path) -> None:
    spec, log = batch_adapter(tmp_path)
    paths = projects(tmp_path, 3)

    outputs = spec.invoke_many(paths)

    assert set(outputs) == {path.resolve() for path in paths}
    assert {output.project for output in outputs.values()} == {str(path.resolve()) for path in paths}
    assert calls(log) == [3]


def test_invoke_many_retries_projects_a_crashed_batch_missed(tmp_path: Path) -> None:
    spec, log = batch_adapter(tmp_path, crash_after=1)
    paths = projects(tmp_path, 3)

    outputs = spec.invoke_many(paths)

    assert all(output.error is None for output in outputs.values())
    assert calls(log) == [3, 1, 1]


def test_invoke_many_falls_back_for_single_project_adapters(tmp_path: Path) -> None:
    log = tmp_path / "calls.log"
    body = (
        "import json, sys\n"
        f"open({str(log)!r}, 'a').write(str(len(sys.argv) - 1) + '\\n')\n"
        "print(json.dumps({'adapter': 'old', 'version': sys.argv[-1]}))\n"
    )
    spec = AdapterSpec("old", script(tmp_path, body))
    paths = projects(tmp_path, 2)

    outputs = spec.invoke_many(paths)

    assert calls(log) == [2, 1, 1]
    assert {output.version for output in outputs.values()} == {str(path.resolve()) for path in paths}


def test_invoke_many_retries_after_a_batch_timeout(tmp_path: Path) -> None:
    body = 'import sys, time\nif len(sys.argv) > 2:\n    time.sleep(5)\nprint(\'{"adapter": "slow"}\')\n'
    spec = AdapterSpec("slow", script(tmp_path, body), timeout=0.5)

    outputs = spec.invoke_many(projects(tmp_path, 2))

    assert [output.error for output in outputs.values()] == [None, None]


def test_invoke_many_reports_missing_executable_for_every_project(tmp_path: Path) -> None:
    outputs = AdapterSpec("x", ("/nonexistent/tool",)).invoke_many(projects(tmp_path, 2))

    assert all(output.error and output.error.startswith("cannot run") for output in outputs.values())


def test_parse_outputs_reports_protocol_errors_per_project(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    stdout = "\n".join([
        json.dumps({"adapter": "x", "project": str(good)}),
        json.dumps({"adapter": "x", "project": str(bad), "models": []}),
        json.dumps({"adapter": "x", "project": "/elsewhere"}),
        "[1, 2]",
    ])  # fmt: skip

    outputs = parse_outputs("x", stdout, "", [good, bad])

    assert outputs[good].error is None
    assert outputs[bad].error == "output does not follow the protocol: models must be an object"
    assert set(outputs) == {good, bad}


def test_run_suite_batches_cases_per_adapter(tmp_path: Path, make_case: MakeCase) -> None:
    cases = [load_case(make_case(id=f"r0{index}_c")) for index in range(1, 6)]
    spec, log = batch_adapter(tmp_path)

    scorecard = run_suite(cases, [spec], jobs=2)

    assert sorted(calls(log)) == [2, 3]
    assert {result.verdicts["fake"].outcome for result in scorecard.results} == {Outcome.PASS}


def test_run_suite_without_batching_runs_one_case_per_process(tmp_path: Path, make_case: MakeCase) -> None:
    cases = [load_case(make_case(id=f"r0{index}_c")) for index in range(1, 4)]
    spec, log = batch_adapter(tmp_path)

    run_suite(cases, [spec], jobs=2, batch=False)
    run_suite(cases, [AdapterSpec(spec.name, spec.command, batch=False)], jobs=2)

    assert calls(log) == [1] * 6


def test_load_registry_reads_the_batch_flag(tmp_path: Path) -> None:
    registry = tmp_path / "adapters.json"
    registry.write_text(json.dumps({"adapters": [{"name": "a", "command": ["x"], "batch": False}]}))

    assert load_registry(registry)[0].batch is False
