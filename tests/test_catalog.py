from __future__ import annotations

from lookml_conformance.cases import Citation, load_case
from lookml_conformance.catalog import citation_label, render_catalog
from tests.conftest import MakeCase


def test_citation_label() -> None:
    assert citation_label(Citation("https://docs.example.com/looker/docs/page#anchor", "q")) == "page#anchor"
    assert citation_label(Citation("https://docs.example.com/looker/docs/page/", "q")) == "page"
    assert citation_label(Citation("https://example.com", "q")) == "example.com"


def test_render_catalog(make_case: MakeCase) -> None:
    confirmed = load_case(make_case(id="r01_a", rationale="Because."))
    provisional = load_case(
        make_case(
            category="includes",
            id="i01_b",
            status="provisional",
            provisional={"question": "Which order?", "pinned_to": "tool 1.0"},
            invalid_in_looker=True,
        )
    )

    catalog = render_catalog([confirmed, provisional])

    assert catalog.startswith("# Cases\n")
    assert "| [Refinements](#refinements) | 1 | 1 | 0 |" in catalog
    assert "| [Includes](#includes) | 1 | 0 | 1 |" in catalog
    assert "| **Total** | 2 | 1 | 1 |" in catalog
    assert "## Refinements\n\n### `r01_a`\n\n**An example case.** *confirmed*" in catalog
    assert "Rule: A refinement overrides sql_table_name." in catalog
    assert (
        "> In most cases a refinement will override the original settings of an object.<br>"
        "[lookml-refinements#refinements_override_parameters]"
    ) in catalog
    assert "Why: Because." in catalog
    assert "Open question: Which order?\n\nPinned to: tool 1.0" in catalog
    assert "Looker rejects this project." in catalog
    assert "[`project/`](cases/includes/i01_b/project)" in catalog
    assert catalog.endswith("[`project/`](cases/includes/i01_b/project)\n")
