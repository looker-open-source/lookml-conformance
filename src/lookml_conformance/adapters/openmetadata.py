"""Adapter for OpenMetadata's Looker connector (``openmetadata-ingestion[looker]``).

    python -m lookml_conformance.adapters.openmetadata <project>

The connector reads views from the repository with ``BulkLkmlParser`` and takes explores from the
Looker API, so the adapter reports views only (``explores: false``). When ``find_view`` accepts
``model_name`` (a branch with model scoping), each model is resolved separately; otherwise the
project-wide views are reported as one model. ``@{constant}`` references are substituted with
``LookerSource._resolve_lookml_constants``, the function the connector applies to
``sql_table_name`` and derived table SQL.
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import lkml
from metadata.ingestion.source.dashboard.looker.bulk_parser import BulkLkmlParser
from metadata.ingestion.source.dashboard.looker.metadata import LookerSource
from metadata.ingestion.source.dashboard.looker.models import LookMLManifest
from metadata.readers.file.local import LocalReader
from metadata.utils.singleton import Singleton

from lookml_conformance.adapters import kit
from lookml_conformance.protocol import AdapterOutput, Capabilities, ModelOutput, ViewOutput

NAME = "openmetadata"
DISTRIBUTION = "openmetadata-ingestion"
PROJECT_WIDE = "*"


class ConstantResolver:
    """Substitutes manifest constants with the connector's own function."""

    def __init__(self, root: Path) -> None:
        constants: dict[str, str] = {}
        manifest = root / "manifest.lkml"
        if manifest.is_file():
            parsed = LookMLManifest.model_validate(lkml.load(manifest.read_text(encoding="utf-8")))
            constants = {constant["name"]: constant.get("value", "") for constant in parsed.constants or []}
        # _resolve_lookml_constants reads nothing but this attribute from the source.
        self._source = SimpleNamespace(_lookml_constants_map=constants)

    def __call__(self, text: str | None, *, strip_unresolved: bool) -> str | None:
        if text is None:
            return None
        return LookerSource._resolve_lookml_constants(self._source, text, strip_unresolved=strip_unresolved)


def summarize_view(view: Any, resolve_constants: ConstantResolver) -> ViewOutput:
    # Released versions model dimensions and measures; dimension_groups is read if a branch adds it.
    fields = [*view.dimensions, *(getattr(view, "dimension_groups", None) or []), *view.measures]
    raw = view.model_dump(by_alias=True, exclude_none=True)
    derived = raw.get("derived_table")
    return kit.view_output(
        raw,
        sql_table_name=resolve_constants(view.sql_table_name, strip_unresolved=True),
        derived_table_sql=resolve_constants(derived.get("sql"), strip_unresolved=False) if derived else None,
        fields=[field.model_dump(exclude_none=True) for field in fields],
    )


def resolve_views(
    parser: BulkLkmlParser, names: list[str], resolve_constants: ConstantResolver, model: str | None
) -> dict[str, ViewOutput]:
    views = {}
    for name in names:
        try:
            view = parser.find_view(name) if model is None else parser.find_view(name, model_name=model)
            if view is not None:
                views[name] = summarize_view(view, resolve_constants)
        except Exception as exc:  # reported for this view only
            views[name] = ViewOutput(error=repr(exc))
    return views


def resolve(root: Path, args: argparse.Namespace) -> AdapterOutput:
    Singleton.clear_all()  # BulkLkmlParser is a process-wide singleton.
    parser = BulkLkmlParser(reader=LocalReader(base_path=root))
    # Every view the connector would ingest, including refinements it caches as "+name" views.
    names = sorted(parser._views_cache)
    resolve_constants = ConstantResolver(root)
    per_model = "model_name" in inspect.signature(parser.find_view).parameters
    scopes = [kit.model_name(path) for path in kit.model_files(root)] if per_model else [None]
    return AdapterOutput(
        adapter=NAME,
        capabilities=Capabilities(per_model=per_model, explores=False),
        models={
            scope or PROJECT_WIDE: ModelOutput(
                views=resolve_views(parser, names, resolve_constants, scope), all_views=tuple(names)
            )
            for scope in scopes
        },
    )


def main() -> int:
    return kit.run_adapter(NAME, DISTRIBUTION, resolve)


if __name__ == "__main__":
    raise SystemExit(main())
