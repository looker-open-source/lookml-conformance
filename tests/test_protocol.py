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

from typing import Any

import pytest

from lookml_conformance.protocol import (
    AdapterOutput,
    Capabilities,
    ExploreOutput,
    ModelOutput,
    ProtocolError,
    Upstream,
    ViewOutput,
)

FULL_OUTPUT: dict[str, Any] = {
    "adapter": "tool",
    "version": "1.2.3",
    "capabilities": {"per_model": True, "explores": False, "imported_projects": True, "constants": True},
    "models": {
        "m": {
            "views": {
                "orders": {
                    "sql_table_name": "raw.orders",
                    "derived_table": None,
                    "fields": ["status", "id"],
                    "field_params": {"id": {"sql": "${TABLE}.id", "filters": [{"status": "x"}]}},
                    "extends": ["base"],
                    "upstream": [{"table": "raw.orders"}, {"view": "base"}],
                },
                "broken": {"error": "boom"},
            },
            "explores": {
                "orders": {
                    "view_name": "orders",
                    "from": None,
                    "label": "Orders",
                    "joins": {"users": {"from": "users", "sql_on": "a = b"}},
                }
            },
            "all_views": ["+orders", "orders"],
        }
    },
    "errors": ["warning"],
}


def test_parses_full_output() -> None:
    output = AdapterOutput.from_dict(FULL_OUTPUT)

    assert output.adapter == "tool"
    assert output.version == "1.2.3"
    assert output.capabilities == Capabilities(explores=False)
    assert output.errors == ("warning",)
    model = output.models["m"]
    assert model.views["orders"] == ViewOutput(
        sql_table_name="raw.orders",
        fields=("status", "id"),
        field_params={"id": {"sql": "${TABLE}.id", "filters": [{"status": "x"}]}},
        extends=("base",),
        upstream=(Upstream("table", "raw.orders"), Upstream("view", "base")),
    )
    assert model.views["broken"].error == "boom"
    assert model.explores["orders"] == ExploreOutput(
        view_name="orders", label="Orders", joins={"users": {"from": "users", "sql_on": "a = b"}}
    )
    assert model.exposed_views == ("+orders", "orders")


def test_round_trips_through_json_dicts() -> None:
    serialized = AdapterOutput.from_dict(FULL_OUTPUT).to_dict()

    assert AdapterOutput.from_dict(serialized).to_dict() == serialized


def test_to_dict_sorts_fields_and_views() -> None:
    model = ModelOutput(views={"b": ViewOutput(fields=("z", "a")), "a": ViewOutput()})

    data = model.to_dict()

    assert list(data["views"]) == ["a", "b"]
    assert data["views"]["b"]["fields"] == ["a", "z"]
    assert data["all_views"] == ["a", "b"]


def test_exposed_views_default_to_resolved_views() -> None:
    assert ModelOutput(views={"orders": ViewOutput()}).exposed_views == ("orders",)


def test_minimal_output_uses_defaults() -> None:
    output = AdapterOutput.from_dict({"adapter": "tool"})

    assert output == AdapterOutput(adapter="tool")
    assert output.capabilities == Capabilities()


def test_error_output_is_a_failure() -> None:
    output = AdapterOutput.from_dict({"adapter": "tool", "version": "1", "error": "crashed"})

    assert output == AdapterOutput.failure("tool", "crashed", version="1")
    assert output.to_dict() == {"adapter": "tool", "version": "1", "error": "crashed"}


def test_view_without_upstream_reports_no_lineage() -> None:
    view = ViewOutput.from_dict({"sql_table_name": "raw.orders"}, "v")

    assert view.upstream is None
    assert view.to_dict()["upstream"] is None


def test_empty_upstream_is_lineage_without_upstreams() -> None:
    assert ViewOutput.from_dict({"upstream": []}, "v").upstream == ()


def test_upstream_round_trips_and_prints_its_kind() -> None:
    edge = Upstream.from_dict({"explore": "orders"}, "e")

    assert edge.to_dict() == {"explore": "orders"}
    assert str(edge) == "explore orders"


def test_capabilities_lacks_only_declared_false() -> None:
    capabilities = Capabilities.from_dict({"explores": False, "unknown_flag": False})

    assert capabilities.lacks("explores")
    assert not capabilities.lacks("constants")
    assert not capabilities.lacks("unknown_flag")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "output must be an object"),
        ({}, "'adapter' must be a non-empty string"),
        ({"adapter": "t", "capabilities": []}, "'capabilities' must be an object"),
        ({"adapter": "t", "capabilities": {"explores": "no"}}, "capabilities.explores must be true or false"),
        ({"adapter": "t", "models": []}, "models must be an object"),
        (
            {"adapter": "t", "models": {"m": {"views": {"v": {"fields": "id"}}}}},
            "models.m.views.v.fields must be a list",
        ),
        ({"adapter": "t", "models": {"m": {"views": {"v": []}}}}, "models.m.views.v must be an object"),
        ({"adapter": "t", "models": {"m": {"all_views": "v"}}}, "models.m.all_views must be a list"),
        (
            {"adapter": "t", "models": {"m": {"explores": {"e": {"joins": []}}}}},
            "models.m.explores.e.joins must be",
        ),
        (
            {"adapter": "t", "models": {"m": {"views": {"v": {"upstream": {"table": "x"}}}}}},
            "models.m.views.v.upstream must be a list",
        ),
        (
            {"adapter": "t", "models": {"m": {"views": {"v": {"upstream": [{"table": "x", "view": "y"}]}}}}},
            r"upstream\[0\] must have exactly one of the keys",
        ),
        (
            {"adapter": "t", "models": {"m": {"views": {"v": {"upstream": [{"dataset": "x"}]}}}}},
            "must have exactly one of the keys table, view, explore",
        ),
        (
            {"adapter": "t", "models": {"m": {"views": {"v": {"upstream": [{"view": ""}]}}}}},
            r"upstream\[0\].view must be a non-empty string",
        ),
    ],
)
def test_rejects_malformed_output(data: Any, message: str) -> None:
    with pytest.raises(ProtocolError, match=message):
        AdapterOutput.from_dict(data)
