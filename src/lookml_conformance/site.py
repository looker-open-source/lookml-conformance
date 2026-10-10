"""Build ``site/data.json``: cases, citations, project files and the latest scorecard for the website."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import urldefrag

from lookml_conformance.cases import CATEGORIES, Case, Status
from lookml_conformance.catalog import CATEGORY_TITLES, citation_label
from lookml_conformance.runner import AdapterSpec
from lookml_conformance.scorecard import Scorecard

MAX_FILE_BYTES = 20_000


def build_site_data(
    cases: Sequence[Case], scorecard: Scorecard, adapters: Sequence[AdapterSpec]
) -> dict[str, Any]:
    results = {result.case_id: result for result in scorecard.results}
    if missing := sorted(case.id for case in cases if case.id not in results):
        raise ValueError(f"the scorecard has no results for: {', '.join(missing)}")
    specs = {adapter.name: adapter for adapter in adapters}
    citations = [citation for case in cases for citation in case.citations]
    return {
        "date": scorecard.date,
        "suite": {
            "cases": len(cases),
            "confirmed": sum(case.status is Status.CONFIRMED for case in cases),
            "provisional": sum(case.status is Status.PROVISIONAL for case in cases),
            "citations": len(citations),
            "pages": len({urldefrag(citation.url).url for citation in citations}),
        },
        "categories": [
            {"id": category, "title": CATEGORY_TITLES[category]}
            for category in CATEGORIES
            if any(case.category == category for case in cases)
        ],
        "tools": [_tool(run.name, run.version, scorecard, specs.get(run.name)) for run in scorecard.adapters],
        "cases": [_case(case, results[case.id].verdicts) for case in cases],
    }


def render_site_data(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def _tool(name: str, version: str | None, scorecard: Scorecard, spec: AdapterSpec | None) -> dict[str, Any]:
    def tally(status: str | None) -> dict[str, int]:
        result = scorecard.tally(name, status)
        return {"passed": result.passed, "applicable": result.applicable}

    return {
        "name": name,
        "label": spec.display_name if spec else name,
        "kind": spec.kind if spec else None,
        "language": spec.language if spec else None,
        "url": spec.url if spec else None,
        "package": next(iter(spec.install.values()), None) if spec else None,
        "version": version,
        "score": {"all": tally(None), **{status.value: tally(status.value) for status in Status}},
    }


def _case(case: Case, verdicts: Any) -> dict[str, Any]:
    return {
        "id": case.id,
        "category": case.category,
        "title": case.title,
        "rule": case.rule,
        "status": case.status.value,
        "basis": [basis.value for basis in case.basis],
        "citations": [
            {"url": citation.url, "quote": citation.quote, "label": citation_label(citation)}
            for citation in case.citations
        ],
        "rationale": case.rationale,
        "provisional": None
        if case.provisional is None
        else {"question": case.provisional.question, "pinned_to": case.provisional.pinned_to},
        "observations": [
            {
                "looker_version": observation.looker_version,
                "date": observation.date.isoformat(),
                "finding": observation.finding,
                "evidence": observation.evidence,
            }
            for observation in case.observations
        ],
        "invalid_in_looker": case.invalid_in_looker,
        "expect": {
            "models": {
                name: {"views": dict(model.views), "explores": dict(model.explores)}
                for name, model in case.models.items()
            },
            "absent_views": list(case.absent_views),
        },
        "files": [
            {"path": path.as_posix(), "content": (case.project / path).read_text(encoding="utf-8")}
            for path in case.project_files()
            if (case.project / path).stat().st_size <= MAX_FILE_BYTES
        ],
        "verdicts": {
            name: {"outcome": verdict.outcome.value, "reasons": list(verdict.reasons)}
            for name, verdict in verdicts.items()
        },
    }
