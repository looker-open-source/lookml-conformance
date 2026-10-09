"""Adapter for DataHub's LookML source (``acryl-datahub[lookml]``).

    python -m lookml_conformance.adapters.datahub <project> [--no-process-refinements]

The adapter drives the classes ``LookMLSource`` uses to build view and explore entities: it loads
each model file, walks the model's resolved includes, applies refinements with
``LookerRefinementResolver`` and reads each view through ``LookerViewContext``. DataHub's
``process_refinements`` option defaults to false; the adapter turns it on so that the refinement
resolver is exercised. Directories under ``imported_projects/`` become ``project_dependencies``.
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from typing import Any

import lkml
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.source.looker.looker_common import LookerExplore
from datahub.ingestion.source.looker.looker_config import LookerConnectionDefinition
from datahub.ingestion.source.looker.looker_connection import get_connection_def_based_on_connection_string
from datahub.ingestion.source.looker.looker_file_loader import LookerViewFileLoader
from datahub.ingestion.source.looker.lookml_concept_context import LookerViewContext
from datahub.ingestion.source.looker.lookml_config import BASE_PROJECT_NAME, LookMLSourceConfig
from datahub.ingestion.source.looker.lookml_refinement import LookerRefinementResolver
from datahub.ingestion.source.looker.lookml_source import LookMLSource

from lookml_conformance.adapters import kit
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import AdapterOutput, ExploreOutput, ModelOutput, ViewOutput

NAME = "datahub"
DISTRIBUTION = "acryl-datahub"
# The suite checks LookML resolution only, so every connection maps to one placeholder warehouse.
PLACEHOLDER_CONNECTION = LookerConnectionDefinition(
    platform="snowflake", default_db="default_db", default_schema="default_schema"
)


def summarize_view(view: LookerViewContext) -> ViewOutput:
    sql_table_name = view._get_sql_table_name_field()
    if sql_table_name is not None:
        # DataHub emits lineage for the table name after its own constant substitution.
        sql_table_name = (
            view.get_including_extends(field="datahub_transformed_sql_table_name") or sql_table_name
        )
    raw_derived_table = view.get_including_extends(field="derived_table")
    derived_table_sql = None
    if isinstance(raw_derived_table, dict):
        derived_table_sql = raw_derived_table.get("datahub_transformed_sql", raw_derived_table.get("sql"))
        raw_derived_table = {k: v for k, v in raw_derived_table.items() if k != "datahub_transformed_sql"}
    raw = {**view.raw_view, "derived_table": raw_derived_table}
    return kit.view_output(
        raw,
        sql_table_name=sql_table_name,
        derived_table_sql=derived_table_sql,
        fields=[*view.dimensions(), *view.dimension_groups(), *view.measures()],
    )


def summarize_explore(explore: LookerExplore, raw: dict[str, Any]) -> ExploreOutput:
    raw_joins = {
        join["name"]: join for join in raw.get("joins") or [] if isinstance(join, dict) and "name" in join
    }
    joins = {
        join.name: {
            "from": collapse_whitespace(join.from_view),
            "view_label": collapse_whitespace(
                getattr(join, "view_label", None) or raw_joins.get(join.name, {}).get("view_label")
            ),
            "sql_on": collapse_whitespace(join.sql_on),
            "relationship": collapse_whitespace(join.relationship),
            "type": collapse_whitespace(join.join_type),
        }
        for join in explore.join_definitions or []
    }
    from_view = getattr(explore, "from_view", None) or raw.get("from")
    return ExploreOutput(
        view_name=collapse_whitespace(
            getattr(explore, "view_name", None) or raw.get("view_name") or from_view or explore.name
        ),
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
        self.root = root
        self.source = LookMLSource(config=config, ctx=PipelineContext(run_id="lookml-conformance"))
        self.source.base_projects_folder[BASE_PROJECT_NAME] = root
        self.source.base_projects_folder.update(dependencies)
        # Loads manifest constants the way LookMLSource does before reading views.
        self.source._recursively_check_manifests(
            str(root), BASE_PROJECT_NAME, set(), self.source.manifest_constants
        )
        self.loader = LookerViewFileLoader(
            self.source.source_config.project_name,
            self.source.base_projects_folder,
            self.source.reporter,
            self.source.source_config,
            self.source.manifest_constants,
        )
        # Arguments that only some DataHub versions accept, so a branch under test can add them.
        self._view_context_takes_model = (
            "looker_model" in inspect.signature(LookerViewContext.__init__).parameters
        )
        self._refines_explores = hasattr(LookerRefinementResolver, "apply_explore_refinement")

    def resolve_model(self, model_file: Path, errors: list[str]) -> ModelOutput:
        source = self.source
        name = kit.model_name(model_file)
        model = source._load_model(str(model_file))
        connection = (
            get_connection_def_based_on_connection_string(
                connection=model.connection,
                looker_client=source.looker_client,
                source_config=source.source_config,
                reporter=source.reporter,
            )
            or PLACEHOLDER_CONNECTION
        )
        resolver = LookerRefinementResolver(
            looker_model=model,
            looker_viewfile_loader=self.loader,
            connection_definition=connection,
            source_config=source.source_config,
            reporter=source.reporter,
        )
        views = self._resolve_views(model, connection, resolver)
        explores = self._resolve_explores(name, model, resolver, errors)
        return ModelOutput(views=views, explores=explores)

    def _resolve_views(
        self, model: Any, connection: Any, resolver: LookerRefinementResolver
    ) -> dict[str, ViewOutput]:
        source = self.source
        views: dict[str, ViewOutput] = {}
        for include in model.resolved_includes:
            view_file = self.loader.load_viewfile(
                path=include.include,
                project_name=include.project,
                connection=connection,
                reporter=source.reporter,
            )
            if view_file is None:
                continue
            project = (
                include.project if include.project != BASE_PROJECT_NAME else source.source_config.project_name
            )
            context_args: dict[str, Any] = {
                "view_file": view_file,
                "view_connection": connection,
                "view_file_loader": self.loader,
                "looker_refinement_resolver": resolver,
                "base_folder_path": str(
                    source.base_projects_folder.get(project, source.base_projects_folder[BASE_PROJECT_NAME])
                ),
                "reporter": source.reporter,
            }
            if self._view_context_takes_model:
                context_args["looker_model"] = model
            for raw_view in view_file.views:
                view_name = raw_view["name"]
                if LookerRefinementResolver.is_refinement(view_name):
                    continue  # LookMLSource does not emit refinements as views
                try:
                    refined = resolver.apply_view_refinement(raw_view=raw_view)
                    views[view_name] = summarize_view(LookerViewContext(raw_view=refined, **context_args))
                except Exception as exc:  # reported for this view only
                    views[view_name] = ViewOutput(error=repr(exc))
        return views

    def _resolve_explores(
        self, model_name: str, model: Any, resolver: LookerRefinementResolver, errors: list[str]
    ) -> dict[str, ExploreOutput]:
        base_explores = {
            e["name"]: e for e in model.explores if not LookerRefinementResolver.is_refinement(e["name"])
        }
        explores = {}
        for name, raw in base_explores.items():
            if raw.get("extension") == "required":
                continue
            try:
                refined = resolver.apply_explore_refinement(raw) if self._refines_explores else raw
                explore = LookerExplore.from_dict(
                    model_name,
                    refined,
                    model.resolved_includes,
                    self.loader,
                    self.source.reporter,
                    base_explores,
                )
                explores[name] = summarize_explore(explore, refined)
            except Exception as exc:  # reported, the other explores still resolve
                errors.append(f"{model_name}.explore.{name}: {exc!r}")
        return explores


def resolve(root: Path, args: argparse.Namespace) -> AdapterOutput:
    project = Project(root, args.process_refinements)
    models: dict[str, ModelOutput] = {}
    errors: list[str] = []
    for model_file in kit.model_files(root):
        try:
            models[kit.model_name(model_file)] = project.resolve_model(model_file, errors)
        except Exception as exc:  # reported, the other models still resolve
            errors.append(f"{kit.model_name(model_file)}: {exc!r}")
    return AdapterOutput(adapter=NAME, models=models, errors=tuple(errors))


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--process-refinements",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="set LookMLSourceConfig.process_refinements (default: on)",
    )


def main() -> int:
    return kit.run_adapter(NAME, DISTRIBUTION, resolve, configure=configure)


if __name__ == "__main__":
    raise SystemExit(main())
