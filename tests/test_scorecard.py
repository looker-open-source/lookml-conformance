from __future__ import annotations

from lookml_conformance.judge import Outcome, Verdict
from lookml_conformance.scorecard import (
    AdapterRun,
    CaseResult,
    Scorecard,
    Tally,
    render_markdown,
    render_text,
)

PASS = Verdict(Outcome.PASS)
NA = Verdict(Outcome.NOT_APPLICABLE, ("adapter does not support explores",))


def sample() -> Scorecard:
    return Scorecard(
        date="2026-10-09",
        adapters=(AdapterRun("a", "1.0"), AdapterRun("b", None)),
        results=(
            CaseResult(
                "r01_x", "refinements", "confirmed", {"a": PASS, "b": Verdict(Outcome.FAIL, ("m.v.f: bad",))}
            ),
            CaseResult(
                "i01_y", "includes", "provisional", {"a": PASS, "b": Verdict(Outcome.ERROR, ("crashed",))}
            ),
            CaseResult("x01_z", "explores", "confirmed", {"a": Verdict(Outcome.FAIL, ("nope",)), "b": NA}),
        ),
    )


def test_tally_counts_passes_over_applicable_cases() -> None:
    scorecard = sample()

    assert scorecard.tally("a") == Tally(2, 3)
    assert scorecard.tally("b") == Tally(0, 2)
    assert scorecard.tally("a", "confirmed") == Tally(1, 2)
    assert scorecard.tally("b", "provisional") == Tally(0, 1)
    assert str(Tally(2, 3)) == "2 / 3"


def test_failed_and_failures() -> None:
    scorecard = sample()

    assert scorecard.failed
    assert [(result.case_id, name) for result, name, _ in scorecard.failures()] == [
        ("r01_x", "b"),
        ("i01_y", "b"),
        ("x01_z", "a"),
    ]


def test_a_clean_scorecard_has_not_failed() -> None:
    scorecard = Scorecard(
        "2026-10-09", (AdapterRun("a", "1"),), (CaseResult("r01", "refinements", "confirmed", {"a": NA}),)
    )

    assert not scorecard.failed


def test_statuses_follow_the_status_order() -> None:
    assert sample().statuses() == ["confirmed", "provisional"]


def test_round_trips_through_json() -> None:
    scorecard = sample()

    assert Scorecard.from_dict(scorecard.to_dict()) == scorecard


def test_markdown_report() -> None:
    markdown = render_markdown(sample(), labels={"a": "Tool A"})

    assert markdown.startswith("# LookML conformance scorecard, 2026-10-09\n")
    assert "| Tool A | `1.0` | 1 / 2 | 1 / 1 | **2 / 3** |" in markdown
    assert "| b | unknown | 0 / 1 | 0 / 1 | **0 / 2** |" in markdown
    assert "| Case | Status | Tool A | b |" in markdown
    assert "| `x01_z` | confirmed | ❌ | N/A |" in markdown
    assert "- `r01_x` · **b**: m.v.f: bad" in markdown


def test_markdown_report_without_failures() -> None:
    scorecard = Scorecard(
        "2026-10-09", (AdapterRun("a", "1"),), (CaseResult("r01", "refinements", "confirmed", {"a": PASS}),)
    )

    assert render_markdown(scorecard).endswith("## Failure details\n\nNone.\n")


def test_text_summary() -> None:
    text = render_text(sample())

    assert "FAIL  r01_x [b]: m.v.f: bad" in text
    assert "ERROR i01_y [b]: crashed" in text
    assert text.splitlines()[-2:] == [
        "a        1.0      1 / 2      1 / 1        2 / 3",
        "b        ?        0 / 1      0 / 1        0 / 2",
    ]
