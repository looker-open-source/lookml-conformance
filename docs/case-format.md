# Case format

A case is a directory `cases/<category>/<id>/`:

```text
case.json     the rule, the documentation it comes from, and the expected resolution
project/      a minimal LookML project
```

Categories: `refinements`, `includes`, `extends`, `model_scope`, `explores`, `constants`, `lineage`,
`syntax`. Ids start with the category letter (`r`, `i`, `e`, `m`, `x`, `c`, `l`, `p`), two digits and
a snake_case summary, and match the directory name.

`lookml-conformance validate` checks every case against this format.

## `case.json`

| Key | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Same as the directory name. |
| `title` | yes | One line, shown in listings. |
| `rule` | yes | The rule under test, in one sentence. |
| `status` | yes | `confirmed` or `provisional` (see below). |
| `citations` | yes | One or more `{"url", "quote"}`. `quote` is verbatim text from the page; `url` links to the closest section anchor. |
| `rationale` | no | How the quotes lead to the expectation, when that is not immediate. |
| `provisional` | provisional only | `{"question", "pinned_to"}`: what the documentation leaves open, and the public source the expectation follows. |
| `invalid_in_looker` | no | `true` when Looker rejects the project (for example a refinement after `final: yes`). Tools may report an error but must not produce the forbidden result. |
| `expect` | yes | `{"models": {...}, "absent_views": [...]}`, described below. |

### Status

- **confirmed**: the expectation follows from the quoted documentation.
- **provisional**: the documentation does not settle the behavior. The case states the question
  and the source it is pinned to, and stays provisional until it is checked on a Looker instance.

### Citations

Quotes are copied word for word, without Markdown and without ellipses. Quote a shorter fragment
instead of shortening a sentence. `lookml-conformance check-citations` fetches each page, extracts
its text, and fails for any quote it cannot find. Citations point at the Looker documentation:
`docs.cloud.google.com/looker/docs/` and, where the documentation has no statement, the Looker
community knowledge base.

### Expectations

Expectations are per model. A model name is the file name of a `<name>.model.lkml` file in
`project/`. **Only the keys present are checked**, so a case asserts exactly what its rule is about.

```json
{
  "models": {
    "main": {
      "views": {
        "orders": {
          "sql_table_name": "analytics.orders_clean",
          "derived_table": {"sql": "SELECT id FROM raw.orders", "datagroup_trigger": "daily"},
          "fields": ["id", "status"],
          "field_params": {"id": {"label": "Order ID", "sql": "${TABLE}.id", "timeframes": ["date"]}},
          "extends": ["base_a", "base_b"]
        },
        "order_facts": {"upstream_tables": ["raw.orders"]}
      },
      "explores": {
        "buyer_orders": {
          "view_name": "orders",
          "from": "orders",
          "label": "Buyer Orders",
          "joins": {"buyer": {"from": "users", "sql_on": "${buyer_orders.user_id} = ${buyer.id}"}}
        }
      }
    }
  },
  "absent_views": ["+orders"]
}
```

| Key | Compared as |
| --- | --- |
| `sql_table_name` | Text with whitespace collapsed. `null` asserts that the view has no table name. |
| `derived_table` | Each listed parameter, as text. Unlisted parameters are ignored. |
| `fields` | Set of dimension, dimension group and measure names. |
| `field_params` | Per field, per listed parameter. `filters` is an ordered list of one-key objects; `timeframes` is compared as a set; anything else as text. |
| `extends` | Ordered list. |
| `upstream_tables` | Set of warehouse tables the view reads, lower-cased. The tool's view and explore upstreams are followed to their tables (see [adapter-protocol.md](adapter-protocol.md#lineage)). |
| explore `view_name`, `from`, `label` | Text. |
| explore `joins` | Per join, per listed parameter (`from`, `view_label`, `sql_on`, `relationship`, `type`), as text. |
| `absent_views` | Names that no model may expose as a view, such as a refinement mistaken for a view (`+orders`). |

## `project/`

A minimal LookML project: model files, view files, any other `.lkml` files, and an optional
`manifest.lkml`. Imported projects live under `project/imported_projects/<name>/`, the folder the
Looker IDE shows them in, so `include: "//shared/views/orders.view"` resolves to
`imported_projects/shared/views/orders.view.lkml`.

## Capabilities

Some tools do not produce a kind of output at all. A case needs a capability when:

| Capability | The case needs it when |
| --- | --- |
| `explores` | it asserts an explore |
| `imported_projects` | its project has an `imported_projects/` directory |
| `constants` | its `manifest.lkml` declares a `constant` |
| `lineage` | it asserts `upstream_tables` |

An adapter that declares the capability `false` is scored N/A on those cases.
