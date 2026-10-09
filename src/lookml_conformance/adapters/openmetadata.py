"""Adapter for OpenMetadata's Looker connector (``openmetadata-ingestion[looker]``).

    python -m lookml_conformance.adapters.openmetadata <project>...

The connector reads views from the repository with ``BulkLkmlParser`` and takes explores from the
Looker API, so the adapter reports views only. ``BulkLkmlParser`` has no model scope, so the views
are reported as one project-wide model. ``@{constant}`` references are substituted with the
function the connector applies to ``sql_table_name`` and derived table SQL.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import lkml
from metadata.ingestion.source.dashboard.looker.bulk_parser import BulkLkmlParser
from metadata.ingestion.source.dashboard.looker.metadata import LookerSource
from metadata.ingestion.source.dashboard.looker.models import LookMLManifest
from metadata.readers.file.local import LocalReader
from metadata.utils.singleton import Singleton

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.protocol import Capabilities, ModelOutput, ViewOutput

PROJECT_WIDE = "*"


class OpenMetadataAdapter(Adapter):
    name = "openmetadata"
    distribution = "openmetadata-ingestion"
    capabilities = Capabilities(per_model=False, explores=False)

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        Singleton.clear_all()  # BulkLkmlParser is a process-wide singleton
        parser = BulkLkmlParser(reader=LocalReader(base_path=project))
        constants = manifest_constants(project)
        # Every view the connector would ingest, including refinements it indexes as "+name" views.
        names = indexed_view_names(parser)
        views = {name: self._view(parser, name, constants) for name in names}
        return {
            PROJECT_WIDE: ModelOutput(
                views={name: view for name, view in views.items() if view is not None}, all_views=tuple(names)
            )
        }

    def _view(self, parser: BulkLkmlParser, name: str, constants: dict[str, str]) -> ViewOutput | None:
        try:
            view = parser.find_view(name)
            return None if view is None else summarize_view(view, constants)
        except Exception as exc:  # reported for this view only
            return ViewOutput(error=repr(exc))


def summarize_view(view: Any, constants: dict[str, str]) -> ViewOutput:
    # Released versions model dimensions and measures but not dimension groups.
    fields = [*view.dimensions, *(getattr(view, "dimension_groups", None) or []), *view.measures]
    raw = view.model_dump(by_alias=True, exclude_none=True)
    derived = raw.get("derived_table") or {}
    return kit.view_output(
        raw,
        sql_table_name=substitute_constants(view.sql_table_name, constants, strip_unresolved=True),
        derived_table_sql=substitute_constants(derived.get("sql"), constants, strip_unresolved=False),
        fields=[field.model_dump(exclude_none=True) for field in fields],
    )


def manifest_constants(project: Path) -> dict[str, str]:
    """Manifest constants, read the way the connector reads them (``LookMLManifest``)."""
    manifest = project / "manifest.lkml"
    if not manifest.is_file():
        return {}
    parsed = LookMLManifest.model_validate(lkml.load(manifest.read_text(encoding="utf-8")))
    return {constant["name"]: constant.get("value", "") for constant in parsed.constants or []}


# Private OpenMetadata APIs. Both are pinned by the version in adapters.json and exercised by
# `pytest -m integration`; check them first when upgrading the tool.


def indexed_view_names(parser: BulkLkmlParser) -> list[str]:
    """Names of every view the parser indexed. ``BulkLkmlParser`` has no public way to list them."""
    return sorted(parser._views_cache)


def substitute_constants(
    text: str | None, constants: dict[str, str], *, strip_unresolved: bool
) -> str | None:
    """``LookerSource._resolve_lookml_constants``, which reads nothing from the source but the map."""
    if text is None:
        return None
    source = SimpleNamespace(_lookml_constants_map=constants)
    return LookerSource._resolve_lookml_constants(source, text, strip_unresolved=strip_unresolved)


if __name__ == "__main__":
    raise SystemExit(OpenMetadataAdapter.main())
