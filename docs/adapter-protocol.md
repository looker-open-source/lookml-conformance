# Adapter protocol

This is the reference for what an adapter prints. To write one, start with
[writing-an-adapter.md](writing-an-adapter.md).

An adapter is an executable that:

1. takes one or more LookML project directories as its final arguments,
2. runs one tool on each project, and
3. prints one JSON object per project on stdout, each on its own line.

Lines that are not JSON objects, and anything on stderr, are ignored, so the tool may log freely.

An adapter reports what the tool produces and nothing more. It must not merge refinements,
substitute constants, resolve extends, or fill any other gap the tool leaves. A case the tool gets
wrong must fail.

## Batches

The runner passes a chunk of projects to each adapter process, so a tool's start-up cost is paid
once per chunk. Each output line names its project in the `project` key, exactly as the path was
given on the command line, and lines may come in any order.

If a run ends without a line for some project (the tool crashed part-way, or timed out), the runner
runs those projects again one at a time. An adapter that only handles one project per run, and does
not print `project`, therefore still works: the runner falls back to one process per case. The
timeout is 300 seconds per project. `lookml-conformance run --no-batch`, or `"batch": false` in
`adapters.json`, starts one process per case.

## Output

```json
{
  "adapter": "datahub",
  "version": "1.7.0.14",
  "project": "/path/to/cases/refinements/r01_refinement_overrides_sql_table_name/project",
  "capabilities": {"per_model": true, "explores": true, "imported_projects": true, "constants": true, "lineage": true},
  "models": {
    "ecommerce": {
      "views": {
        "orders": {
          "sql_table_name": "analytics.orders_clean",
          "derived_table": null,
          "fields": ["id", "status"],
          "field_params": {"id": {"sql": "${TABLE}.id", "type": "number"}},
          "extends": null,
          "upstream": [{"table": "analytics.orders_clean"}]
        },
        "order_facts": {
          "sql_table_name": null,
          "derived_table": {"sql": "SELECT customer_id, COUNT(*) FROM ${orders.SQL_TABLE_NAME} GROUP BY 1"},
          "fields": ["customer_id"],
          "field_params": {},
          "extends": null,
          "upstream": [{"view": "orders"}]
        },
        "users": {"error": "KeyError('dimensions')"}
      },
      "explores": {
        "orders": {"view_name": "orders", "from": null, "label": null, "joins": {}}
      },
      "all_views": ["order_facts", "orders", "users"]
    }
  },
  "errors": []
}
```

| Key | Meaning |
| --- | --- |
| `adapter` | Required. The adapter's name. |
| `version` | The tool version that ran. |
| `project` | The project path as received. Required when the adapter is given several projects. |
| `capabilities` | Optional; every capability defaults to `true`. Set one to `false` only when the tool produces no output of that kind, for example explores for a tool that reads them from the Looker API. Cases that need it are scored N/A. |
| `models` | One entry per model, keyed by model name. |
| `models.*.views` | Each resolved view. `field_params` holds the parameters the cases check: `sql`, `label`, `type`, `timeframes`, `filters` (a list of one-key objects). `upstream` is described below. A view the tool failed on can be reported as `{"error": "..."}`. |
| `models.*.explores` | Each resolved explore, with joins keyed by join name. |
| `models.*.all_views` | Every view the tool would expose, including refinements it mistakes for views. Defaults to the keys of `views`. |
| `errors` | Diagnostics the tool reported while still producing a result. They do not affect the verdict. |
| `error` | Set instead of `models` when the tool produced no result for this project. The case is scored as an adapter error. |

### Lineage

`upstream` lists a view's direct upstreams in the tool's lineage graph, each as one of:

| Entry | Meaning |
| --- | --- |
| `{"table": "raw.orders"}` | A warehouse table, as the tool names it. |
| `{"view": "orders"}` | A view of the same model, for example from `${orders.SQL_TABLE_NAME}`. |
| `{"explore": "orders"}` | An explore of the same model, for example the `explore_source` of a native derived table. |

Report the edges the tool draws, not the tables they lead to: the judge follows view and explore
entries through the rest of the output. `null` (or no key) means the tool reported no lineage for
the view; `[]` means it reported lineage with no upstream.

[`adapter-output.schema.json`](adapter-output.schema.json) is the same format as a JSON Schema
(draft 2020-12), for adapters written in any language.

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
| error | The adapter crashed, timed out, printed no line for the project, or printed JSON that does not follow this protocol. |
| N/A | The case needs a capability the adapter declares `false`. |

## Running adapters by name

Python adapters can be registered under the `lookml_conformance.adapters` entry point group. An
installed adapter then runs with `python -m lookml_conformance.adapters <name> <project>...`, and
`lookml-conformance run --adapter <name>` finds it without an `adapters.json` entry.
`lookml-conformance adapters` lists the adapters in the registry and those installed.
