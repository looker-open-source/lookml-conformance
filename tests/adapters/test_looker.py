from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lookml_conformance.adapters import looker
from lookml_conformance.protocol import AdapterOutput, Upstream

DERIVED_SQL = """-- Looker Query Context '{"user_id":1,"history_slug":"x"}'
WITH orders_rollup AS (SELECT customer_id, COUNT(*) AS n
      FROM raw.orders AS o
      WHERE note != ';' AND note != ')'
      GROUP BY 1)
  , orders_rollup_repeat AS (SELECT * FROM orders_rollup)
SELECT
    orders_rollup_repeat.customer_id  AS orders_rollup_repeat_customer_id
FROM orders_rollup_repeat
GROUP BY
    1
ORDER BY
    1
LIMIT 1
"""

JOIN_SQL = """SELECT
    buyer.id  AS buyer_id,
    EXTRACT(YEAR FROM buyer_orders.created_at) AS y
FROM `raw.orders`  AS buyer_orders
LEFT JOIN raw.users  AS buyer ON buyer_orders.user_id = buyer.id
GROUP BY
    1
LIMIT 1
"""


def test_parse_query_reads_ctes_and_top_level_sources() -> None:
    ctes, sources = looker.parse_query(DERIVED_SQL)
    assert set(ctes) == {"orders_rollup", "orders_rollup_repeat"}
    assert "note != ';' AND note != ')'" in ctes["orders_rollup"]
    assert sources == [looker.Source(table="orders_rollup_repeat", query=None, alias="orders_rollup_repeat")]


def test_tables_read_follows_chained_ctes() -> None:
    assert looker.tables_read(DERIVED_SQL) == {"raw.orders"}


def test_view_from_sql_for_a_derived_table() -> None:
    table, derived, upstream = looker.view_from_sql(DERIVED_SQL, "orders_rollup_repeat") or (None, None, [])
    assert table is None
    assert derived == "SELECT * FROM orders_rollup"
    assert upstream == ["raw.orders"]


def test_view_from_sql_for_base_and_joined_views() -> None:
    assert looker.view_from_sql(JOIN_SQL, "buyer_orders") == ("raw.orders", None, ["raw.orders"])
    assert looker.view_from_sql(JOIN_SQL, "buyer") == ("raw.users", None, ["raw.users"])
    assert looker.view_from_sql(JOIN_SQL, "nobody") is None


def test_view_from_sql_for_an_inline_subquery() -> None:
    sql = "SELECT o.id AS o_id FROM (SELECT id FROM raw.orders JOIN raw.users AS u ON TRUE) AS o LIMIT 1"
    assert looker.view_from_sql(sql, "o") == (
        None,
        "SELECT id FROM raw.orders JOIN raw.users AS u ON TRUE",
        ["raw.orders", "raw.users"],
    )


def test_strip_comments_keeps_literals() -> None:
    assert looker.strip_comments("SELECT '--x' /* c */ -- tail\nFROM t") == "SELECT '--x'  \nFROM t"


def explore(name: str, view_name: str, fields: list[dict[str, Any]], joins: Any = ()) -> dict[str, Any]:
    return {
        "name": name,
        "view_name": view_name,
        "label": name.replace("_", " ").title(),
        "sql_table_name": f"raw.{view_name} AS {name}",
        "joins": list(joins),
        "fields": {"dimensions": [f for f in fields if not f.get("measure")],
                   "measures": [f for f in fields if f.get("measure")]},
    }  # fmt: skip


def dim(view: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"name": f"{view}.{name}", "view": view, "sql": f"${{TABLE}}.{name}", "type": "string",
            "label_short": name.title()} | extra  # fmt: skip


def test_explore_output_infers_from_and_reads_joins() -> None:
    join = {"name": "buyer", "from": "users", "relationship": "many_to_one", "type": "left_outer",
            "sql_on": "${buyer_orders.user_id} =\n ${buyer.id}",
            "sql_table_name": "raw.users AS buyer"}  # fmt: skip
    with_from = explore("buyer_orders", "orders", [dim("buyer_orders", "id"), dim("buyer", "id")], [join])
    output = looker.explore_output(with_from)
    assert (output.view_name, output.from_view) == ("orders", "orders")
    assert output.joins["buyer"]["from"] == "users"
    assert output.joins["buyer"]["sql_on"] == "${buyer_orders.user_id} = ${buyer.id}"
    with_view_name = explore("customer_orders", "orders", [dim("orders", "id")])
    assert looker.explore_output(with_view_name).from_view is None
    assert looker.view_aliases(with_from) == {"buyer_orders": "orders", "buyer": "users"}


def test_fields_output_groups_timeframes_and_reads_filters() -> None:
    fields = [
        dim("orders", "created_date", type="date_date", dimension_group="orders.created",
            field_group_label="Order Created", sql="${TABLE}.created_at"),
        dim("orders", "created_month", type="date_month", dimension_group="orders.created",
            field_group_label="Order Created", sql="${TABLE}.created_at"),
        {"name": "orders.n", "view": "orders", "type": "count", "measure": True, "label_short": "N",
         "filters": [{"field": "orders.status", "condition": "complete"},
                     {"field": "region", "condition": "EU"}]},
    ]  # fmt: skip
    assert looker.fields_output(fields) == {
        "created": {"sql": "${TABLE}.created_at", "label": "Order Created", "type": "time",
                    "timeframes": ["date", "month"]},
        "n": {"label": "N", "type": "count", "filters": [{"status": "complete"}, {"region": "EU"}]},
    }  # fmt: skip


def test_views_output_prefers_generated_sql_and_falls_back_to_metadata() -> None:
    meta = explore(
        "orders_rollup_repeat", "orders_rollup_repeat", [dim("orders_rollup_repeat", "customer_id")]
    )
    views = looker.views_output(meta, {"orders_rollup_repeat": DERIVED_SQL})
    view = views["orders_rollup_repeat"]
    assert view.sql_table_name is None
    assert view.derived_table == {"sql": "SELECT * FROM orders_rollup"}
    assert view.upstream == (Upstream("table", "raw.orders"),)
    fallback = looker.views_output(meta, {})["orders_rollup_repeat"]
    assert fallback.sql_table_name == "raw.orders_rollup_repeat"
    assert fallback.upstream is None


def test_probe_explores_cover_only_unexplored_views() -> None:
    model = 'connection: "wh"\nexplore: orders {\n  join: users { sql_on: x ;; }\n}\n'
    probes = looker.probe_explores(model, ["orders", "users", "order_facts"])
    assert probes == "\nexplore: lc_probe__order_facts { from: order_facts }\n"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    git("config", "user.email", "t@example.com", cwd=work)
    git("config", "user.name", "t", cwd=work)
    (work / "README.md").write_text("x\n")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "init", cwd=work)
    git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=work)
    return work


def write_project(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def test_stage_project_replaces_files_and_pushes(repo: Path, tmp_path: Path) -> None:
    first = write_project(tmp_path / "a" / "project", {
        "m.model.lkml": 'connection: "wh"\ninclude: "/views/*.view.lkml"\n',
        "views/orders.view.lkml": "view: orders {\n  sql_table_name: raw.orders ;;\n}\n",
    })  # fmt: skip
    sha = looker.stage_project(first, repo, "lc", "bq", "a")
    assert git("rev-parse", "origin/lc", cwd=repo) == sha
    model = (repo / "m.model.lkml").read_text()
    assert 'connection: "bq"' in model
    assert "explore: lc_probe__orders { from: orders }" in model

    second = write_project(tmp_path / "b" / "project", {"n.model.lkml": 'connection: "wh"\nexplore: x {}\n'})
    looker.stage_project(second, repo, "lc", None, "b")
    assert sorted(git("ls-files", cwd=repo).split()) == ["n.model.lkml"]
    assert not (repo / "views").exists()


class FakeApi(looker.LookerApi):
    """Answers the calls the adapter makes for one model with one explore."""

    def __init__(self, remote_sha: str) -> None:
        super().__init__("https://looker.invalid", "id", "secret")
        self.remote_sha = remote_sha
        self.calls: list[tuple[str, str]] = []
        self.models: set[str] = set()

    def call(self, method: str, path: str, body: Any = None, query: Any = None, raw: bool = False) -> Any:
        self.calls.append((method, path))
        meta = explore("orders", "orders", [dim("orders", "id")])
        responses: dict[tuple[str, str], Any] = {
            ("PATCH", "/session"): {"workspace_id": "dev"},
            ("GET", "/projects/p/git_branch"): {"name": "lc", "ref": self.remote_sha},
            ("POST", "/projects/p/reset_to_remote"): None,
            ("POST", "/lookml_models"): {},
            ("POST", "/projects/p/validate"): {"errors": [
                {"severity": "warning", "message": "about lc_probe__x"},
                {"severity": "error", "message": "Refinement after final", "file_path": "r.view.lkml",
                 "line_number": 2},
            ]},
            ("GET", "/lookml_models/m"): {"name": "m", "explores": [{"name": "orders"}, {"name": "ghost"}]},
            ("GET", "/lookml_models/m/explores/orders"): meta,
            ("POST", "/queries/run/sql"): "SELECT orders.id AS orders_id FROM a.final AS orders LIMIT 1",
        }  # fmt: skip
        if path == "/lookml_models/m/explores/ghost":
            raise looker.LookerApiError(method, path, 422, "unknown view ghost")
        if (method, path) == ("GET", "/lookml_models/m") and query is not None and "m" not in self.models:
            self.models.add("m")
            raise looker.LookerApiError(method, path, 404, "not found")
        return responses[(method, path)]


def test_resolve_end_to_end_with_a_fake_api(repo: Path, tmp_path: Path) -> None:
    project = write_project(tmp_path / "r10_case" / "project", {
        "m.model.lkml": 'connection: "wh"\ninclude: "/*.view"\nexplore: orders {}\n',
        "orders.view.lkml": "view: orders {\n  sql_table_name: raw.orders ;;\n  dimension: id {}\n}\n",
    })  # fmt: skip
    remote_sha = looker.stage_project(project, repo, "lc", None, "pre")  # the commit Looker will report
    options = argparse.Namespace(
        base_url="https://looker.invalid", client_id="id", client_secret="s", looker_project="p",
        repo=str(repo), connection=None, branch="lc", dump=str(tmp_path / "dump"),
    )  # fmt: skip
    adapter = looker.LookerAdapter(options)
    fake = FakeApi(remote_sha)
    adapter._api = fake
    # Staging the same files again gives a new commit; let the fake report whatever was pushed.
    original = looker.stage_project

    def stage(*args: Any) -> str:
        fake.remote_sha = original(*args)
        return fake.remote_sha

    looker.stage_project = stage  # type: ignore[assignment]
    try:
        output: AdapterOutput = adapter.run(str(project))
    finally:
        looker.stage_project = original  # type: ignore[assignment]
    assert output.error is None, output.error
    view = output.models["m"].views["orders"]
    assert view.sql_table_name == "a.final"
    assert view.fields == ("id",)
    assert output.errors[0] == "error: Refinement after final r.view.lkml:2"
    ghost = output.models["m"].views["ghost"]
    assert ghost.error is not None
    assert "Looker rejected explore ghost" in ghost.error
    assert "ghost" not in output.models["m"].exposed_views
    assert ("POST", "/lookml_models") in fake.calls
    dump = tmp_path / "dump" / "r10_case"
    assert json.loads((dump / "validation.json").read_text())["errors"]
    assert (dump / "sql__m__orders__orders.sql").exists()


def test_imported_projects_are_skipped(tmp_path: Path) -> None:
    project = write_project(tmp_path / "i05" / "project", {"imported_projects/shared/x.view.lkml": ""})
    adapter = looker.LookerAdapter(argparse.Namespace())
    output = adapter.run(str(project))
    assert output.error is None
    assert output.models == {}
    assert not output.capabilities.imported_projects
