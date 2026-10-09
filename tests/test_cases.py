from __future__ import annotations

from pathlib import Path

import pytest

from lookml_conformance.cases import (
    CaseError,
    Citation,
    Provenance,
    Status,
    SuiteError,
    case_directories,
    load_case,
    load_cases,
)
from tests.conftest import MakeCase


def problems_of(directory: Path) -> str:
    with pytest.raises(CaseError) as excinfo:
        load_case(directory)
    return "; ".join(excinfo.value.problems)


def test_loads_a_valid_case(make_case: MakeCase) -> None:
    case = load_case(make_case())

    assert case.id == "r01_example"
    assert case.category == "refinements"
    assert case.status is Status.CONFIRMED
    assert case.citations == (Citation(url=case.citations[0].url, quote=case.citations[0].quote),)
    assert case.models["m"].views["orders"] == {"sql_table_name": "raw.orders"}
    assert case.absent_views == ()
    assert case.invalid_in_looker is False
    assert case.provisional is None
    assert case.project == case.directory / "project"


def test_project_files_are_relative_and_sorted(make_case: MakeCase) -> None:
    case = load_case(make_case())

    assert case.project_files() == [Path("m.model.lkml"), Path("orders.view.lkml")]


def test_provisional_case_needs_provenance(make_case: MakeCase) -> None:
    assert "'provisional' block" in problems_of(make_case(status="provisional"))


def test_provisional_case_loads_provenance(make_case: MakeCase) -> None:
    case = load_case(make_case(status="provisional", provisional={"question": "Q?", "pinned_to": "tool 1.0"}))

    assert case.provisional == Provenance(question="Q?", pinned_to="tool 1.0")


def test_confirmed_case_rejects_provenance(make_case: MakeCase) -> None:
    problems = problems_of(make_case(provisional={"question": "Q?", "pinned_to": "tool"}))

    assert "must not have a 'provisional' block" in problems


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"id": "r01_other"}, "does not match the directory name"),
        ({"id": "R1-bad"}, "must look like"),
        ({"status": "verified"}, "'status' must be one of"),
        ({"citations": []}, "'citations' must be a non-empty list"),
        ({"citations": [{"url": "http://example.com", "quote": "x"}]}, "must be an https URL"),
        ({"citations": [{"url": "https://example.com", "quote": " "}]}, "non-empty verbatim quote"),
        ({"citations": [{"url": "https://example.com", "quote": "x", "page": 1}]}, "unknown keys ['page']"),
        ({"title": ""}, "'title' must be a non-empty string"),
        ({"extra": 1}, "unknown keys ['extra']"),
        ({"invalid_in_looker": "yes"}, "must be true or false"),
        ({"expect": {}}, "must map at least one model"),
        ({"expect": {"models": {"m": {}}}}, "at least one view or explore"),
        ({"expect": {"models": {"other": {"views": {"orders": {"fields": []}}}}}}, "without a .model.lkml"),
        ({"expect": {"models": {"m": {"views": {"orders": {"table": "x"}}}}}}, "unknown keys ['table']"),
        ({"expect": {"models": {"m": {"views": {"orders": {"fields": "id"}}}}}}, "must be a list of strings"),
        ({"expect": {"models": {"m": {"views": {"orders": {"sql_table_name": 1}}}}}}, "string or null"),
        (
            {"expect": {"models": {"m": {"views": {"orders": {"derived_table": {"sql": 1}}}}}}},
            "derived_table must map",
        ),
        (
            {
                "expect": {
                    "models": {"m": {"views": {"orders": {"field_params": {"id": {"filters": ["a"]}}}}}}
                }
            },
            "one-key objects",
        ),
        (
            {
                "expect": {
                    "models": {"m": {"views": {"orders": {"field_params": {"id": {"timeframes": "date"}}}}}}
                }
            },
            "timeframes must be a list of strings",
        ),
        (
            {"expect": {"models": {"m": {"views": {"orders": {"field_params": {"id": {"label": 1}}}}}}}},
            "label must be a string",
        ),
        (
            {"expect": {"models": {"m": {"explores": {"orders": {"joins": {"u": {"on": "x"}}}}}}}},
            "unknown keys ['on']",
        ),
        (
            {"expect": {"models": {"m": {"explores": {"orders": {"label": 1}}}}}},
            "label must be a string or null",
        ),
        ({"expect": {"models": {"m": {"views": {"orders": {}}}}}}, "must be a non-empty object"),
        (
            {"expect": {"models": {"m": {"views": {"orders": {"fields": []}}}}, "absent_views": "x"}},
            "absent_views' must be a list",
        ),
    ],
)
def test_rejects_invalid_case_files(make_case: MakeCase, overrides: dict[str, object], expected: str) -> None:
    case_id = overrides.get("id", "r01_example")
    directory = make_case(**overrides)
    if case_id != "r01_example":
        # The directory is named after the id, so rename it to provoke the mismatch or bad-id errors.
        directory = directory.rename(directory.with_name("r01_example"))

    assert expected in problems_of(directory)


def test_reports_every_problem_at_once(make_case: MakeCase) -> None:
    problems = problems_of(make_case(title="", status="unknown", citations=[]))

    assert "'title'" in problems
    assert "'status'" in problems
    assert "'citations'" in problems


def test_rejects_unknown_category(make_case: MakeCase) -> None:
    assert "category directory 'misc'" in problems_of(make_case(category="misc"))


def test_rejects_missing_project(make_case: MakeCase) -> None:
    directory = make_case(files={})

    assert "missing LookML project directory" in problems_of(directory)


def test_rejects_malformed_json(tmp_path: Path) -> None:
    directory = tmp_path / "refinements" / "r01_example"
    directory.mkdir(parents=True)
    (directory / "case.json").write_text("{not json", encoding="utf-8")

    assert "Expecting property name" in problems_of(directory)


def test_rejects_non_object_json(tmp_path: Path) -> None:
    directory = tmp_path / "refinements" / "r01_example"
    directory.mkdir(parents=True)
    (directory / "case.json").write_text("[]", encoding="utf-8")

    assert "must be a JSON object" in problems_of(directory)


@pytest.mark.parametrize(
    ("files", "expect", "requires"),
    [
        (None, {"models": {"m": {"views": {"orders": {"fields": ["id"]}}}}}, set()),
        (None, {"models": {"m": {"explores": {"orders": {"view_name": "orders"}}}}}, {"explores"}),
        (
            {"m.model.lkml": "", "imported_projects/shared/orders.view.lkml": ""},
            {"models": {"m": {"views": {"orders": {"fields": []}}}}},
            {"imported_projects"},
        ),
        (
            {"m.model.lkml": "", "manifest.lkml": 'constant: SCHEMA {\n  value: "x"\n}\n'},
            {"models": {"m": {"views": {"orders": {"fields": []}}}}},
            {"constants"},
        ),
        (
            {"m.model.lkml": "", "manifest.lkml": 'project_name: "p"\n'},
            {"models": {"m": {"views": {"orders": {"fields": []}}}}},
            set(),
        ),
    ],
)
def test_requires_is_derived_from_the_case(
    make_case: MakeCase, files: dict[str, str] | None, expect: dict[str, object], requires: set[str]
) -> None:
    case = load_case(make_case(files=files, expect=expect))

    assert case.requires == requires


def test_load_cases_orders_by_category_then_id(make_case: MakeCase, tmp_path: Path) -> None:
    make_case(category="syntax", id="p01_a")
    make_case(category="refinements", id="r02_b")
    make_case(category="refinements", id="r01_a")

    cases = load_cases(tmp_path / "cases")

    assert [case.id for case in cases] == ["r01_a", "r02_b", "p01_a"]
    assert [d.name for d in case_directories(tmp_path / "cases")] == ["r01_a", "r02_b", "p01_a"]


def test_load_cases_filters_by_id_substring(make_case: MakeCase, tmp_path: Path) -> None:
    make_case(id="r01_a")
    make_case(id="r02_b")

    assert [case.id for case in load_cases(tmp_path / "cases", only="r02")] == ["r02_b"]


def test_load_cases_reports_all_invalid_cases(make_case: MakeCase, tmp_path: Path) -> None:
    make_case(id="r01_a", title="")
    make_case(id="r02_b", status="nope")

    with pytest.raises(SuiteError) as excinfo:
        load_cases(tmp_path / "cases")

    assert [error.path.parent.name for error in excinfo.value.errors] == ["r01_a", "r02_b"]


def test_load_cases_rejects_duplicate_ids(make_case: MakeCase, tmp_path: Path) -> None:
    make_case(category="refinements", id="r01_a")
    make_case(category="includes", id="r01_a")

    with pytest.raises(SuiteError, match="duplicate case ids: r01_a"):
        load_cases(tmp_path / "cases")
