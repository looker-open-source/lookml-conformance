# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Adapter for Dagster's Looker integration (``dagster-looker``).

    python -m lookml_conformance.adapters.dagster <project>...

The adapter calls ``build_looker_asset_specs``, the function users call to turn a LookML project
into asset specs. It hands every resolved view and explore to a ``DagsterLookerLkmlTranslator``;
the adapter passes one that records them, and records each view's upstream from the ``deps`` of
its asset spec: asset keys ``["view", name]`` are Looker views, any other key is a warehouse
table. dagster-looker resolves the project as a whole, so the result is reported as one
project-wide model.

dagster-looker finds files with ``Path.rglob`` and applies refinements in the order it lists them.
The adapter passes a plain ``Path``, so files are read in the order the file system lists them, as
in a real run. That order depends on the file system: APFS (macOS) lists a directory in an order
fixed by the file names, and ext4 (Linux) in an order that also depends on a hash seed chosen when
the file system was created.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dagster import AssetKey, AssetSpec
from dagster_looker import build_looker_asset_specs
from dagster_looker.lkml.dagster_looker_lkml_translator import (
    DagsterLookerLkmlTranslator,
    LookMLStructureType,
)

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.normalize import collapse_whitespace
from lookml_conformance.protocol import Capabilities, ExploreOutput, ModelOutput, Upstream

PROJECT_WIDE = "*"
JOIN_PARAMS = ("from", "view_label", "sql_on", "relationship", "type")


class DagsterAdapter(Adapter):
    name = "dagster"
    distribution = "dagster-looker"
    capabilities = Capabilities(per_model=False)

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        translator = RecordingTranslator()
        build_looker_asset_specs(project_dir=project, dagster_looker_translator=translator)
        return {
            PROJECT_WIDE: ModelOutput(
                views={
                    name: kit.view_output(view, upstream=translator.upstream.get(name, ()))
                    for name, view in translator.views.items()
                },
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
        self.upstream: dict[str, tuple[Upstream, ...]] = {}
        self._depth = 0

    def get_asset_spec(
        self, lookml_structure: tuple[Path, LookMLStructureType, Mapping[str, Any]]
    ) -> AssetSpec:
        _, structure_type, props = lookml_structure
        # Building a spec calls get_asset_spec for upstream structures; record top-level calls only.
        top_level = self._depth == 0
        self._depth += 1
        try:
            spec = super().get_asset_spec(lookml_structure)
        finally:
            self._depth -= 1
        if top_level:
            if structure_type == "view" and "name" in props:
                name = str(props["name"])
                self.views[name] = props
                self.upstream[name] = tuple(upstream_from_key(dep.asset_key) for dep in spec.deps)
            elif structure_type == "explore" and (name := props.get("explore") or props.get("name")):
                self.explores[str(name)] = props
        return spec


def upstream_from_key(key: AssetKey) -> Upstream:
    """dagster-looker keys views as ``["view", name]`` and tables by their name parts."""
    if len(key.path) == 2 and key.path[0] == "view":
        return Upstream("view", key.path[1])
    return Upstream("table", ".".join(key.path))


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
