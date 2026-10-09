"""The JSON Schema in docs/ must accept what the adapters print and reject what the runner rejects."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from lookml_conformance.protocol import (
    AdapterOutput,
    Capabilities,
    ExploreOutput,
    ModelOutput,
    ProtocolError,
    ViewOutput,
)
from tests.conftest import REPO_ROOT

SCHEMA = json.loads((REPO_ROOT / "docs" / "adapter-output.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

FULL = AdapterOutput(
    adapter="tool",
    version="1.0",
    project="/projects/a",
    capabilities=Capabilities(explores=False),
    models={
        "m": ModelOutput(
            views={
                "orders": ViewOutput(
                    sql_table_name="raw.orders",
                    derived_table={"sql": "SELECT 1", "datagroup_trigger": "daily"},
                    fields=("id", "n"),
                    field_params={
                        "n": {"type": "count", "filters": [{"status": "x"}], "timeframes": ["date"]}
                    },
                    extends=("base",),
                ),
                "broken": ViewOutput(error="KeyError('x')"),
            },
            explores={"e": ExploreOutput(view_name="orders", joins={"u": {"from": "users", "sql_on": None}})},
            all_views=("+orders", "broken", "orders"),
        )
    },
    errors=("warning",),
)


def test_the_schema_is_valid() -> None:
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize(
    "output",
    [FULL, AdapterOutput(adapter="tool"), AdapterOutput.failure("tool", "crashed", "1.0", "/projects/a")],
    ids=["full", "minimal", "failure"],
)
def test_the_schema_accepts_what_adapters_print(output: AdapterOutput) -> None:
    VALIDATOR.validate(output.to_dict())


def test_the_schema_documents_every_key_adapters_print() -> None:
    printed = FULL.to_dict()
    model = printed["models"]["m"]
    defs = SCHEMA["$defs"]

    assert set(printed) <= set(SCHEMA["properties"])
    assert set(printed["capabilities"]) == set(SCHEMA["properties"]["capabilities"]["properties"])
    assert set(model) == set(defs["model"]["properties"])
    assert set(model["views"]["orders"]) | {"error"} == set(defs["view"]["properties"])
    assert set(model["explores"]["e"]) == set(defs["explore"]["properties"])


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"adapter": ""},
        {"adapter": "t", "capabilities": {"explores": "no"}},
        {"adapter": "t", "models": []},
        {"adapter": "t", "models": {"m": {"views": {"v": {"fields": "id"}}}}},
        {"adapter": "t", "models": {"m": {"all_views": "v"}}},
    ],
)
def test_the_schema_rejects_what_the_runner_rejects(data: dict[str, Any]) -> None:
    assert not VALIDATOR.is_valid(data)
    with pytest.raises(ProtocolError):
        AdapterOutput.from_dict(data)
