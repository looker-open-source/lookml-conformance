"""Adapter for DataHub's LookML source (``acryl-datahub[lookml]``).

    python -m lookml_conformance.adapters.datahub <project>... [--no-process-refinements]

The adapter drives the classes ``LookMLSource`` uses to build view and explore entities: it loads
each model file, walks the model's resolved includes, applies refinements with
``LookerRefinementResolver`` and reads each view through ``LookerViewContext``. DataHub's
``process_refinements`` option defaults to false; the adapter turns it on so that the refinement
resolver is exercised. Directories under ``imported_projects/`` become ``project_dependencies``.

A view's upstream is what ``create_view_upstream`` returns for it, the lineage ``LookMLSource``
emits: warehouse tables, other Looker views (for ``${view.SQL_TABLE_NAME}``) and explores (for
native derived tables).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import lkml
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.source.looker.looker_common import LookerExplore
from datahub.ingestion.source.looker.looker_config import LookerConnectionDefinition
from datahub.ingestion.source.looker.looker_connection import get_connection_def_based_on_connection_string
from datahub.ingestion.source.looker.looker_dataclasses import LookerModel
from datahub.ingestion.source.looker.looker_file_loader import LookerViewFileLoader
from datahub.ingestion.source.looker.looker_view_id_cache import LookerViewIdCache
from datahub.ingestion.source.looker.lookml_concept_context import LookerViewContext
from datahub.ingestion.source.looker.lookml_config import BASE_PROJECT_NAME, LookMLSourceConfig
from datahub.ingestion.source.looker.lookml_refinement import LookerRefinementResolver
from datahub.ingestion.source.looker.lookml_source import LookMLSource
from datahub.ingestion.source.looker.view_upstream import create_view_upstream
from datahub.utilities.urns.dataset_urn import DatasetUrn

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import ExploreOutput, ModelOutput, Upstream, ViewOutput

# The suite checks LookML resolution only, so every connection maps to one placeholder warehouse.
PLACEHOLDER_CONNECTION = LookerConnectionDefinition(
    platform="snowflake", default_db="default_db", default_schema="default_schema"
)


class DataHubAdapter(Adapter):
    name = "datahub"
    distribution = "acryl-datahub"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--process-refinements",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="set LookMLSourceConfig.process_refinements (default: on)",
        )

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        loaded = Project(project, getattr(self.options, "process_refinements", True))
        models = {}
        for model_file in kit.model_files(project):
            name = kit.model_name(model_file)
            try:
                models[name] = loaded.resolve_model(model_file, self.warn)
            except Exception as exc:  # reported, the other models still resolve
                self.warn(f"{name}: {exc!r}")
        return models


class Project:
    """A LookML project loaded with DataHub's LookML source classes."""

    def __init__(self, root: Path, process_refinements: bool) -> None:
        dependencies = kit.imported_projects(root)
        config = LookMLSourceConfig(
            base_folder=root,
            project_name="conformance_project",
            connection_to_platform_map=dict.fromkeys(connection_names(root), PLACEHOLDER_CONNECTION),
            process_refinements=process_refinements,
            emit_reachable_views_only=False,
            project_dependencies=dependencies,
        )
        self.source = LookMLSource(config=config, ctx=PipelineContext(run_id="lookml-conformance"))
        self.source.base_projects_folder[BASE_PROJECT_NAME] = root
        self.source.base_projects_folder.update(dependencies)
        load_manifest_constants(self.source, root)
        self.loader = LookerViewFileLoader(
            self.source.source_config.project_name,
            self.source.base_projects_folder,
            self.source.reporter,
            self.source.source_config,
            self.source.manifest_constants,
        )

    def resolve_model(self, model_file: Path, warn: Any) -> ModelOutput:
        model = load_model(self.source, model_file)
        connection = (
            get_connection_def_based_on_connection_string(
                connection=model.connection,
                looker_client=self.source.looker_client,
                source_config=self.source.source_config,
                reporter=self.source.reporter,
            )
            or PLACEHOLDER_CONNECTION
        )
        resolver = LookerRefinementResolver(
            looker_model=model,
            looker_viewfile_loader=self.loader,
            connection_definition=connection,
            source_config=self.source.source_config,
            reporter=self.source.reporter,
        )
        view_ids = LookerViewIdCache(
            project_name=self.source.source_config.project_name,
            model_name=kit.model_name(model_file),
            looker_model=model,
            looker_viewfile_loader=self.loader,
            reporter=self.source.reporter,
        )
        return ModelOutput(
            views=self._views(model, connection, resolver, view_ids, warn),
            explores=self._explores(kit.model_name(model_file), model, resolver, warn),
        )

    def _views(
        self,
        model: LookerModel,
        connection: Any,
        resolver: LookerRefinementResolver,
        view_ids: LookerViewIdCache,
        warn: Any,
    ) -> dict[str, ViewOutput]:
        folders = self.source.base_projects_folder
        views: dict[str, ViewOutput] = {}
        for include in model.resolved_includes:
            view_file = self.loader.load_viewfile(
                path=include.include,
                project_name=include.project,
                connection=connection,
                reporter=self.source.reporter,
            )
            if view_file is None:
                continue
            project = (
                include.project
                if include.project != BASE_PROJECT_NAME
                else self.source.source_config.project_name
            )
            context = {
                "view_file": view_file,
                "view_connection": connection,
                "view_file_loader": self.loader,
                "looker_refinement_resolver": resolver,
                "base_folder_path": str(folders.get(project, folders[BASE_PROJECT_NAME])),
                "reporter": self.source.reporter,
            }
            for raw_view in view_file.views:
                name = raw_view["name"]
                if LookerRefinementResolver.is_refinement(name):
                    continue  # LookMLSource does not emit refinements as views
                try:
                    refined = resolver.apply_view_refinement(raw_view=raw_view)
                    view = LookerViewContext(raw_view=refined, **context)
                    views[name] = summarize_view(view, self._upstream(view, view_ids, warn))
                except Exception as exc:  # reported for this view only
                    views[name] = ViewOutput(error=repr(exc))
        return views

    def _upstream(
        self, view: LookerViewContext, view_ids: LookerViewIdCache, warn: Any
    ) -> tuple[Upstream, ...] | None:
        try:
            lineage = create_view_upstream(
                view_context=view,
                looker_view_id_cache=view_ids,
                config=self.source.source_config,
                ctx=self.source.ctx,
                reporter=self.source.reporter,
            )
            return tuple(upstream_from_urn(urn) for urn in lineage.get_upstream_dataset_urn())
        except Exception as exc:  # reported as no lineage for this view; the view still resolves
            warn(f"{view.name()} lineage: {exc!r}")
            return None

    def _explores(
        self, model_name: str, model: LookerModel, resolver: LookerRefinementResolver, warn: Any
    ) -> dict[str, ExploreOutput]:
        base = {e["name"]: e for e in model.explores if not LookerRefinementResolver.is_refinement(e["name"])}
        explores = {}
        for name, raw in base.items():
            if raw.get("extension") == "required":
                continue
            try:
                refined = resolver.apply_explore_refinement(raw)
                explore = LookerExplore.from_dict(
                    model_name, refined, model.resolved_includes, self.loader, self.source.reporter, base
                )
                explores[name] = summarize_explore(explore, refined)
            except Exception as exc:  # reported, the other explores still resolve
                warn(f"{model_name}.explore.{name}: {exc!r}")
        return explores


def summarize_view(view: LookerViewContext, upstream: tuple[Upstream, ...] | None = None) -> ViewOutput:
    sql_table_name = view.get_including_extends(field="sql_table_name")
    if sql_table_name is not None:
        # DataHub emits lineage for the table name after its own constant substitution.
        sql_table_name = (
            view.get_including_extends(field="datahub_transformed_sql_table_name") or sql_table_name
        )
    derived_table = view.get_including_extends(field="derived_table")
    derived_table_sql = None
    if isinstance(derived_table, dict):
        derived_table_sql = derived_table.get("datahub_transformed_sql", derived_table.get("sql"))
        derived_table = {k: v for k, v in derived_table.items() if k != "datahub_transformed_sql"}
    return kit.view_output(
        {**view.raw_view, "derived_table": derived_table},
        sql_table_name=sql_table_name,
        derived_table_sql=derived_table_sql,
        fields=[*view.dimensions(), *view.dimension_groups(), *view.measures()],
        upstream=upstream,
    )


def upstream_from_urn(urn: str) -> Upstream:
    """A lineage edge from a dataset urn: a Looker view or explore, or a warehouse table."""
    dataset = DatasetUrn.from_string(urn)
    name = dataset.name
    if dataset.platform.endswith(":looker"):
        for kind in ("view", "explore"):
            # Looker urns are named <project>.view.<name> and <model>.explore.<name>.
            prefix, separator, short_name = name.partition(f".{kind}.")
            if separator and prefix:
                return Upstream(kind, short_name)
    # Drop the placeholder database and schema of PLACEHOLDER_CONNECTION, which the adapter set.
    for placeholder in (f"{PLACEHOLDER_CONNECTION.default_db}.", f"{PLACEHOLDER_CONNECTION.default_schema}."):
        name = name.removeprefix(placeholder)
    return Upstream("table", name)


def summarize_explore(explore: LookerExplore, raw: dict[str, Any]) -> ExploreOutput:
    raw_joins = {
        join["name"]: join for join in raw.get("joins") or [] if isinstance(join, dict) and "name" in join
    }
    joins = {
        join.name: {
            "from": collapse_whitespace(join.from_view),
            "view_label": collapse_whitespace(raw_joins.get(join.name, {}).get("view_label")),
            "sql_on": collapse_whitespace(join.sql_on),
            "relationship": collapse_whitespace(join.relationship),
            "type": collapse_whitespace(join.join_type),
        }
        for join in explore.join_definitions or []
    }
    from_view = raw.get("from")
    return ExploreOutput(
        view_name=collapse_whitespace(raw.get("view_name") or from_view or explore.name),
        from_view=collapse_whitespace(from_view),
        label=collapse_whitespace(explore.label),
        joins=joins,
    )


def connection_names(root: Path) -> set[str]:
    names = {"wh"}
    for path in kit.model_files(root):
        try:
            names.add(lkml.load(path.read_text(encoding="utf-8"))["connection"])
        except Exception:  # models without a parsable connection use the placeholder
            continue
    return names


# Private DataHub APIs. LookMLSource has no public way to load one model or its manifest
# constants without running the whole ingestion. Both are pinned by the version in adapters.json
# and exercised by `pytest -m integration`; check them first when upgrading the tool.


def load_model(source: LookMLSource, model_file: Path) -> LookerModel:
    return source._load_model(str(model_file))


def load_manifest_constants(source: LookMLSource, root: Path) -> None:
    source._recursively_check_manifests(str(root), BASE_PROJECT_NAME, set(), source.manifest_constants)


if __name__ == "__main__":
    raise SystemExit(DataHubAdapter.main())
