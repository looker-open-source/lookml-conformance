"""Checks on the suite itself: every case in cases/ is valid, traceable and documented in CASES.md."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from lookml_conformance.cases import CATEGORIES, Case, Status, load_cases
from lookml_conformance.catalog import render_catalog
from tests.conftest import CASES_ROOT, REPO_ROOT

CASES = load_cases(CASES_ROOT)
# Where citations may point: the Looker documentation and the Looker Community knowledge base.
CITATION_HOSTS = {"docs.cloud.google.com", "community.looker.com"}


def by_id(case: Case) -> str:
    return case.id


def test_the_suite_covers_every_category() -> None:
    assert {case.category for case in CASES} == set(CATEGORIES)


def test_case_ids_carry_a_category_prefix() -> None:
    prefixes = {"refinements": "r", "includes": "i", "extends": "e", "model_scope": "m", "explores": "x",
                "constants": "c", "syntax": "p"}  # fmt: skip
    assert [case.id for case in CASES if not case.id.startswith(prefixes[case.category])] == []


@pytest.mark.parametrize("case", CASES, ids=by_id)
def test_citations_point_at_looker_documentation(case: Case) -> None:
    assert {urlsplit(citation.url).netloc for citation in case.citations} <= CITATION_HOSTS


@pytest.mark.parametrize("case", CASES, ids=by_id)
def test_citations_are_short_unique_quotes(case: Case) -> None:
    quotes = [citation.quote for citation in case.citations]
    assert len(quotes) == len(set(quotes))
    assert all(len(quote) <= 160 for quote in quotes)
    assert all("`" not in quote and "…" not in quote and "..." not in quote for quote in quotes)


@pytest.mark.parametrize("case", [case for case in CASES if case.status is Status.PROVISIONAL], ids=by_id)
def test_provisional_cases_state_their_question(case: Case) -> None:
    assert case.provisional is not None
    assert case.provisional.question.endswith(("?", "."))


@pytest.mark.parametrize("case", CASES, ids=by_id)
def test_rules_are_single_sentences(case: Case) -> None:
    assert case.rule.endswith(".")
    assert case.rule.count(". ") == 0


def test_cases_md_is_up_to_date() -> None:
    rendered = render_catalog(CASES, cases_path="cases")

    assert (REPO_ROOT / "CASES.md").read_text(encoding="utf-8") == rendered, "run: lookml-conformance catalog"
