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
    # e.g. Capabilities(per_model=False) for a tool without model scoping.
    capabilities = Capabilities()

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        models = {{}}
        for model_file in kit.model_files(project):
            # TODO: run {name} on this model and collect the views it resolved,
            # as lkml-style dictionaries: {{"name": ..., "sql_table_name": ...,
            # "dimensions": [...], ...}}.
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
