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

"""Generate a starting point for a new Python adapter (``lookml-conformance new-adapter``)."""

from __future__ import annotations

import re

_NAME = re.compile(r"^[a-z][a-z0-9-]*$")

TEMPLATE = '''\
"""Adapter for {name}.

    python {path} <project>...

Report what {name} produces and nothing more: do not merge refinements,
substitute constants or fill any other gap the tool leaves. A case the tool
gets wrong must fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.protocol import Capabilities, ModelOutput

# TODO: import {name}.


class {class_name}(Adapter):
    name = "{name}"
    distribution = "{distribution}"  # the installed package whose version is reported
    # Set a capability to False only when the tool never produces that output,
    # e.g. Capabilities(per_model=False) for a tool without model scoping, or
    # Capabilities(lineage=False) for a tool that builds no lineage.
    capabilities = Capabilities()

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        models = {{}}
        for model_file in kit.model_files(project):
            # TODO: run {name} on this model and collect the views it resolved,
            # as lkml-style dictionaries: {{"name": ..., "sql_table_name": ...,
            # "dimensions": [...], ...}}. If the tool builds lineage, pass each view's
            # upstreams to kit.view_output as upstream=[Upstream("table", ...), ...]
            # (Upstream is in lookml_conformance.protocol).
            views: dict[str, dict[str, Any]] = {{}}
            models[kit.model_name(model_file)] = ModelOutput(
                views={{name: kit.view_output(view) for name, view in views.items()}},
            )
        return models


if __name__ == "__main__":
    raise SystemExit({class_name}.main())
'''


def module_name(name: str) -> str:
    return name.replace("-", "_")


def class_name(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_]", name)) + "Adapter"


def adapter_template(name: str, distribution: str | None = None, path: str | None = None) -> str:
    """Source code for a new adapter named ``name`` (lowercase letters, digits and hyphens)."""
    if not _NAME.match(name):
        raise ValueError(
            f"adapter name {name!r} must be lowercase letters, digits and hyphens, e.g. 'my-tool'"
        )
    return TEMPLATE.format(
        name=name,
        distribution=distribution or name,
        class_name=class_name(name),
        path=path or f"{module_name(name)}.py",
    )
