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

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from lookml_conformance.cases import Case, Citation, ModelExpectation, Status
from lookml_conformance.judge import Outcome, Verdict, judge, upstream_tables
from lookml_conformance.protocol import (
    AdapterOutput,
    Capabilities,
    ExploreOutput,
    ModelOutput,
    Upstream,
    ViewOutput,
)


def make_case(
    tmp_path: Path,
    views: dict[str, Any] | None = None,
    explores: dict[str, Any] | None = None,
    models: dict[str, ModelExpectation] | None = None,
    absent_views: tuple[str, ...] = (),
    invalid_in_looker: bool = False,
) -> Case:
    (tmp_path / "project").mkdir(exist_ok=True)
    return Case(
        id="r01_test",
        category="refinements",
        title="t",
        rule="r",
        status=Status.CONFIRMED,
        citations=(Citation("https://example.com", "q"),),
        models=models or {"m": ModelExpectation(views=views or {}, explores=explores or {})},
        directory=tmp_path,
        absent_views=absent_views,
        invalid_in_looker=invalid_in_looker,
    )


def output(
    views: dict[str, ViewOutput] | None = None,
    explores: dict[str, ExploreOutput] | None = None,
    capabilities: Capabilities | None = None,
    model: str = "m",
    all_views: tuple[str, ...] | None = None,
) -> AdapterOutput:
    return AdapterOutput(
        adapter="tool",
        capabilities=capabilities or Capabilities(),
        models={model: ModelOutput(views=views or {}, explores=explores or {}, all_views=all_views)},
    )


def test_pass_when_asserted_keys_match(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"sql_table_name": "a.b", "fields": ["id", "status"]}})
    result = output({"orders": ViewOutput(sql_table_name="a.b", fields=("status", "id"), extends=("x",))})

    assert judge(case, result) == Verdict(Outcome.PASS)


def test_unasserted_keys_are_ignored(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"fields": ["id"]}})

    assert (
        judge(case, output({"orders": ViewOutput(sql_table_name="anything", fields=("id",))})).outcome
        is Outcome.PASS
    )


def test_text_comparison_ignores_whitespace(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"derived_table": {"sql": "SELECT id\n  FROM t"}}})
    result = output({"orders": ViewOutput(derived_table={"sql": " SELECT  id FROM t "})})

    assert judge(case, result).outcome is Outcome.PASS


@pytest.mark.parametrize(
    ("expected", "got", "reason"),
    [
        (
            {"sql_table_name": "a"},
            ViewOutput(sql_table_name="b"),
            "m.orders.sql_table_name: expected 'a', got 'b'",
        ),
        (
            {"sql_table_name": None},
            ViewOutput(sql_table_name="b"),
            "m.orders.sql_table_name: expected None, got 'b'",
        ),
        (
            {"derived_table": {"sql": "x", "datagroup_trigger": "d"}},
            ViewOutput(derived_table={"sql": "x"}),
            "m.orders.derived_table.datagroup_trigger: expected 'd', got None",
        ),
        ({"derived_table": {"sql": "x"}}, ViewOutput(), "m.orders.derived_table.sql: expected 'x', got None"),
        (
            {"fields": ["a", "b"]},
            ViewOutput(fields=("a",)),
            "m.orders.fields: expected ['a', 'b'], got ['a']",
        ),
        (
            {"extends": ["a", "b"]},
            ViewOutput(extends=("b",)),
            "m.orders.extends: expected ['a', 'b'], got ['b']",
        ),
        ({"extends": ["a"]}, ViewOutput(), "m.orders.extends: expected ['a'], got None"),
        ({"field_params": {"id": {"label": "X"}}}, ViewOutput(), "m.orders.id: field not resolved"),
        (
            {"field_params": {"id": {"label": "X"}}},
            ViewOutput(field_params={"id": {"label": "Y"}}),
            "m.orders.id.label: expected 'X', got 'Y'",
        ),
        (
            {"field_params": {"n": {"filters": [{"a": "1"}, {"b": "2"}]}}},
            ViewOutput(field_params={"n": {"filters": [{"b": "2"}, {"a": "1"}]}}),
            "m.orders.n.filters: expected [{'a': '1'}, {'b': '2'}], got [{'b': '2'}, {'a': '1'}]",
        ),
        (
            {"field_params": {"d": {"timeframes": ["date", "month"]}}},
            ViewOutput(field_params={"d": {"timeframes": ["raw", "date", "month"]}}),
            "m.orders.d.timeframes: expected ['date', 'month'], got ['date', 'month', 'raw']",
        ),
        (
            {"field_params": {"d": {"timeframes": ["date"]}}},
            ViewOutput(field_params={"d": {}}),
            "m.orders.d.timeframes: expected ['date'], got None",
        ),
    ],
)
def test_view_mismatches(tmp_path: Path, expected: dict[str, Any], got: ViewOutput, reason: str) -> None:
    verdict = judge(make_case(tmp_path, views={"orders": expected}), output({"orders": got}))

    assert verdict == Verdict(Outcome.FAIL, (reason,))


def test_timeframes_ignore_order(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"field_params": {"d": {"timeframes": ["month", "date"]}}}})
    result = output({"orders": ViewOutput(field_params={"d": {"timeframes": ["date", "month"]}})})

    assert judge(case, result).outcome is Outcome.PASS


def test_missing_view_and_view_error(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"fields": []}, "users": {"fields": []}})

    verdict = judge(case, output({"users": ViewOutput(error="KeyError('x')")}))

    assert verdict.reasons == ("m.orders: view not resolved", "m.users: KeyError('x')")


def test_missing_model(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"fields": []}})

    assert judge(case, output(model="other")).reasons == ("m: model not resolved",)


def test_project_wide_output_must_satisfy_every_model(tmp_path: Path) -> None:
    case = make_case(
        tmp_path,
        models={
            "a": ModelExpectation(views={"orders": {"sql_table_name": "x"}}),
            "b": ModelExpectation(views={"orders": {"sql_table_name": "y"}}),
        },
    )
    result = output(
        {"orders": ViewOutput(sql_table_name="x")}, model="*", capabilities=Capabilities(per_model=False)
    )

    assert judge(case, result).reasons == ("b.orders.sql_table_name: expected 'y', got 'x'",)


def test_per_model_output_is_not_reused_across_models(tmp_path: Path) -> None:
    case = make_case(tmp_path, models={"a": ModelExpectation(views={"orders": {"fields": []}})})

    assert judge(case, output(model="b")).reasons == ("a: model not resolved",)


def test_explore_checks(tmp_path: Path) -> None:
    case = make_case(
        tmp_path,
        explores={
            "e": {
                "view_name": "orders",
                "from": "orders",
                "label": "E",
                "joins": {
                    "buyer": {"from": "users", "sql_on": "${e.id} = ${buyer.id}"},
                    "gone": {"from": "x"},
                },
            },
            "missing": {"view_name": "orders"},
        },
    )
    result = output(
        explores={
            "e": ExploreOutput(
                view_name="orders",
                from_view="orders",
                label=None,
                joins={"buyer": {"from": "users", "sql_on": "${e.id}  = ${buyer.id}"}},
            )
        }
    )

    assert judge(case, result).reasons == (
        "m.explore.e.label: expected 'E', got None",
        "m.explore.e.join.gone: join not resolved",
        "m.explore.missing: explore not resolved",
    )


def test_absent_views(tmp_path: Path) -> None:
    case = make_case(tmp_path, views={"orders": {"fields": []}}, absent_views=("+orders", "ghost"))
    result = output({"orders": ViewOutput()}, all_views=("+orders", "orders"))

    assert judge(case, result).reasons == ("views that must not exist were exposed: ['+orders']",)


def test_adapter_error_is_an_error_verdict(tmp_path: Path) -> None:
    verdict = judge(make_case(tmp_path, views={"orders": {}}), AdapterOutput.failure("tool", "crashed"))

    assert verdict == Verdict(Outcome.ERROR, ("crashed",))
    assert verdict.failed


def test_missing_capability_is_not_applicable(tmp_path: Path) -> None:
    case = make_case(tmp_path, explores={"e": {"view_name": "orders"}})

    verdict = judge(case, output(capabilities=Capabilities(explores=False)))

    assert verdict == Verdict(Outcome.NOT_APPLICABLE, ("adapter does not support explores",))
    assert not verdict.outcome.applicable
    assert not verdict.failed


def table(name: str) -> Upstream:
    return Upstream("table", name)


def view(name: str) -> Upstream:
    return Upstream("view", name)


def lineage_case(tmp_path: Path, tables: list[str]) -> Case:
    return make_case(tmp_path, views={"facts": {"upstream_tables": tables}})


def test_upstream_tables_follow_view_references(tmp_path: Path) -> None:
    result = output(
        {
            "facts": ViewOutput(upstream=(view("rollup"), table("RAW.customers"))),
            "rollup": ViewOutput(upstream=(view("orders"),)),
            "orders": ViewOutput(upstream=(table("raw.orders"),)),
        }
    )

    assert judge(lineage_case(tmp_path, ["raw.customers", "raw.orders"]), result) == Verdict(Outcome.PASS)


def test_upstream_tables_follow_an_explore_to_its_views(tmp_path: Path) -> None:
    result = output(
        {
            "facts": ViewOutput(upstream=(Upstream("explore", "buyers"),)),
            "orders": ViewOutput(upstream=(table("raw.orders"),)),
            "users": ViewOutput(upstream=(table("raw.users"),)),
        },
        explores={"buyers": ExploreOutput(from_view="orders", joins={"buyer": {"from": "users"}})},
    )

    assert judge(lineage_case(tmp_path, ["raw.orders", "raw.users"]), result).outcome is Outcome.PASS


def test_upstream_tables_stop_at_cycles_and_report_unresolved_references() -> None:
    model = ModelOutput(
        views={
            "a": ViewOutput(upstream=(view("b"), view("missing"), Upstream("explore", "gone"))),
            "b": ViewOutput(upstream=(view("a"), table("t"))),
            "no_lineage": ViewOutput(),
        }
    )

    tables, unresolved = upstream_tables(model.views["a"], model)

    assert tables == {"t"}
    assert unresolved == ["explore gone", "view missing"]
    assert upstream_tables(ViewOutput(upstream=(view("no_lineage"),)), model) == (set(), ["view no_lineage"])


def test_upstream_mismatch_names_what_the_tool_reported(tmp_path: Path) -> None:
    result = output({"facts": ViewOutput(upstream=(view("orders"),))})

    verdict = judge(lineage_case(tmp_path, ["raw.orders"]), result)

    assert verdict.reasons == (
        "m.facts.upstream_tables: expected ['raw.orders'], got []; "
        "reported upstream: ['view orders']; not resolved: ['view orders']",
    )


def test_view_without_lineage_fails_an_upstream_assertion(tmp_path: Path) -> None:
    verdict = judge(lineage_case(tmp_path, ["raw.orders"]), output({"facts": ViewOutput()}))

    assert verdict.reasons == ("m.facts.upstream_tables: expected ['raw.orders'], got no lineage",)


def test_lineage_cases_are_not_applicable_without_lineage(tmp_path: Path) -> None:
    case = lineage_case(tmp_path, ["raw.orders"])

    verdict = judge(case, output(capabilities=Capabilities(lineage=False)))

    assert verdict == Verdict(Outcome.NOT_APPLICABLE, ("adapter does not support lineage",))


def test_view_error_is_accepted_for_a_project_looker_rejects(tmp_path: Path) -> None:
    case = make_case(tmp_path, {"orders": {"sql_table_name": "a.final"}}, invalid_in_looker=True)
    rejected = output({"orders": ViewOutput(error="Looker rejected explore orders")})

    assert judge(case, rejected).outcome is Outcome.PASS
    assert judge(case, output({"orders": ViewOutput(sql_table_name="a.final")})).outcome is Outcome.PASS
    assert judge(case, output({"orders": ViewOutput(sql_table_name="b.later")})).outcome is Outcome.FAIL


def test_view_error_fails_a_valid_project(tmp_path: Path) -> None:
    case = make_case(tmp_path, {"orders": {"sql_table_name": "a.final"}})

    assert judge(case, output({"orders": ViewOutput(error="KeyError('x')")})).outcome is Outcome.FAIL


def filters_case(tmp_path: Path, unordered: frozenset[str]) -> Case:
    expected = {"n": {"filters": [{"status": "complete"}, {"region": "EU"}]}}
    case = make_case(tmp_path, {"orders": {"field_params": expected}})
    return replace(case, unordered=unordered)


def filters_output(*filters: dict[str, str]) -> AdapterOutput:
    return output({"orders": ViewOutput(field_params={"n": {"filters": list(filters)}})})


def test_filters_are_compared_in_order_by_default(tmp_path: Path) -> None:
    case = filters_case(tmp_path, frozenset())

    assert judge(case, filters_output({"status": "complete"}, {"region": "EU"})).outcome is Outcome.PASS
    assert judge(case, filters_output({"region": "EU"}, {"status": "complete"})).outcome is Outcome.FAIL


def test_unordered_filters_are_compared_as_a_collection(tmp_path: Path) -> None:
    case = filters_case(tmp_path, frozenset({"filters"}))

    assert judge(case, filters_output({"region": "EU"}, {"status": "complete"})).outcome is Outcome.PASS
    assert judge(case, filters_output({"status": "complete"}, {"region": "EU"})).outcome is Outcome.PASS
    missing = judge(case, filters_output({"region": "EU"}))
    assert missing.reasons == (
        "m.orders.n.filters: expected [{'status': 'complete'}, {'region': 'EU'}], got [{'region': 'EU'}] "
        "(compared in any order)",
    )
    repeated = filters_output({"region": "EU"}, {"region": "EU"}, {"status": "complete"})
    assert judge(case, repeated).outcome is Outcome.FAIL
    assert judge(case, output({"orders": ViewOutput(field_params={"n": {}})})).outcome is Outcome.FAIL
