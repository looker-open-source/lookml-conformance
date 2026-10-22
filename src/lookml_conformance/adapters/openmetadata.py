"""Adapter for OpenMetadata's Looker connector (``openmetadata-ingestion[looker]``).

    python -m lookml_conformance.adapters.openmetadata <project>...

The connector reads views from the repository with ``BulkLkmlParser`` and takes explores from the
Looker API, so the adapter reports views only. ``BulkLkmlParser`` has no model scope, so the views
are reported as one project-wide model. ``@{constant}`` references are substituted with the
function the connector applies to ``sql_table_name`` and derived table SQL.

How the connector runs: it clones the LookML repository and builds one ``BulkLkmlParser`` over it
with a ``LocalReader``, which lists every ``*.view.lkml`` file with ``os.walk``. The parser keeps
one view per name: when two files define a view of the same name, the file listed last wins. The
adapter builds the parser the same way, with the connector's own ``LocalReader``, so files are read
in the order the file system lists them. That order depends on the file system: APFS (macOS)
lists a directory in an order fixed by the file names, and ext4 (Linux) in an order that also
depends on a hash seed chosen when the file system was created. Versions of the parser that sort
the paths themselves read them in path order.

A view's upstream is the lineage the connector draws for it. Without a Looker instance there are
no explores from the API, so every view is a standalone view: the adapter runs the connector's
``_add_standalone_view_lineage`` on each view of the parser's cache, in the cache's order, which is
how ``yield_standalone_datamodels`` and ``_yield_bulk_datamodel_lineage`` process them. The calls
to the OpenMetadata server are replaced by recorders: a table lineage request becomes a table
upstream, and a view-to-view request (for ``extends``) a view upstream. The order matters for
``${view.SQL_TABLE_NAME}`` references, which the connector resolves only when the referenced view
was drawn first. In a run against a Looker instance, the views of the explores the API returns are
drawn first, through ``add_view_lineage``, which draws the same table and ``extends`` edges.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import lkml
import networkx as nx
from metadata.ingestion.lineage.models import Dialect
from metadata.ingestion.source.dashboard.looker.bulk_parser import BulkLkmlParser
from metadata.ingestion.source.dashboard.looker.metadata import LookerSource
from metadata.ingestion.source.dashboard.looker.models import (
    LookMlDerivedTableField,
    LookMlField,
    LookMLManifest,
)
from metadata.readers.file.local import LocalReader
from metadata.utils.singleton import Singleton

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.protocol import Capabilities, ModelOutput, Upstream, ViewOutput

PROJECT_WIDE = "*"


class OpenMetadataAdapter(Adapter):
    name = "openmetadata"
    distribution = "openmetadata-ingestion"
    # What the connector can report is what its view model (LookMlField, LookMlDerivedTableField)
    # keeps. Released versions keep no field filters; later ones keep measure filters as
    # ``filters__all``. No version keeps timeframes or derived table parameters other than SQL.
    capabilities = Capabilities(
        per_model=False,
        explores=False,
        field_filters="filters__all" in LookMlField.model_fields,
        field_timeframes="timeframes" in LookMlField.model_fields,
        derived_table_params=bool(set(LookMlDerivedTableField.model_fields) - {"sql", "sql_create"}),
    )

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        Singleton.clear_all()  # BulkLkmlParser is a process-wide singleton
        parser = BulkLkmlParser(reader=LocalReader(base_path=project))
        constants = manifest_constants(project)
        # Every view the connector would ingest, including refinements it indexes as "+name" views.
        names = indexed_view_names(parser)
        models = [kit.model_name(path) for path in kit.model_files(project)]
        lineage = OfflineLineage(constants, names)
        for diagnostic in lineage.run(indexed_views(parser), models[0] if models else "default"):
            self.warn(diagnostic)
        views = {name: self._view(parser, name, constants, lineage.upstream.get(name)) for name in names}
        return {
            PROJECT_WIDE: ModelOutput(
                views={name: view for name, view in views.items() if view is not None}, all_views=tuple(names)
            )
        }

    def _view(
        self,
        parser: BulkLkmlParser,
        name: str,
        constants: dict[str, str],
        upstream: tuple[Upstream, ...] | None,
    ) -> ViewOutput | None:
        try:
            view = parser.find_view(name)
            return None if view is None else summarize_view(view, constants, upstream)
        except Exception as exc:  # reported for this view only
            return ViewOutput(error=repr(exc))


def summarize_view(
    view: Any, constants: dict[str, str], upstream: tuple[Upstream, ...] | None = None
) -> ViewOutput:
    # Released versions model dimensions and measures but not dimension groups.
    fields = [*view.dimensions, *(getattr(view, "dimension_groups", None) or []), *view.measures]
    raw = view.model_dump(by_alias=True, exclude_none=True)
    derived = raw.get("derived_table") or {}
    return kit.view_output(
        raw,
        sql_table_name=substitute_constants(view.sql_table_name, constants, strip_unresolved=True),
        derived_table_sql=substitute_constants(derived.get("sql"), constants, strip_unresolved=False),
        fields=[field.model_dump(exclude_none=True) for field in fields],
        upstream=upstream,
    )


def manifest_constants(project: Path) -> dict[str, str]:
    """Manifest constants, read the way the connector reads them (``LookMLManifest``)."""
    manifest = project / "manifest.lkml"
    if not manifest.is_file():
        return {}
    parsed = LookMLManifest.model_validate(lkml.load(manifest.read_text(encoding="utf-8")))
    return {constant["name"]: constant.get("value", "") for constant in parsed.constants or []}


# Private OpenMetadata APIs. They are pinned by the version in adapters.json and exercised by
# `pytest -m integration`; check them first when upgrading the tool.


def indexed_view_names(parser: BulkLkmlParser) -> list[str]:
    """Names of every view the parser indexed. ``BulkLkmlParser`` has no public way to list them."""
    return sorted(parser._views_cache)


def indexed_views(parser: BulkLkmlParser) -> list[tuple[str, Any]]:
    """The indexed views in the order ``yield_standalone_datamodels`` iterates them."""
    return list(parser._views_cache.items())


class OfflineLineage(LookerSource):
    """``LookerSource`` view lineage without an OpenMetadata server.

    Only the attributes the lineage methods read are set, and the methods that call the server are
    replaced: lineage requests are recorded as upstreams instead of being sent.
    """

    def __init__(self, constants: dict[str, str], view_names: Iterable[str]) -> None:
        # LookerSource.__init__ connects to Looker and OpenMetadata, so it is not called.
        self._lookml_constants_map = constants
        self._parsed_views: dict[str, str] = {}
        self._unparsed_views: dict[str, str] = {}
        self._derived_dependencies = nx.DiGraph()
        self._views_cache = {name: SimpleNamespace(name=name) for name in view_names}
        self._view_data_model = None
        self.source_config = SimpleNamespace(queryParserConfig=None)
        self.upstream: dict[str, tuple[Upstream, ...]] = {}

    def run(self, views: Iterable[tuple[str, Any]], model_name: str) -> list[str]:
        """Draw lineage for each view in order; returns the errors the connector reported."""
        errors = []
        for name, view in views:
            self._view_data_model = SimpleNamespace(name=name)
            self.upstream[name] = ()
            for result in self._add_standalone_view_lineage(view, "conformance_project", model_name):
                if getattr(result, "left", None) is not None:
                    errors.append(f"{name}: {result.left.error}")
        return errors

    def get_db_service_prefixes(self) -> list[str]:
        return ["warehouse"]

    def _get_db_dialect(self, db_service_name: Any) -> Dialect:
        return Dialect.ANSI

    def _build_data_model(self, datamodel_name: str) -> None:
        return None

    def build_lineage_request(self, source: str, db_service_prefix: Any, to_entity: Any, **_: Any) -> None:
        self._record(to_entity.name, Upstream("table", str(source)))

    def _get_add_lineage_request(self, from_entity: Any, to_entity: Any, column_lineage: Any) -> None:
        self._record(to_entity.name, Upstream("view", from_entity.name))

    def _record(self, view_name: str, edge: Upstream) -> None:
        if edge not in self.upstream.get(view_name, ()):
            self.upstream[view_name] = (*self.upstream.get(view_name, ()), edge)


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
