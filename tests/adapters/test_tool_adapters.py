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

"""Run each registry adapter on small projects and check that it reports what its tool produces.

Opt in with ``pytest -m integration`` after ``lookml-conformance setup``. Adapters whose environment
is missing are skipped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lookml_conformance.cases import load_cases
from lookml_conformance.judge import Outcome
from lookml_conformance.runner import AdapterSpec, load_registry, run_suite
from tests.adapters.test_published_scorecard import installed
from tests.conftest import CASES_ROOT, REPO_ROOT

REGISTRY = {adapter.name: adapter for adapter in load_registry(REPO_ROOT / "adapters.json")}

ORDERS = """view: orders {
  sql_table_name: raw.orders ;;
  dimension: id { type: number sql: ${TABLE}.id ;; }
}
"""
INCLUDE_ORDERS = 'connection: "wh"\ninclude: "/views/orders.view.lkml"\n'


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def run(name: str, *projects: Path) -> list[dict[str, Any]]:
    adapter: AdapterSpec = REGISTRY[name]
    if not installed(adapter):
        pytest.skip(f"{name} is not installed; run: lookml-conformance setup {name}")
    if adapter.command[0] == "node" and shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    env = os.environ | {key: str(REPO_ROOT / value) for key, value in adapter.env.items()}
    completed = subprocess.run(
        [*adapter.command, *map(str, projects)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]


def listed(root: Path, pattern: str) -> list[str]:
    """File names in the order the file system lists them, as ``os.walk`` and ``Path.rglob`` see them."""
    return [path.name for path in root.rglob(pattern)]


def two_models(root: Path, refining_model: str, plain_model: str) -> Path:
    """Two models include orders; only one includes a refinement that adds a field."""
    return write(
        root,
        {
            f"{refining_model}.model.lkml": INCLUDE_ORDERS
            + 'include: "/views/refine.view.lkml"\nexplore: orders {}\n',
            f"{plain_model}.model.lkml": INCLUDE_ORDERS + "explore: orders {}\n",
            "views/orders.view.lkml": ORDERS,
            "views/refine.view.lkml": 'include: "/views/orders.view.lkml"\n'
            "view: +orders {\n  dimension: status { sql: ${TABLE}.status ;; }\n}\n",
        },
    )


@pytest.mark.integration
def test_datahub_reports_the_one_entity_it_emits_under_every_model(tmp_path: Path) -> None:
    # LookMLSource reads model files in path order and emits one entity per view, so the first model
    # that includes orders decides its fields, whichever model the entity is reported under.
    first_refines = two_models(tmp_path / "first_refines", refining_model="a", plain_model="b")
    second_refines = two_models(tmp_path / "second_refines", refining_model="z", plain_model="b")

    outputs = {
        Path(output["project"]).name: output for output in run("datahub", first_refines, second_refines)
    }

    def fields(project: str) -> dict[str, list[str]]:
        models = outputs[project]["models"]
        return {model: models[model]["views"]["orders"]["fields"] for model in models}

    assert fields("first_refines") == {"a": ["id", "status"], "b": ["id", "status"]}
    assert fields("second_refines") == {"b": ["id"], "z": ["id"]}


@pytest.mark.integration
def test_datahub_reports_lineage_of_the_emitted_entity(tmp_path: Path) -> None:
    project = write(
        tmp_path,
        {
            "m.model.lkml": 'connection: "wh"\ninclude: "/*.view.lkml"\n',
            "orders.view.lkml": ORDERS,
            "facts.view.lkml": "view: facts {\n"
            "  derived_table: { sql: SELECT id FROM ${orders.SQL_TABLE_NAME} ;; }\n"
            "  dimension: id {}\n}\n",
        },
    )

    [output] = run("datahub", project)

    views = output["models"]["m"]["views"]
    assert views["orders"]["upstream"] == [{"table": "raw.orders"}]
    assert views["facts"]["upstream"] == [{"view": "orders"}]


def same_name_in_two_files(root: Path) -> Path:
    return write(
        root,
        {
            "m.model.lkml": 'connection: "wh"\ninclude: "/*.view"\nexplore: orders {}\n',
            "a.view.lkml": "view: orders { sql_table_name: from_a ;; }\n",
            "b.view.lkml": "view: orders { sql_table_name: from_b ;; }\n",
            "c.view.lkml": "view: orders { sql_table_name: from_c ;; }\n",
            "d.view.lkml": "view: orders { sql_table_name: from_d ;; }\n",
        },
    )


@pytest.mark.integration
def test_openmetadata_keeps_the_view_of_the_file_os_walk_lists_last(tmp_path: Path) -> None:
    project = same_name_in_two_files(tmp_path)
    last = listed(project, "*.view.lkml")[-1]

    [output] = run("openmetadata", project)

    assert output["models"]["*"]["views"]["orders"]["sql_table_name"] == f"from_{last[0]}"


@pytest.mark.integration
def test_dagster_applies_refinements_in_rglob_order(tmp_path: Path) -> None:
    project = write(
        tmp_path,
        {
            "m.model.lkml": 'connection: "wh"\ninclude: "/*.view"\nexplore: orders {}\n',
            "orders.view.lkml": ORDERS,
            **{
                f"{name}.view.lkml": f"view: +orders {{ sql_table_name: from_{name} ;; }}\n"
                for name in "abcd"
            },
        },
    )
    last = [name for name in listed(project, "*.view.lkml") if name != "orders.view.lkml"][-1]

    [output] = run("dagster", project)

    assert output["models"]["*"]["views"]["orders"]["sql_table_name"] == f"from_{last[0]}"


@pytest.mark.integration
def test_node_lookml_parser_finds_files_with_its_own_glob(tmp_path: Path) -> None:
    # The parser sorts the paths its glob finds, so a wildcard include applies s after p whatever
    # the file system order (APFS lists s.view.lkml first), and a refinement in a file that is not
    # a .view file is read.
    project = write(
        tmp_path,
        {
            "m.model.lkml": 'connection: "wh"\ninclude: "/orders.view"\ninclude: "/r/*.lkml"\n'
            'include: "/layer.lkml"\nexplore: orders {}\n',
            "orders.view.lkml": ORDERS,
            "r/s.view.lkml": 'include: "/orders.view"\nview: +orders { sql_table_name: from_s ;; }\n',
            "r/p.view.lkml": 'include: "/orders.view"\nview: +orders { sql_table_name: from_p ;; }\n',
            "layer.lkml": 'include: "/orders.view"\nview: +orders { dimension: status {} }\n',
        },
    )

    [output] = run("node-lookml-parser", project)

    orders = output["models"]["m"]["views"]["orders"]
    assert orders["sql_table_name"] == "from_s"
    assert orders["fields"] == ["id", "status"]


@pytest.mark.integration
def test_a_pass_that_came_from_the_file_listing_now_fails() -> None:
    # dagster-looker has no notion of final: yes and applies refinements in rglob order. Before r10
    # ran with r_final.view.lkml and r_later.view.lkml exchanged, it passed on APFS, which lists
    # r_final.view.lkml last. Now it resolves the final refinement in one layout and the later one in
    # the other, on any file system, and the case fails.
    adapter = REGISTRY["dagster"]
    if not installed(adapter):
        pytest.skip("dagster is not installed; run: lookml-conformance setup dagster")
    [case] = load_cases(CASES_ROOT, only="r10_")

    verdict = run_suite([case], [adapter]).results[0].verdicts["dagster"]

    assert verdict.outcome is Outcome.FAIL
    assert sorted(reason.partition(": ")[2] for reason in verdict.reasons) == [
        "m.orders.sql_table_name: expected 'a.final', got 'b.later'",
        "pass",
    ]


@pytest.mark.integration
@pytest.mark.parametrize("case_id", ["r04_", "i03_"])
def test_a_tool_that_follows_include_order_passes_every_layout(case_id: str) -> None:
    adapter = REGISTRY["node-lookml-parser"]
    if not installed(adapter) or shutil.which("node") is None:
        pytest.skip("node-lookml-parser is not installed or node is not on PATH")
    [case] = load_cases(CASES_ROOT, only=case_id)
    assert len(case.file_orders) == 2

    verdict = run_suite([case], [adapter]).results[0].verdicts["node-lookml-parser"]

    assert verdict.outcome is Outcome.PASS
    assert verdict.reasons == ()
