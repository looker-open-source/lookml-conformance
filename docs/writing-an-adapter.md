# Writing an adapter

An adapter runs one tool on a LookML project and prints what the tool resolved. This guide covers
a Python adapter. For another language, print the JSON described in
[adapter-protocol.md](adapter-protocol.md); [`node_lookml_parser.js`](../src/lookml_conformance/adapters/node_lookml_parser.js)
is a complete example.

## 1. Generate the starting point

From a checkout of this repository, in an environment where your tool is installed:

```bash
pip install -e .
lookml-conformance new-adapter my-tool --distribution my-tool
```

This writes `src/lookml_conformance/adapters/my_tool.py` (or `./my_tool.py` outside the
repository). `--distribution` is the installed package whose version the adapter reports.

## 2. Implement `resolve`

The generated class subclasses `Adapter`. Implement one method: resolve one project and return its
models.

```python
from pathlib import Path

from my_tool import load_project  # your tool

from lookml_conformance.adapter import Adapter
from lookml_conformance.adapters import kit
from lookml_conformance.protocol import ModelOutput


class MyToolAdapter(Adapter):
    name = "my-tool"
    distribution = "my-tool"

    def resolve(self, project: Path) -> dict[str, ModelOutput]:
        resolved = load_project(project)  # however the tool resolves a project
        return {
            model.name: ModelOutput(views={view["name"]: kit.view_output(view) for view in model.views})
            for model in resolved.models
        }


if __name__ == "__main__":
    raise SystemExit(MyToolAdapter.main())
```

The base class handles the rest: the command line, batches of projects, the tool version, silencing
the tool's logging and warnings, and turning exceptions into `error` output.

Helpers in `lookml_conformance.adapters.kit`:

| Helper | Use |
| --- | --- |
| `kit.view_output(view, ...)` | Build a view from an lkml-style dictionary (`sql_table_name`, `derived_table`, `dimensions`, `dimension_groups`, `measures`, `extends`). Keyword arguments override values the tool computes separately, such as a table name after constant substitution. `upstream=` takes the view's lineage edges as `Upstream("table" \| "view" \| "explore", name)`. |
| `kit.model_files(project)`, `kit.model_name(path)` | The project's `.model.lkml` files, excluding imported projects. |
| `kit.imported_projects(project)` | Imported projects, keyed by name, for tools that take them as configuration. |
| `kit.field_params(field)`, `kit.derived_table(raw)` | The pieces `view_output` uses, for tools with their own view objects. |

Other hooks on `Adapter`:

| Hook | Use |
| --- | --- |
| `capabilities = Capabilities(...)` | Set a capability to `False` only when the tool never produces that output: `per_model=False` for a tool without model scoping (return one model), `explores=False` for a tool that does not read explores, `lineage=False` for a tool that builds no lineage. |
| `add_arguments(parser)` | Add tool options; read them from `self.options`. |
| `self.warn(message)` | Report a diagnostic while still returning a result. |

Report what the tool produces. If the tool leaves `@{constant}` unsubstituted, or ignores a
refinement, the adapter must pass that through so the case fails.

## 3. Check it

```bash
lookml-conformance check-adapter --command "python src/lookml_conformance/adapters/my_tool.py" --name my-tool
```

`check-adapter` runs every case and reports output that does not follow the protocol. Failing cases
are expected and do not count; only unusable output does. Then score it:

```bash
lookml-conformance run --command "python src/lookml_conformance/adapters/my_tool.py" --name my-tool
```

## 4. Make it runnable by name

Either add it to `adapters.json` with the pinned tool version, so `lookml-conformance setup` can
install it and it appears in the published scorecard:

```json
{
  "name": "my-tool",
  "label": "My Tool",
  "kind": "Metadata catalog",
  "language": "Python",
  "url": "https://github.com/example/my-tool",
  "install": {"pip": "my-tool==1.2.3"},
  "command": [".envs/my-tool/bin/python", "-m", "lookml_conformance.adapters.my_tool"]
}
```

Or, if the adapter lives in the tool's own package, register it as an entry point there:

```toml
[project.entry-points."lookml_conformance.adapters"]
my-tool = "my_tool.conformance:MyToolAdapter"
```

With the tool and `lookml-conformance` installed in one environment,
`lookml-conformance run --adapter my-tool` then runs it, which also works as a CI step in the tool's
own repository.

## When the tool uses private APIs

Prefer the tool's public functions. When the only way to get a resolved view is a private one, put
those calls together in one marked section of the adapter, as the DataHub and OpenMetadata adapters
do, so an upgrade that breaks them is quick to fix. `pytest -m integration` re-runs every installed
tool and fails when its results change.
