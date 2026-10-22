"""Adapter for DataHub's LookML source (``acryl-datahub[lookml]``).

    python -m lookml_conformance.adapters.datahub <project>... [--no-process-refinements]

The adapter runs ``LookMLSource`` the way ``datahub ingest`` does: it iterates the source's work
units over the whole project, offline, and records each view entity the source emits. The source
reads the model files in path order (``sorted(base_folder.glob("**/*.model.lkml"))``) and emits
one entity per view and project (the default ``view_naming_pattern`` is
``{project}.view.{name}``). When several models include a view, the first model in path order
that resolves it decides what the entity holds; the source skips the view in later models. The
adapter reports that one entity under every model that includes the view, so a view that two
models refine differently resolves the same in both.

Configuration: every connection maps to one placeholder warehouse, directories under
``imported_projects/`` become ``project_dependencies``, and two options differ from the source's
defaults. ``process_refinements`` defaults to false; the adapter turns it on so that the
refinement resolver is exercised (``--no-process-refinements`` turns it off).
``emit_reachable_views_only`` defaults to true, which drops views no explore reaches; the adapter
turns it off so that every view a model includes is emitted, which several lineage cases need.

What the adapter reports for a view comes from the entity the source emits and from the view
context the source built it from:

- fields: the names of the entity's schema fields; ``sql``, ``label`` and ``type`` from the field
  definitions the source read them from;
- ``sql_table_name``, ``derived_table`` and ``extends``: the resolved view the source built the
  entity from, with the table name after the source's constant substitution;
- upstream: the entity's upstream lineage: warehouse tables, other Looker views (for
  ``${view.SQL_TABLE_NAME}``) and explores (for native derived tables).

LookMLSource emits no explore entities. The adapter reports the explores the source resolves per
model while it runs, so that the judge can follow lineage through them.
"""

from __future__ import annotations

import argparse
import contextlib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lkml
from datahub.ingestion.api.common import PipelineContext
from datahub.ingestion.source.looker.looker_common import LookerExplore
from datahub.ingestion.source.looker.looker_config import LookerConnectionDefinition
from datahub.ingestion.source.looker.looker_dataclasses import LookerModel
from datahub.ingestion.source.looker.looker_file_loader import LookerViewFileLoader
from datahub.ingestion.source.looker.lookml_concept_context import LookerViewContext
from datahub.ingestion.source.looker.lookml_config import (
    BASE_PROJECT_NAME,
    LookMLSourceConfig,
    LookMLSourceReport,
)
from datahub.ingestion.source.looker.lookml_refinement import LookerRefinementResolver
from datahub.ingestion.source.looker.lookml_source import LookerView, LookMLSource
from datahub.utilities.urns.dataset_urn import DatasetUrn

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import Capabilities, ExploreOutput, ModelOutput, Upstream, ViewOutput

# The suite checks LookML resolution only, so every connection maps to one placeholder warehouse.
PLACEHOLDER_CONNECTION = LookerConnectionDefinition(
    platform="snowflake", default_db="default_db", default_schema="default_schema"
)
PROJECT_NAME = "conformance_project"

# A view entity is keyed by its project and view name, the variables of the default
# view_naming_pattern ("{project}.view.{name}"), which the adapter keeps.
ViewKey = tuple[str, str]


class DataHubAdapter(Adapter):
    name = "datahub"
    distribution = "acryl-datahub"
    # LookMLSource emits views only: it resolves explores to find reachable views and to draw the
    # lineage of native derived tables, but explore entities come from DataHub's Looker API source.
    # A view's schema fields (ViewField) carry no filters or timeframes, and the only derived table
    # parameters it reads besides sql decide the materialized flag of native derived tables.
    # The adapter still reports explores, so that lineage through them can be followed.
    capabilities = Capabilities(
        explores=False, field_filters=False, field_timeframes=False, derived_table_params=False
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--process-refinements",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="set LookMLSourceConfig.process_refinements (default: on; the source's default is off)",
        )

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        run = ingest(project, getattr(self.options, "process_refinements", True))
        for diagnostic in run.diagnostics:
            self.warn(diagnostic)
        return {name: run.model_output(name) for name in run.models}


def source_config(root: Path, process_refinements: bool) -> LookMLSourceConfig:
    return LookMLSourceConfig(
        base_folder=root,
        project_name=PROJECT_NAME,
        connection_to_platform_map=dict.fromkeys(connection_names(root), PLACEHOLDER_CONNECTION),
        process_refinements=process_refinements,
        emit_reachable_views_only=False,
        project_dependencies=kit.imported_projects(root),
    )


def ingest(root: Path, process_refinements: bool) -> Ingestion:
    """Run LookMLSource over the project as ``datahub ingest`` does and record what it emits."""
    source = RecordingLookMLSource(
        config=source_config(root, process_refinements), ctx=PipelineContext(run_id="lookml-conformance")
    )
    with recording(source.ingestion):
        for _ in source.get_workunits():
            pass
    source.ingestion.diagnostics.extend(
        f"{warning.title}: {warning.message} {list(warning.context)[:1]}"
        for warning in [*source.reporter.failures, *source.reporter.warnings]
        if warning.title in {"Error Loading View", "Error Loading Model File", "Failed to process explores"}
    )
    source.ingestion.members = {
        name: included_views(source, model) for name, model in source.ingestion.models.items()
    }
    return source.ingestion


@dataclass
class EmittedView:
    """A view entity the source emitted, with the view context it built the entity from."""

    entity: LookerView
    context: LookerViewContext


@dataclass
class Ingestion:
    """What one run of LookMLSource loaded, resolved and emitted."""

    # Models in the order the source processed them.
    models: dict[str, LookerModel] = field(default_factory=dict)
    # The views each model includes, by entity key, in include order.
    members: dict[str, list[ViewKey]] = field(default_factory=dict)
    # Every view the source built, with its context, by the id of the LookerView.
    built: dict[int, EmittedView] = field(default_factory=dict)
    emitted: dict[ViewKey, EmittedView] = field(default_factory=dict)
    view_errors: dict[ViewKey, str] = field(default_factory=dict)
    explores: dict[str, dict[str, ExploreOutput]] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)

    def model_output(self, model: str) -> ModelOutput:
        views: dict[str, ViewOutput] = {}
        for key in self.members.get(model, []):
            _, name = key
            if name in views:
                continue  # a second definition in the same project is the same entity
            if (emitted := self.emitted.get(key)) is not None:
                views[name] = summarize_view(emitted)
            elif (error := self.view_errors.get(key)) is not None:
                views[name] = ViewOutput(error=error)
        return ModelOutput(views=views, explores=self.explores.get(model, {}))


def summarize_view(emitted: EmittedView) -> ViewOutput:
    view, entity = emitted.context, emitted.entity
    sql_table_name = view.get_including_extends(field="sql_table_name")
    if sql_table_name is not None:
        # DataHub draws lineage from the table name after its own constant substitution.
        sql_table_name = (
            view.get_including_extends(field="datahub_transformed_sql_table_name") or sql_table_name
        )
    derived_table = view.get_including_extends(field="derived_table")
    derived_table_sql = None
    if isinstance(derived_table, dict):
        derived_table_sql = derived_table.get("datahub_transformed_sql", derived_table.get("sql"))
        derived_table = {k: v for k, v in derived_table.items() if k != "datahub_transformed_sql"}
    definitions = {
        str(raw["name"]): raw
        for raw in [*view.dimensions(), *view.dimension_groups(), *view.measures()]
        if isinstance(raw, Mapping) and "name" in raw
    }
    fields = [definitions.get(field.name, {"name": field.name}) for field in entity.fields]
    return kit.view_output(
        {**view.raw_view, "derived_table": derived_table},
        sql_table_name=sql_table_name,
        derived_table_sql=derived_table_sql,
        fields=fields,
        upstream=[upstream_from_urn(urn) for urn in entity.upstream_dataset_urns],
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


def summarize_explore(explore: LookerExplore, raw: Mapping[str, Any]) -> ExploreOutput:
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
    for path in root.glob("**/*.model.lkml"):
        try:
            names.add(lkml.load(path.read_text(encoding="utf-8"))["connection"])
        except Exception:  # models without a parsable connection use the placeholder
            continue
    return names


def view_key(project: str, name: str) -> ViewKey:
    return (PROJECT_NAME if project == BASE_PROJECT_NAME else project, name)


def included_views(source: LookMLSource, model: LookerModel) -> list[ViewKey]:
    """The views a model includes, as the source loads them from the model's resolved includes."""
    loader = LookerViewFileLoader(
        source.source_config.project_name,
        source.base_projects_folder,
        LookMLSourceReport(),
        source.source_config,
        source.manifest_constants,
    )
    keys: list[ViewKey] = []
    for include in model.resolved_includes:
        view_file = loader.load_viewfile(include.include, include.project, None, LookMLSourceReport())
        for raw_view in view_file.views if view_file is not None else []:
            name = raw_view.get("name")
            if name and not LookerRefinementResolver.is_refinement(name):
                keys.append(view_key(include.project, name))
    return keys


# Private DataHub APIs. LookMLSource has no public hook to observe which model loads which view, or
# the view context an entity was built from, so the adapter overrides two of its methods and wraps
# the two class methods the source calls to resolve views and explores. They are pinned by the
# version in adapters.json and exercised by `pytest -m integration`; check them first when
# upgrading the tool.


class RecordingLookMLSource(LookMLSource):
    """LookMLSource that records the models it loads and the view entities it emits."""

    def __init__(self, config: LookMLSourceConfig, ctx: PipelineContext) -> None:
        super().__init__(config, ctx)
        self.ingestion = Ingestion()

    def _load_model(self, path: str) -> LookerModel:
        model = super()._load_model(path)
        self.ingestion.models[kit.model_name(Path(path))] = model
        return model

    def _build_dataset_entities(self, looker_view: LookerView) -> Iterator[Any]:
        key = (looker_view.id.project_name, looker_view.id.view_name)
        built = self.ingestion.built.get(id(looker_view))
        if built is not None and built.entity is looker_view:
            self.ingestion.emitted.setdefault(key, built)
        yield from super()._build_dataset_entities(looker_view)


@contextlib.contextmanager
def recording(ingestion: Ingestion) -> Iterator[None]:
    """Wrap the class methods LookMLSource resolves views and explores with, for one run."""
    view_from_dict = LookerView.from_looker_dict
    explore_from_dict = LookerExplore.from_dict

    def record_view(*args: Any, **kwargs: Any) -> LookerView | None:
        context = kwargs["view_context"]
        try:
            view = view_from_dict(*args, **kwargs)
        except Exception as exc:  # the source reports it and does not emit the view
            ingestion.view_errors.setdefault(view_key(kwargs["project_name"], context.name()), repr(exc))
            raise
        if view is not None:
            ingestion.built[id(view)] = EmittedView(view, context)
        return view

    def record_explore(model_name: str, raw: dict[str, Any], *args: Any, **kwargs: Any) -> LookerExplore:
        explore = explore_from_dict(model_name, raw, *args, **kwargs)
        ingestion.explores.setdefault(model_name, {})[raw["name"]] = summarize_explore(explore, raw)
        return explore

    patches: list[tuple[type, str, Callable[..., Any]]] = [
        (LookerView, "from_looker_dict", record_view),
        (LookerExplore, "from_dict", record_explore),
    ]
    originals = [(owner, name, owner.__dict__[name]) for owner, name, _ in patches]
    try:
        for owner, name, wrapper in patches:
            setattr(owner, name, staticmethod(wrapper))
        yield
    finally:
        for owner, name, original in originals:
            setattr(owner, name, original)


if __name__ == "__main__":
    raise SystemExit(DataHubAdapter.main())
