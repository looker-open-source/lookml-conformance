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

import json
from pathlib import Path

import pytest

from lookml_conformance.cases import load_case, load_cases
from lookml_conformance.cli import EXIT_FAILURES, EXIT_OK, EXIT_USAGE, main
from lookml_conformance.judge import Outcome, Verdict
from lookml_conformance.runner import AdapterSpec, load_registry
from lookml_conformance.scorecard import AdapterRun, CaseResult, Scorecard
from lookml_conformance.site import build_site_data, render_site_data
from tests.conftest import CASES_ROOT, REPO_ROOT, MakeCase


def scorecard_for(case_ids: list[str]) -> Scorecard:
    return Scorecard(
        date="2026-10-09",
        adapters=(AdapterRun("tool", "1.0"), AdapterRun("unregistered", None)),
        results=tuple(
            CaseResult(
                case_id,
                "refinements",
                "confirmed",
                {"tool": Verdict(Outcome.FAIL, ("m.orders.sql_table_name: expected 'a', got 'b'",)),
                 "unregistered": Verdict(Outcome.PASS)},
            )
            for case_id in case_ids
        ),
    )  # fmt: skip


def test_build_site_data(make_case: MakeCase) -> None:
    case = load_case(make_case())
    spec = AdapterSpec(
        "tool", ("x",), label="Tool", kind="Parser", language="Go", install={"pip": "tool==1.0"}
    )

    data = build_site_data([case], scorecard_for([case.id]), [spec])

    assert data["date"] == "2026-10-09"
    assert data["suite"] == {"cases": 1, "confirmed": 1, "provisional": 0, "citations": 1, "pages": 1}
    assert data["categories"] == [{"id": "refinements", "title": "Refinements"}]
    tool, unregistered = data["tools"]
    assert tool["label"] == "Tool"
    assert tool["package"] == "tool==1.0"
    assert tool["score"]["all"] == {"passed": 0, "applicable": 1}
    assert tool["score"]["provisional"] == {"passed": 0, "applicable": 0}
    assert unregistered["label"] == "unregistered"
    assert unregistered["kind"] is None
    entry = data["cases"][0]
    assert entry["citations"][0]["label"] == "lookml-refinements#refinements_override_parameters"
    assert entry["expect"]["models"]["m"]["views"]["orders"] == {"sql_table_name": "raw.orders"}
    assert [file["path"] for file in entry["files"]] == ["m.model.lkml", "orders.view.lkml"]
    assert entry["verdicts"]["tool"]["outcome"] == "fail"
    assert json.loads(render_site_data(data)) == data


def test_build_site_data_needs_a_result_for_every_case(make_case: MakeCase) -> None:
    case = load_case(make_case())

    with pytest.raises(ValueError, match="no results for: r01_example"):
        build_site_data([case], scorecard_for([]), [])


def test_site_command_writes_and_checks(make_case: MakeCase, tmp_path: Path) -> None:
    case = load_case(make_case())
    scorecard = tmp_path / "s.json"
    scorecard.write_text(json.dumps(scorecard_for([case.id]).to_dict()), encoding="utf-8")
    registry = tmp_path / "adapters.json"
    registry.write_text(json.dumps({"adapters": [{"name": "tool", "command": ["x"]}]}), encoding="utf-8")
    output = tmp_path / "site" / "data.json"
    args = [
        "--cases",
        str(tmp_path / "cases"),
        "site",
        str(scorecard),
        "--registry",
        str(registry),
        "-o",
        str(output),
    ]

    assert main([*args, "--check"]) == EXIT_FAILURES
    assert main(args) == EXIT_OK
    assert main([*args, "--check"]) == EXIT_OK


def test_site_command_rejects_an_incomplete_scorecard(make_case: MakeCase, tmp_path: Path) -> None:
    make_case()
    scorecard = tmp_path / "s.json"
    scorecard.write_text(json.dumps(scorecard_for([]).to_dict()), encoding="utf-8")
    registry = tmp_path / "adapters.json"
    registry.write_text(json.dumps({"adapters": []}), encoding="utf-8")

    code = main(["--cases", str(tmp_path / "cases"), "site", str(scorecard), "--registry", str(registry)])

    assert code == EXIT_USAGE


def test_published_site_data_is_up_to_date() -> None:
    scorecard = Scorecard.from_dict(
        json.loads((REPO_ROOT / "results" / "latest.json").read_text(encoding="utf-8"))
    )
    data = build_site_data(load_cases(CASES_ROOT), scorecard, load_registry(REPO_ROOT / "adapters.json"))

    published = (REPO_ROOT / "site" / "data.json").read_text(encoding="utf-8")
    assert published == render_site_data(data), "run: lookml-conformance site"
