# Adapter protocol

An adapter is an executable that:

1. takes the path of a LookML project directory as its last argument,
2. runs one tool on that project, and
3. prints one JSON object on the last line of stdout.

Anything else on stdout before the last line, and anything on stderr, is ignored. The runner starts
one adapter process per case, with a timeout of 300 seconds.

An adapter reports what the tool produces and nothing more. It must not merge refinements,
substitute constants, resolve extends, or fill any other gap the tool leaves. A case the tool gets
wrong must fail.

## Output

```json
{
  "adapter": "datahub",
  "version": "1.7.0.14",
  "capabilities": {"per_model": true, "explores": true, "imported_projects": true, "constants": true},
  "models": {
    "ecommerce": {
      "views": {
        "orders": {
          "sql_table_name": "analytics.orders_clean",
          "derived_table": null,
          "fields": ["id", "status"],
          "field_params": {"id": {"sql": "${TABLE}.id", "type": "number"}},
          "extends": null
        },
        "users": {"error": "KeyError('dimensions')"}
      },
      "explores": {
        "orders": {"view_name": "orders", "from": null, "label": null, "joins": {}}
      },
      "all_views": ["orders", "users"]
    }
  },
  "errors": []
}
```

| Key | Meaning |
| --- | --- |
| `adapter` | Required. The adapter's name. |
| `version` | The tool version that ran. |
| `capabilities` | Optional; every capability defaults to `true`. Set one to `false` only when the tool produces no output of that kind, for example explores for a tool that reads them from the Looker API. Cases that need it are scored N/A. |
| `models` | One entry per model, keyed by model name. |
| `models.*.views` | Each resolved view. `field_params` holds the parameters the cases check: `sql`, `label`, `type`, `timeframes`, `filters` (a list of one-key objects). A view the tool failed on can be reported as `{"error": "..."}`. |
| `models.*.explores` | Each resolved explore, with joins keyed by join name. |
| `models.*.all_views` | Every view the tool would expose, including refinements it mistakes for views. Defaults to the keys of `views`. |
| `errors` | Diagnostics the tool reported while still producing a result. They do not affect the verdict. |
| `error` | Set instead of `models` when the tool produced no result. The case is scored as an adapter error. |

### Tools without model scope

A tool that resolves the whole project at once sets `capabilities.per_model` to `false` and
reports a single model under any name (the bundled adapters use `"*"`). That model is compared with
every model the case expects, so a refinement that leaks from one model into another shows up as a
failure.

## Verdicts

| Verdict | When |
| --- | --- |
| pass | Every asserted key matches. |
| fail | At least one asserted key differs, or a view that must not exist is exposed. |
| error | The adapter crashed, timed out, printed no JSON, or printed JSON that does not follow this protocol. |
| N/A | The case needs a capability the adapter declares `false`. |

## Writing a Python adapter

Python adapters live in `src/lookml_conformance/adapters/` and use `kit.py`:

```python
from pathlib import Path
import argparse

from lookml_conformance.adapters import kit
from lookml_conformance.protocol import AdapterOutput, ModelOutput


def resolve(root: Path, args: argparse.Namespace) -> AdapterOutput:
    models = {}
    for model_file in kit.model_files(root):
        views = my_tool.resolve(model_file)  # the tool's own resolution
        models[kit.model_name(model_file)] = ModelOutput(
            views={name: kit.view_output(view) for name, view in views.items()}
        )
    return AdapterOutput(adapter="my-tool", models=models)


def main() -> int:
    return kit.run_adapter("my-tool", "my-tool-distribution", resolve)
```

`run_adapter` parses the arguments, fills in the version from the installed distribution, silences
the tool's logging and warnings, and turns any exception into an `error` output.
`kit.view_output` builds a view from an lkml-style dictionary.

Adapters in other languages only need to print the JSON above; see `node_lookml_parser.js`.
