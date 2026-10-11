"""Compare an adapter's output with a case's expectations."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from lookml_conformance.cases import Case, ModelExpectation
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import AdapterOutput, ExploreOutput, ModelOutput, Upstream, ViewOutput


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    NOT_APPLICABLE = "n/a"

    @property
    def applicable(self) -> bool:
        return self is not Outcome.NOT_APPLICABLE


@dataclass(frozen=True)
class Verdict:
    """The outcome of one adapter on one case, with the reasons for anything but a pass."""

    outcome: Outcome
    reasons: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.outcome in (Outcome.FAIL, Outcome.ERROR)


def judge(case: Case, output: AdapterOutput) -> Verdict:
    if output.error is not None:
        return Verdict(Outcome.ERROR, (output.error,))
    if missing := sorted(capability for capability in case.requires if output.capabilities.lacks(capability)):
        return Verdict(Outcome.NOT_APPLICABLE, tuple(f"adapter does not support {name}" for name in missing))

    reasons = [
        *(
            reason
            for model_name, expected in case.models.items()
            for reason in _check_model(model_name, expected, _model_for(model_name, output))
        ),
        *_check_absent_views(case.absent_views, output),
    ]
    if case.invalid_in_looker:
        # Looker rejects the project, so a tool may report an error for a view instead of resolving
        # it. It still fails if it resolves the view to anything but the expectation.
        errors = set(_view_errors(case, output))
        accepted = [reason for reason in reasons if reason in errors]
        reasons = [reason for reason in reasons if reason not in errors]
        if not reasons:
            return Verdict(
                Outcome.PASS, tuple(f"accepted for a project Looker rejects: {r}" for r in accepted)
            )
    return Verdict(Outcome.FAIL, tuple(reasons)) if reasons else Verdict(Outcome.PASS)


def _view_errors(case: Case, output: AdapterOutput) -> Iterator[str]:
    """The reasons ``_check_model`` gives for expected views the tool reported as errors."""
    for model_name, expected in case.models.items():
        model = _model_for(model_name, output)
        for view_name in expected.views:
            view = None if model is None else model.views.get(view_name)
            if view is not None and view.error is not None:
                yield f"{model_name}.{view_name}: {view.error}"


def _model_for(name: str, output: AdapterOutput) -> ModelOutput | None:
    if name in output.models:
        return output.models[name]
    if not output.capabilities.per_model and len(output.models) == 1:
        # A tool without model scoping reports one project-wide model, which must satisfy every model.
        return next(iter(output.models.values()))
    return None


def _check_model(name: str, expected: ModelExpectation, got: ModelOutput | None) -> Iterator[str]:
    if got is None:
        yield f"{name}: model not resolved"
        return
    for view_name, expected_view in expected.views.items():
        where = f"{name}.{view_name}"
        view = got.views.get(view_name)
        if view is None:
            yield f"{where}: view not resolved"
        elif view.error is not None:
            yield f"{where}: {view.error}"
        else:
            yield from _check_view(where, expected_view, view)
            if "upstream_tables" in expected_view:
                yield from _check_upstream(where, expected_view["upstream_tables"], view, got)
    for explore_name, expected_explore in expected.explores.items():
        where = f"{name}.explore.{explore_name}"
        explore = got.explores.get(explore_name)
        if explore is None:
            yield f"{where}: explore not resolved"
        else:
            yield from _check_explore(where, expected_explore, explore)


def _check_view(where: str, expected: Mapping[str, Any], got: ViewOutput) -> Iterator[str]:
    if "sql_table_name" in expected:
        yield from _compare_text(f"{where}.sql_table_name", expected["sql_table_name"], got.sql_table_name)
    if "derived_table" in expected:
        actual = got.derived_table or {}
        for param, value in (expected["derived_table"] or {}).items():
            yield from _compare_text(f"{where}.derived_table.{param}", value, actual.get(param))
    if "fields" in expected and sorted(got.fields) != sorted(expected["fields"]):
        yield _mismatch(f"{where}.fields", sorted(expected["fields"]), sorted(got.fields))
    for field_name, params in (expected.get("field_params") or {}).items():
        actual_params = got.field_params.get(field_name)
        if actual_params is None:
            yield f"{where}.{field_name}: field not resolved"
            continue
        for param, value in params.items():
            yield from _compare_field_param(
                f"{where}.{field_name}.{param}", param, value, actual_params.get(param)
            )
    if "extends" in expected and list(got.extends or []) != expected["extends"]:
        yield _mismatch(
            f"{where}.extends", expected["extends"], None if got.extends is None else list(got.extends)
        )


def _check_upstream(where: str, expected: list[str], view: ViewOutput, model: ModelOutput) -> Iterator[str]:
    want = sorted({_table_key(name) for name in expected})
    if view.upstream is None:
        yield f"{where}.upstream_tables: expected {want!r}, got no lineage"
        return
    tables, unresolved = upstream_tables(view, model)
    if sorted(tables) != want:
        reported = [str(edge) for edge in view.upstream]
        detail = f"; reported upstream: {reported}" + (f"; not resolved: {unresolved}" if unresolved else "")
        yield _mismatch(f"{where}.upstream_tables", want, sorted(tables)) + detail


def upstream_tables(view: ViewOutput, model: ModelOutput) -> tuple[set[str], list[str]]:
    """The warehouse tables a view reads, following the tool's own view and explore upstreams.

    A view upstream contributes that view's tables; an explore contributes the tables of its base
    view and joined views, as the tool resolved the explore. Returns the tables, and the upstream
    views and explores the tool reported but did not resolve.
    """
    tables: set[str] = set()
    unresolved: set[str] = set()
    seen: set[Upstream] = set()
    pending = list(view.upstream or ())
    while pending:
        edge = pending.pop()
        if edge.kind == "table":
            tables.add(_table_key(edge.name))
            continue
        if edge in seen:
            continue
        seen.add(edge)
        if edge.kind == "view":
            upstream_view = model.views.get(edge.name)
            if upstream_view is None or upstream_view.upstream is None:
                unresolved.add(str(edge))
            else:
                pending.extend(upstream_view.upstream)
        elif (explore := model.explores.get(edge.name)) is None:
            unresolved.add(str(edge))
        else:
            pending.extend(Upstream("view", name) for name in _explore_views(edge.name, explore))
    return tables, sorted(unresolved)


def _explore_views(name: str, explore: ExploreOutput) -> list[str]:
    base = explore.from_view or explore.view_name or name
    return [base, *((join.get("from") or join_name) for join_name, join in explore.joins.items())]


def _table_key(name: str) -> str:
    return (collapse_whitespace(name) or "").lower()


def _compare_field_param(where: str, param: str, expected: Any, actual: Any) -> Iterator[str]:
    if param == "filters":
        # Filters are compared in order: refinement filters are appended after the base filters.
        if actual != expected:
            yield _mismatch(where, expected, actual)
    elif param == "timeframes":
        if sorted(actual or []) != sorted(expected):
            yield _mismatch(where, sorted(expected), None if actual is None else sorted(actual))
    else:
        yield from _compare_text(where, expected, actual)


def _check_explore(where: str, expected: Mapping[str, Any], got: ExploreOutput) -> Iterator[str]:
    for key in ("view_name", "from", "label"):
        if key in expected:
            yield from _compare_text(f"{where}.{key}", expected[key], got.get(key))
    for join_name, expected_join in (expected.get("joins") or {}).items():
        join = got.joins.get(join_name)
        if join is None:
            yield f"{where}.join.{join_name}: join not resolved"
            continue
        for key, value in expected_join.items():
            yield from _compare_text(f"{where}.join.{join_name}.{key}", value, join.get(key))


def _check_absent_views(absent: tuple[str, ...], output: AdapterOutput) -> Iterator[str]:
    exposed = {view for model in output.models.values() for view in model.exposed_views}
    if present := [view for view in absent if view in exposed]:
        yield f"views that must not exist were exposed: {present}"


def _compare_text(where: str, expected: Any, actual: Any) -> Iterator[str]:
    if collapse_whitespace(actual) != collapse_whitespace(expected):
        yield _mismatch(where, expected, actual)


def _mismatch(where: str, expected: Any, actual: Any) -> str:
    return f"{where}: expected {expected!r}, got {actual!r}"
