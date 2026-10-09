"""Re-run each registry adapter whose tool is installed and compare with the published scorecard.

Opt in with ``pytest -m integration`` after ``lookml-conformance setup``. Adapters whose environment
is missing are skipped.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from lookml_conformance.cases import load_cases
from lookml_conformance.judge import Outcome
from lookml_conformance.runner import AdapterSpec, load_registry, run_suite
from lookml_conformance.scorecard import Scorecard
from tests.conftest import CASES_ROOT, REPO_ROOT

REGISTRY = load_registry(REPO_ROOT / "adapters.json")
PUBLISHED = Scorecard.from_dict(
    json.loads((REPO_ROOT / "results" / "latest.json").read_text(encoding="utf-8"))
)


def installed(adapter: AdapterSpec) -> bool:
    executable = Path(adapter.command[0])
    paths = [executable, *(Path(value) for value in adapter.env.values())]
    return all((REPO_ROOT / path).exists() for path in paths if not path.is_absolute() and "/" in str(path))


@pytest.mark.integration
@pytest.mark.parametrize("adapter", REGISTRY, ids=lambda adapter: adapter.name)
def test_adapter_reproduces_the_published_scorecard(adapter: AdapterSpec) -> None:
    if not installed(adapter):
        pytest.skip(f"{adapter.name} is not installed; run: lookml-conformance setup {adapter.name}")

    scorecard = run_suite(load_cases(CASES_ROOT), [adapter], jobs=4)

    published_version = next(run.version for run in PUBLISHED.adapters if run.name == adapter.name)
    assert scorecard.adapters[0].version == published_version
    outcomes = {result.case_id: result.verdicts[adapter.name] for result in scorecard.results}
    assert [case for case, verdict in outcomes.items() if verdict.outcome is Outcome.ERROR] == []
    assert {case: verdict.outcome for case, verdict in outcomes.items()} == {
        result.case_id: result.verdicts[adapter.name].outcome for result in PUBLISHED.results
    }


@pytest.mark.integration
@pytest.mark.parametrize("adapter", REGISTRY, ids=lambda adapter: adapter.name)
def test_adapter_output_matches_the_schema(adapter: AdapterSpec) -> None:
    if not installed(adapter):
        pytest.skip(f"{adapter.name} is not installed; run: lookml-conformance setup {adapter.name}")
    from jsonschema import Draft202012Validator

    schema = json.loads((REPO_ROOT / "docs" / "adapter-output.schema.json").read_text(encoding="utf-8"))
    projects = [str(case.project.resolve()) for case in load_cases(CASES_ROOT)]
    env = os.environ | {key: str(REPO_ROOT / value) for key, value in adapter.env.items()}

    completed = subprocess.run(
        [*adapter.command, *projects], capture_output=True, text=True, cwd=REPO_ROOT, env=env, check=True
    )

    outputs = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert [output["project"] for output in outputs] == projects
    for output in outputs:
        Draft202012Validator(schema).validate(output)
