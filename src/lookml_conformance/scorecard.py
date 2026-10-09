"""Scorecards: the verdict of every adapter on every case, with JSON and Markdown renderings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lookml_conformance.cases import Status
from lookml_conformance.judge import Outcome, Verdict

MARKS = {Outcome.PASS: "✅", Outcome.FAIL: "❌", Outcome.ERROR: "⚠️", Outcome.NOT_APPLICABLE: "N/A"}
STATUS_ORDER = tuple(status.value for status in Status)


@dataclass(frozen=True)
class AdapterRun:
    name: str
    version: str | None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    status: str
    verdicts: Mapping[str, Verdict]


@dataclass(frozen=True)
class Tally:
    passed: int
    applicable: int

    def __str__(self) -> str:
        return f"{self.passed} / {self.applicable}"


@dataclass(frozen=True)
class Scorecard:
    date: str
    adapters: tuple[AdapterRun, ...]
    results: tuple[CaseResult, ...]

    @property
    def failed(self) -> bool:
        return any(verdict.failed for result in self.results for verdict in result.verdicts.values())

    def statuses(self) -> list[str]:
        present = {result.status for result in self.results}
        return [status for status in STATUS_ORDER if status in present] + sorted(present - set(STATUS_ORDER))

    def tally(self, adapter: str, status: str | None = None) -> Tally:
        verdicts = [
            result.verdicts[adapter]
            for result in self.results
            if adapter in result.verdicts and status in (None, result.status)
        ]
        applicable = [verdict for verdict in verdicts if verdict.outcome.applicable]
        return Tally(sum(verdict.outcome is Outcome.PASS for verdict in applicable), len(applicable))

    def failures(self) -> list[tuple[CaseResult, str, Verdict]]:
        return [
            (result, adapter.name, result.verdicts[adapter.name])
            for result in self.results
            for adapter in self.adapters
            if result.verdicts[adapter.name].failed
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "adapters": [{"name": run.name, "version": run.version} for run in self.adapters],
            "results": [
                {
                    "case": result.case_id,
                    "category": result.category,
                    "status": result.status,
                    "verdicts": {
                        name: {"outcome": verdict.outcome.value, "reasons": list(verdict.reasons)}
                        for name, verdict in result.verdicts.items()
                    },
                }
                for result in self.results
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Scorecard:
        return cls(
            date=data["date"],
            adapters=tuple(AdapterRun(entry["name"], entry.get("version")) for entry in data["adapters"]),
            results=tuple(
                CaseResult(
                    case_id=entry["case"],
                    category=entry["category"],
                    status=entry["status"],
                    verdicts={
                        name: Verdict(Outcome(verdict["outcome"]), tuple(verdict.get("reasons", [])))
                        for name, verdict in entry["verdicts"].items()
                    },
                )
                for entry in data["results"]
            ),
        )


def render_markdown(scorecard: Scorecard, labels: Mapping[str, str] | None = None) -> str:
    """A Markdown report: the case matrix, a pass/applicable summary, and every failure reason."""
    labels = labels or {}
    names = [run.name for run in scorecard.adapters]
    headers = [labels.get(name, name) for name in names]
    statuses = scorecard.statuses()
    lines = [
        f"# LookML conformance scorecard, {scorecard.date}",
        "",
        "✅ pass · ❌ fail · ⚠️ adapter error · N/A not applicable (the tool does not produce that output). "
        "*confirmed* cases follow from the cited Looker documentation; *provisional* cases cover behavior "
        "the documentation leaves open and are pinned to a named public source.",
        "",
        "## Summary (passed / applicable)",
        "",
        _row(["Tool", "Version", *statuses, "All"]),
        _row(["---"] * (len(statuses) + 3)),
        *(
            _row(
                [
                    labels.get(run.name, run.name),
                    f"`{run.version}`" if run.version else "unknown",
                    *(str(scorecard.tally(run.name, status)) for status in statuses),
                    f"**{scorecard.tally(run.name)}**",
                ]
            )
            for run in scorecard.adapters
        ),
        "",
        "## Results",
        "",
        _row(["Case", "Status", *headers]),
        _row(["---"] * (len(names) + 2)),
        *(
            _row(
                [
                    f"`{result.case_id}`",
                    result.status,
                    *(MARKS[result.verdicts[name].outcome] for name in names),
                ]
            )
            for result in scorecard.results
        ),
        "",
        "## Failure details",
        "",
    ]
    failures = scorecard.failures()
    lines += [
        f"- `{result.case_id}` · **{labels.get(name, name)}**: " + "; ".join(verdict.reasons)
        for result, name, verdict in failures
    ] or ["None."]
    return "\n".join(lines) + "\n"


def render_text(scorecard: Scorecard) -> str:
    """A plain-text summary for the terminal: failures first, then the tally table."""
    lines = [
        f"{verdict.outcome.value.upper():5} {result.case_id} [{name}]: {'; '.join(verdict.reasons)}"
        for result, name, verdict in scorecard.failures()
    ]
    statuses = scorecard.statuses()
    table = [["adapter", "version", *statuses, "all"]] + [
        [
            run.name,
            run.version or "?",
            *(str(scorecard.tally(run.name, s)) for s in statuses),
            str(scorecard.tally(run.name)),
        ]
        for run in scorecard.adapters
    ]
    widths = [max(len(row[column]) for row in table) for column in range(len(table[0]))]
    if lines:
        lines.append("")
    lines += [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in table
    ]
    return "\n".join(lines) + "\n"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"
