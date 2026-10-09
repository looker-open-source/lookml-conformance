"""Helpers for Python adapters: reshape a tool's output into the protocol.

These helpers never merge refinements, substitute constants or fill any other gap the tool leaves.
The adapter base class is :class:`lookml_conformance.adapter.Adapter`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lookml_conformance.cases import IMPORTED_PROJECTS_DIR, MODEL_SUFFIX
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import Upstream, ViewOutput

FIELD_TEXT_PARAMS = ("sql", "label", "type")
FIELD_COLLECTIONS = ("dimensions", "dimension_groups", "measures")


def flatten_repeated(groups: Iterable[Any] | None) -> list[Any]:
    """Flatten lkml's ``<key>__all`` lists, which hold one entry per occurrence of a repeated key."""
    flat: list[Any] = []
    for group in groups or []:
        flat.extend(group if isinstance(group, (list, tuple)) else [group])
    return flat


def normalize_filters(raw: Any) -> list[dict[str, str]]:
    """Filters as ordered one-key objects. Accepts ``{field: value}`` maps and ``{field, value}`` pairs."""
    filters = []
    for entry in flatten_repeated(raw if isinstance(raw, (list, tuple)) else [raw] if raw else []):
        if not isinstance(entry, Mapping):
            continue
        if set(entry) == {"field", "value"}:
            filters.append({str(entry["field"]): str(entry["value"])})
        else:
            filters.extend({str(key): str(value)} for key, value in entry.items())
    return filters


def field_params(field: Mapping[str, Any]) -> dict[str, Any]:
    """The parameters the suite checks on a field, from an lkml-style field dictionary."""
    params: dict[str, Any] = {
        key: collapse_whitespace(field[key]) for key in FIELD_TEXT_PARAMS if field.get(key) is not None
    }
    if (timeframes := field.get("timeframes")) is not None:
        params["timeframes"] = [
            str(item) for item in (timeframes if isinstance(timeframes, list) else [timeframes])
        ]
    if filters := normalize_filters(field.get("filters__all") or field.get("filters")):
        params["filters"] = filters
    return params


def derived_table(raw: Mapping[str, Any] | None, sql: str | None = None) -> dict[str, str] | None:
    """Scalar derived_table parameters; ``sql`` overrides the raw SQL when the tool rewrites it."""
    if not raw:
        return None
    params = {"sql": collapse_whitespace(sql if sql is not None else raw.get("sql"))}
    params |= {
        str(key): str(value)
        for key, value in raw.items()
        if key != "sql" and isinstance(value, (str, int, float, bool))
    }
    return {key: value for key, value in params.items() if value is not None}


def view_output(
    view: Mapping[str, Any],
    *,
    sql_table_name: str | None = None,
    derived_table_sql: str | None = None,
    fields: Sequence[Mapping[str, Any]] | None = None,
    upstream: Iterable[Upstream] | None = None,
) -> ViewOutput:
    """Build a view from an lkml-style view dictionary.

    Keyword arguments replace what the tool computes separately from the raw dictionary, such as a
    table name after the tool's own constant substitution. ``upstream`` is the view's direct
    upstreams in the tool's lineage; leave it ``None`` when the tool reports no lineage.
    """
    if fields is None:
        fields = [
            field
            for collection in FIELD_COLLECTIONS
            for field in view.get(collection) or []
            if isinstance(field, Mapping) and "name" in field
        ]
    # lkml reports extends as "extends__all"; some tools write their merged list back as "extends".
    extends = flatten_repeated(view.get("extends", view.get("extends__all")))
    return ViewOutput(
        sql_table_name=collapse_whitespace(
            sql_table_name if sql_table_name is not None else view.get("sql_table_name")
        ),
        derived_table=derived_table(view.get("derived_table"), derived_table_sql),
        fields=tuple(sorted(str(field["name"]) for field in fields)),
        field_params={str(field["name"]): field_params(field) for field in fields},
        extends=tuple(str(item) for item in extends) or None,
        upstream=None if upstream is None else tuple(upstream),
    )


def model_files(root: Path) -> list[Path]:
    """The project's model files, excluding those of imported projects."""
    return sorted(
        path
        for path in root.rglob(f"*{MODEL_SUFFIX}")
        if IMPORTED_PROJECTS_DIR not in path.relative_to(root).parts
    )


def model_name(path: Path) -> str:
    return path.name.removesuffix(MODEL_SUFFIX)


def imported_projects(root: Path) -> dict[str, Path]:
    """Imported projects of the suite layout: ``imported_projects/<name>/``."""
    directory = root / IMPORTED_PROJECTS_DIR
    return (
        {path.name: path.resolve() for path in sorted(directory.iterdir()) if path.is_dir()}
        if directory.is_dir()
        else {}
    )
