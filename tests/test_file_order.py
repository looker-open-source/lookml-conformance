from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from lookml_conformance.cases import AS_WRITTEN, FileOrder, load_case
from lookml_conformance.file_order import layout, prepare, rewrite_includes, write_layout
from lookml_conformance.judge import Outcome, Verdict, judge_file_orders
from lookml_conformance.protocol import AdapterOutput, Capabilities, ModelOutput, ViewOutput
from lookml_conformance.runner import AdapterSpec, run_suite
from tests.conftest import BASE_VIEW, MakeCase

# r04 in miniature: the model includes b, then a, so a wins.
LATER_INCLUDE_WINS = {
    "m.model.lkml": 'connection: "wh"\ninclude: "/orders.view"\ninclude: "/b.view.lkml"\n'
    'include: "/a.view.lkml"\nexplore: orders {}\n',
    "orders.view.lkml": BASE_VIEW,
    "a.view.lkml": 'include: "/orders.view"\nview: +orders { sql_table_name: from_a ;; }\n',
    "b.view.lkml": 'include: "/orders.view"\nview: +orders { sql_table_name: from_b ;; }\n',
}
EXPECT_FROM_A = {"models": {"m": {"views": {"orders": {"sql_table_name": "from_a"}}}}}
EXCHANGE_A_B = FileOrder(("a.view.lkml", "b.view.lkml"))


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("m.model.lkml", 'include: "/a.view.lkml"', 'include: "/b.view.lkml"'),
        ("m.model.lkml", 'include: "/a.view"', 'include: "/b.view"'),
        ("m.model.lkml", 'include:"/b.view.lkml"', 'include:"/a.view.lkml"'),
        ("views/x.view.lkml", 'include: "../a.view"', 'include: "../b.view"'),
        ("x.view.lkml", 'include: "a.view.lkml"', 'include: "b.view.lkml"'),
        ("m.model.lkml", 'include: "/*.view.lkml"', 'include: "/*.view.lkml"'),
        ("m.model.lkml", 'include: "//shared/a.view"', 'include: "//shared/a.view"'),
        ("m.model.lkml", 'include: "/orders.view"', 'include: "/orders.view"'),
        ("m.model.lkml", '# include: "/a.view"', '# include: "/a.view"'),
        ("views/x.view.lkml", 'include: "a.view"', 'include: "a.view"'),
    ],
)
def test_rewrite_includes_follows_the_exchanged_contents(path: str, text: str, expected: str) -> None:
    assert (
        rewrite_includes(text, path, {"a.view.lkml": "b.view.lkml", "b.view.lkml": "a.view.lkml"}) == expected
    )


def test_rewrite_includes_keeps_the_rest_of_the_file() -> None:
    text = 'connection: "wh"\ninclude: "/a.view"\n  include: "/b.view.lkml"\nexplore: orders {}\n'
    renamed = {"a.view.lkml": "b.view.lkml", "b.view.lkml": "a.view.lkml"}

    assert rewrite_includes(text, "m.model.lkml", renamed) == (
        'connection: "wh"\ninclude: "/b.view"\n  include: "/a.view.lkml"\nexplore: orders {}\n'
    )


def test_layout_as_written_is_the_project(make_case: MakeCase) -> None:
    case = load_case(make_case(files=LATER_INCLUDE_WINS))

    files = layout(case.project, AS_WRITTEN)

    assert {path: content.decode() for path, content in files.items()} == LATER_INCLUDE_WINS


def test_layout_exchanges_contents_and_rewrites_includes(make_case: MakeCase) -> None:
    case = load_case(make_case(files=LATER_INCLUDE_WINS))

    files = {path: content.decode() for path, content in layout(case.project, EXCHANGE_A_B).items()}

    assert sorted(files) == sorted(LATER_INCLUDE_WINS)
    assert files["a.view.lkml"] == LATER_INCLUDE_WINS["b.view.lkml"]
    assert files["b.view.lkml"] == LATER_INCLUDE_WINS["a.view.lkml"]
    # The model still includes from_b first and from_a last.
    assert files["m.model.lkml"] == (
        'connection: "wh"\ninclude: "/orders.view"\ninclude: "/a.view.lkml"\n'
        'include: "/b.view.lkml"\nexplore: orders {}\n'
    )


def test_layout_leaves_imported_projects_alone(make_case: MakeCase) -> None:
    files = {
        **LATER_INCLUDE_WINS,
        "imported_projects/shared/x.view.lkml": 'include: "/a.view"\nview: x {}\n',
    }
    case = load_case(make_case(files=files))

    exchanged = layout(case.project, EXCHANGE_A_B)

    assert (
        exchanged["imported_projects/shared/x.view.lkml"].decode()
        == files["imported_projects/shared/x.view.lkml"]
    )


def test_write_layout_writes_files_in_path_order(tmp_path: Path) -> None:
    written: list[str] = []
    destination = tmp_path / "out"

    class Recording(dict[str, bytes]):
        def __getitem__(self, key: str) -> bytes:
            written.append(key)
            return super().__getitem__(key)

    write_layout(Recording({"z.lkml": b"z", "a/b.lkml": b"b", "m.lkml": b"m"}), destination)

    assert written == ["a/b.lkml", "m.lkml", "z.lkml"]
    assert (destination / "a/b.lkml").read_bytes() == b"b"


def test_prepare_uses_the_case_project_without_variants(make_case: MakeCase, tmp_path: Path) -> None:
    case = load_case(make_case())

    assert prepare(case, tmp_path / "scratch") == [(AS_WRITTEN, case.project)]


def test_prepare_writes_every_layout(make_case: MakeCase, tmp_path: Path) -> None:
    case = load_case(
        make_case(
            files=LATER_INCLUDE_WINS, expect=EXPECT_FROM_A, order_variants=[["a.view.lkml", "b.view.lkml"]]
        )
    )

    prepared = prepare(case, tmp_path / "scratch")

    assert prepared == [
        (AS_WRITTEN, tmp_path / "scratch" / "r01_example" / "project"),
        (EXCHANGE_A_B, tmp_path / "scratch" / "r01_example.exchange-1" / "project"),
    ]
    assert (prepared[0][1] / "a.view.lkml").read_text() == LATER_INCLUDE_WINS["a.view.lkml"]
    assert (prepared[1][1] / "a.view.lkml").read_text() == LATER_INCLUDE_WINS["b.view.lkml"]


def outputs(*tables: str | None, error: str | None = None) -> list[tuple[FileOrder, AdapterOutput]]:
    orders = [AS_WRITTEN, EXCHANGE_A_B]
    results = []
    for order, table in zip(orders, tables, strict=True):
        if error is not None and table is None:
            results.append((order, AdapterOutput.failure("tool", error)))
            continue
        view = ViewOutput(sql_table_name=table)
        results.append(
            (order, AdapterOutput(adapter="tool", models={"m": ModelOutput(views={"orders": view})}))
        )
    return results


def test_judge_file_orders_passes_when_every_layout_passes(make_case: MakeCase) -> None:
    case = load_case(make_case(files=LATER_INCLUDE_WINS, expect=EXPECT_FROM_A))

    assert judge_file_orders(case, outputs("from_a", "from_a")) == Verdict(Outcome.PASS)


def test_judge_file_orders_names_the_layout_that_fails(make_case: MakeCase) -> None:
    case = load_case(make_case(files=LATER_INCLUDE_WINS, expect=EXPECT_FROM_A))

    verdict = judge_file_orders(case, outputs("from_a", "from_b"))

    assert verdict == Verdict(
        Outcome.FAIL,
        (
            "as written: pass",
            "a.view.lkml and b.view.lkml exchanged: m.orders.sql_table_name: expected 'from_a', got 'from_b'",
        ),
    )


def test_judge_file_orders_reports_a_result_shared_by_every_layout_once(make_case: MakeCase) -> None:
    case = load_case(make_case(files=LATER_INCLUDE_WINS, expect=EXPECT_FROM_A))

    verdict = judge_file_orders(case, outputs("raw.orders", "raw.orders"))

    assert verdict == Verdict(Outcome.FAIL, ("m.orders.sql_table_name: expected 'from_a', got 'raw.orders'",))


def test_judge_file_orders_prefers_a_failure_to_an_error(make_case: MakeCase) -> None:
    case = load_case(make_case(files=LATER_INCLUDE_WINS, expect=EXPECT_FROM_A))

    verdict = judge_file_orders(case, outputs(None, "from_b", error="crashed"))

    assert verdict.outcome is Outcome.FAIL
    assert verdict.reasons == (
        "as written: crashed",
        "a.view.lkml and b.view.lkml exchanged: m.orders.sql_table_name: expected 'from_a', got 'from_b'",
    )


def test_judge_file_orders_is_not_applicable_when_the_tool_lacks_a_capability(make_case: MakeCase) -> None:
    case = load_case(
        make_case(expect={"models": {"m": {"views": {"orders": {"upstream_tables": ["raw.orders"]}}}}})
    )
    lacking = AdapterOutput(adapter="tool", capabilities=Capabilities(lineage=False))

    verdict = judge_file_orders(case, [(AS_WRITTEN, lacking), (EXCHANGE_A_B, lacking)])

    assert verdict.outcome is Outcome.NOT_APPLICABLE


# Two adapters for the same rule. The first reads files in the order os.walk lists them and lets
# the last refinement it reads win, as a tool that ignores include order does. The second follows
# the model's include statements in order, applying an included file after the files it includes.
LISTING_ORDER_ADAPTER = """\
import json, os, re, sys
for project in sys.argv[1:]:
    table = None
    for directory, _, names in os.walk(project):
        for name in names:
            text = open(os.path.join(directory, name)).read()
            for refinement, value in re.findall(r"view: (\\+?)orders \\{ sql_table_name: (\\S+) ;;", text):
                if refinement or table is None:
                    table = value
    models = {"m": {"views": {"orders": {"sql_table_name": table}}}}
    print(json.dumps({"adapter": "listing", "project": project, "models": models}))
"""
INCLUDE_ORDER_ADAPTER = """\
import json, os, re, sys
def visit(project, path, seen, texts):
    path = path if path.endswith(".lkml") else path + ".lkml"
    if path in seen:
        return
    seen.add(path)
    text = open(os.path.join(project, path)).read()
    for include in re.findall(r'include: "/([^"]+)"', text):
        visit(project, include, seen, texts)
    texts.append(text)
for project in sys.argv[1:]:
    texts = []
    visit(project, "m.model.lkml", set(), texts)
    table = None
    for text in texts:
        for refinement, value in re.findall(r"view: (\\+?)orders \\{ sql_table_name: (\\S+) ;;", text):
            if refinement or table is None:
                table = value
    models = {"m": {"views": {"orders": {"sql_table_name": table}}}}
    print(json.dumps({"adapter": "includes", "project": project, "models": models}))
"""


def adapter(tmp_path: Path, name: str, body: str) -> AdapterSpec:
    path = tmp_path / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return AdapterSpec(name, (sys.executable, str(path)))


def test_a_tool_that_reads_files_in_listing_order_fails_one_layout(
    make_case: MakeCase, tmp_path: Path
) -> None:
    files = {**LATER_INCLUDE_WINS, "orders.view.lkml": "view: orders { sql_table_name: raw.orders ;; }\n"}
    case = load_case(
        make_case(files=files, expect=EXPECT_FROM_A, order_variants=[["a.view.lkml", "b.view.lkml"]])
    )
    listing = adapter(tmp_path, "listing", LISTING_ORDER_ADAPTER)
    includes = adapter(tmp_path, "includes", INCLUDE_ORDER_ADAPTER)

    verdicts = run_suite([case], [listing, includes]).results[0].verdicts

    # Whatever order this file system lists a.view.lkml and b.view.lkml in, the listing adapter reads
    # from_a last in one layout and from_b last in the other.
    assert verdicts["listing"].outcome is Outcome.FAIL
    assert sorted(reason.partition(": ")[2] for reason in verdicts["listing"].reasons) == [
        "m.orders.sql_table_name: expected 'from_a', got 'from_b'",
        "pass",
    ]
    assert verdicts["includes"] == Verdict(Outcome.PASS)


def test_without_variants_the_listing_order_decides(make_case: MakeCase, tmp_path: Path) -> None:
    files = {**LATER_INCLUDE_WINS, "orders.view.lkml": "view: orders { sql_table_name: raw.orders ;; }\n"}
    case = load_case(make_case(files=files, expect=EXPECT_FROM_A))
    listed = [
        name
        for _, _, names in os.walk(case.project)
        for name in names
        if name in {"a.view.lkml", "b.view.lkml"}
    ]

    verdict = (
        run_suite([case], [adapter(tmp_path, "listing", LISTING_ORDER_ADAPTER)])
        .results[0]
        .verdicts["listing"]
    )

    assert verdict.outcome is (Outcome.PASS if listed[-1] == "a.view.lkml" else Outcome.FAIL)
