from __future__ import annotations

import pytest

from lookml_conformance.cases import load_case
from lookml_conformance.citations import CitationProblem, check_citations, normalize, page_text
from tests.conftest import MakeCase

PAGE = """<html><head><title>Refinements</title><style>p { color: red }</style>
<script>var quote = "In most cases a refinement will override";</script></head>
<body><h2 id="order">Order</h2>
<p>It is important to note that in most cases a refinement will override the original settings of an
   object.</p><p>Use the <code>view</code> parameter&nbsp;with the same name, and it&#8217;s a
<a href="#x">refinement</a>.</p><ul><li>first</li><li>second</li></ul></body></html>"""


def test_page_text_keeps_inline_markup_together_and_separates_blocks() -> None:
    text = page_text(PAGE)

    assert "Use the view parameter with the same name, and it's a refinement." in text
    assert "first second" in text
    assert "color: red" not in text
    assert "var quote" not in text


def test_normalize_straightens_quotes_and_collapses_whitespace() -> None:
    apostrophe = "\N{RIGHT SINGLE QUOTATION MARK}"
    curly = f"it{apostrophe}s \N{LEFT DOUBLE QUOTATION MARK}quoted\N{RIGHT DOUBLE QUOTATION MARK}"

    assert normalize(f"  {curly}\n&amp;\N{NO-BREAK SPACE}done ") == 'it\'s "quoted" & done'


def test_check_citations_fetches_each_page_once(make_case: MakeCase) -> None:
    cases = [load_case(make_case(id="r01_a")), load_case(make_case(id="r02_b"))]
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return PAGE

    # The default citation quotes "In most cases ...", capitalized, which the page does not contain.
    problems = check_citations(cases, fetch)

    assert fetched == ["https://docs.cloud.google.com/looker/docs/lookml-refinements"]
    assert [problem.case_id for problem in problems] == ["r01_a", "r02_b"]
    assert {problem.reason for problem in problems} == {"quote not found on the page"}


def test_check_citations_accepts_present_quotes(make_case: MakeCase) -> None:
    citation = {
        "url": "https://docs.example.com/page#order",
        "quote": "in most cases a refinement will override the original settings of an object.",
    }
    case = load_case(make_case(citations=[citation]))

    assert check_citations([case], lambda url: PAGE) == []


def test_check_citations_reports_fetch_errors(make_case: MakeCase) -> None:
    case = load_case(make_case())

    def fetch(url: str) -> str:
        raise OSError("network unreachable")

    assert check_citations([case], fetch) == [
        CitationProblem(
            case_id=case.id,
            url=case.citations[0].url,
            quote=case.citations[0].quote,
            reason="cannot fetch: network unreachable",
        )
    ]


@pytest.mark.parametrize("quote", ["it's a refinement", "it\N{RIGHT SINGLE QUOTATION MARK}s a refinement"])
def test_quotes_match_regardless_of_apostrophe_style(make_case: MakeCase, quote: str) -> None:
    case = load_case(make_case(citations=[{"url": "https://docs.example.com/p", "quote": quote}]))

    assert check_citations([case], lambda url: PAGE) == []
