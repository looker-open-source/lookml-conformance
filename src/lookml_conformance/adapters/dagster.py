"""Adapter for Dagster's Looker integration (``dagster-looker``).

    python -m lookml_conformance.adapters.dagster <project>...

``build_looker_view_specs`` and ``build_looker_explore_specs`` hand every resolved view and explore
to a ``DagsterLookerLkmlTranslator``; the adapter passes one that records them. dagster-looker
resolves the project as a whole, so the result is reported as one project-wide model.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import AssetSpec
from dagster_looker.lkml import asset_utils
from dagster_looker.lkml.dagster_looker_lkml_translator import (
    DagsterLookerLkmlTranslator,
    LookMLStructureType,
)

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import Capabilities, ExploreOutput, ModelOutput

PROJECT_WIDE = "*"
JOIN_PARAMS = ("from", "view_label", "sql_on", "relationship", "type")


class DagsterAdapter(Adapter):
    name = "dagster"
    distribution = "dagster-looker"
    capabilities = Capabilities(per_model=False)

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        translator = RecordingTranslator()
        asset_utils.build_looker_view_specs(project, translator)
        asset_utils.build_looker_explore_specs(project, translator)
        return {
            PROJECT_WIDE: ModelOutput(
                views={name: kit.view_output(view) for name, view in translator.views.items()},
                explores={
                    name: summarize_explore(name, explore) for name, explore in translator.explores.items()
                },
            )
        }


class RecordingTranslator(DagsterLookerLkmlTranslator):
    """Records the resolved LookML of every view and explore dagster-looker builds a spec for."""

    def __init__(self) -> None:
        super().__init__()
        self.views: dict[str, Mapping[str, Any]] = {}
        self.explores: dict[str, Mapping[str, Any]] = {}
        self._depth = 0

    def get_asset_spec(
        self, lookml_structure: tuple[Path, LookMLStructureType, Mapping[str, Any]]
    ) -> AssetSpec:
        _, structure_type, props = lookml_structure
        # Building a spec can call get_asset_spec for upstream structures; record top-level calls only.
        if self._depth == 0:
            if structure_type == "view" and "name" in props:
                self.views[str(props["name"])] = props
            elif structure_type == "explore" and (name := props.get("explore") or props.get("name")):
                self.explores[str(name)] = props
        self._depth += 1
        try:
            return super().get_asset_spec(lookml_structure)
        finally:
            self._depth -= 1


def summarize_explore(name: str, explore: Mapping[str, Any]) -> ExploreOutput:
    joins = {
        str(join["name"]): {key: collapse_whitespace(join.get(key)) for key in JOIN_PARAMS}
        for join in explore.get("joins") or []
        if isinstance(join, Mapping) and "name" in join
    }
    return ExploreOutput(
        view_name=collapse_whitespace(explore.get("view_name") or explore.get("from") or name),
        from_view=collapse_whitespace(explore.get("from")),
        label=collapse_whitespace(explore.get("label")),
        joins=joins,
    )


if __name__ == "__main__":
    raise SystemExit(DagsterAdapter.main())
