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

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = REPO_ROOT / "cases"

BASE_VIEW = "view: orders {\n  sql_table_name: raw.orders ;;\n  dimension: id { sql: ${TABLE}.id ;; }\n}\n"

DEFAULT_FILES = {
    "m.model.lkml": 'connection: "wh"\ninclude: "/orders.view"\nexplore: orders {}\n',
    "orders.view.lkml": BASE_VIEW,
}

VALID_CASE: dict[str, Any] = {
    "id": "r01_example",
    "title": "An example case",
    "rule": "A refinement overrides sql_table_name.",
    "status": "confirmed",
    "basis": ["documentation"],
    "citations": [
        {
            "url": "https://docs.cloud.google.com/looker/docs/lookml-refinements#refinements_override_parameters",
            "quote": "In most cases a refinement will override the original settings of an object.",
        }
    ],
    "expect": {"models": {"m": {"views": {"orders": {"sql_table_name": "raw.orders"}}}}},
}

MakeCase = Callable[..., Path]


@pytest.fixture
def make_case(tmp_path: Path) -> MakeCase:
    """Write a case directory under ``tmp_path/cases`` and return its path.

    Keyword overrides replace top-level keys of a valid case; ``files`` replaces the project files.
    """

    def make(
        category: str = "refinements",
        files: dict[str, str] | None = None,
        **overrides: Any,
    ) -> Path:
        data = copy.deepcopy(VALID_CASE) | overrides
        if data["status"] == "provisional" and "basis" not in overrides:
            del data["basis"]
        directory = tmp_path / "cases" / category / data["id"]
        directory.mkdir(parents=True)
        (directory / "case.json").write_text(json.dumps(data), encoding="utf-8")
        for relative, content in (DEFAULT_FILES if files is None else files).items():
            path = directory / "project" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return directory

    return make
