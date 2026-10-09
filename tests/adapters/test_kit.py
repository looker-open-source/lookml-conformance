from __future__ import annotations

from pathlib import Path

import pytest

from lookml_conformance.adapters import kit
from lookml_conformance.protocol import Upstream, ViewOutput


def test_flatten_repeated() -> None:
    assert kit.flatten_repeated([["a", "b"], "c", ("d",)]) == ["a", "b", "c", "d"]
    assert kit.flatten_repeated(None) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([{"status": "complete"}], [{"status": "complete"}]),
        ([[{"status": "complete"}], [{"region": "EU"}]], [{"status": "complete"}, {"region": "EU"}]),
        ([{"field": "status", "value": "complete"}], [{"status": "complete"}]),
        ({"status": "complete", "region": "EU"}, [{"status": "complete"}, {"region": "EU"}]),
        ([{"n": 1}, "ignored"], [{"n": "1"}]),
        (None, []),
    ],
)
def test_normalize_filters(raw: object, expected: list[dict[str, str]]) -> None:
    assert kit.normalize_filters(raw) == expected


def test_field_params() -> None:
    field = {
        "name": "created",
        "sql": "${TABLE}.created_at\n  ",
        "type": "time",
        "timeframes": ["date", "month"],
        "filters__all": [[{"status": "complete"}]],
        "hidden": "yes",
    }

    assert kit.field_params(field) == {
        "sql": "${TABLE}.created_at",
        "type": "time",
        "timeframes": ["date", "month"],
        "filters": [{"status": "complete"}],
    }


def test_field_params_wraps_a_single_timeframe() -> None:
    assert kit.field_params({"timeframes": "date"}) == {"timeframes": ["date"]}


def test_derived_table() -> None:
    raw = {"sql": "SELECT 1\n", "datagroup_trigger": "daily", "persist_for": 24, "explore_source": {"x": 1}}

    assert kit.derived_table(raw) == {"sql": "SELECT 1", "datagroup_trigger": "daily", "persist_for": "24"}
    assert kit.derived_table(raw, sql="SELECT 2") == {
        "sql": "SELECT 2",
        "datagroup_trigger": "daily",
        "persist_for": "24",
    }
    assert kit.derived_table({"datagroup_trigger": "daily"}) == {"datagroup_trigger": "daily"}
    assert kit.derived_table(None) is None
    assert kit.derived_table({}) is None


def test_view_output_from_an_lkml_dictionary() -> None:
    view = {
        "name": "orders",
        "sql_table_name": " raw.orders ",
        "extends__all": [["base_a"], ["base_b"]],
        "dimensions": [{"name": "id", "sql": "${TABLE}.id"}, "not a field"],
        "dimension_groups": [{"name": "created", "type": "time"}],
        "measures": [{"name": "n", "type": "count"}],
    }

    assert kit.view_output(view) == ViewOutput(
        sql_table_name="raw.orders",
        fields=("created", "id", "n"),
        field_params={"id": {"sql": "${TABLE}.id"}, "created": {"type": "time"}, "n": {"type": "count"}},
        extends=("base_a", "base_b"),
    )


def test_view_output_overrides() -> None:
    view = {"sql_table_name": "@{SCHEMA}.orders", "derived_table": {"sql": "@{X}"}, "extends": ["merged"]}

    output = kit.view_output(
        view, sql_table_name="prod.orders", derived_table_sql="resolved", fields=[{"name": "only"}]
    )

    assert output.sql_table_name == "prod.orders"
    assert output.derived_table == {"sql": "resolved"}
    assert output.fields == ("only",)
    assert output.extends == ("merged",)
    assert output.upstream is None


def test_view_output_keeps_the_tool_upstream() -> None:
    output = kit.view_output({"name": "v"}, upstream=iter([Upstream("view", "orders")]))

    assert output.upstream == (Upstream("view", "orders"),)


def test_model_files_skip_imported_projects(tmp_path: Path) -> None:
    for relative in (
        "b.model.lkml",
        "models/a.model.lkml",
        "imported_projects/shared/c.model.lkml",
        "v.view.lkml",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    files = kit.model_files(tmp_path)

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "b.model.lkml",
        "models/a.model.lkml",
    ]
    assert [kit.model_name(path) for path in files] == ["b", "a"]


def test_imported_projects(tmp_path: Path) -> None:
    assert kit.imported_projects(tmp_path) == {}
    (tmp_path / "imported_projects" / "shared").mkdir(parents=True)
    (tmp_path / "imported_projects" / "README").touch()

    assert kit.imported_projects(tmp_path) == {
        "shared": (tmp_path / "imported_projects" / "shared").resolve()
    }
