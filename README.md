# lookml-conformance

A conformance suite for tools that resolve LookML projects: metadata catalogs, orchestrators,
parsers and linters that read LookML from git instead of asking a Looker instance.

Parsing a `.lkml` file is the easy part; [`lkml`](https://github.com/joshtemple/lkml) does it well.
The hard part is resolving a project the way Looker does: following `include:` statements per
model, applying refinements in include order, merging `extends`, and substituting manifest
constants. Every tool that builds lineage from LookML implements this resolution itself, and then
traces each view to the tables it reads. This suite checks both against the Looker documentation.

Results and case explorer: https://josephaxisa.github.io/lookml-conformance/

## Results

Released versions, scored on 2026-10-10 ([full scorecard](results/latest.md)):

| Tool | Version | Confirmed | Provisional | All |
| --- | --- | ---: | ---: | ---: |
| [node-lookml-parser](https://github.com/fabio-looker/node-lookml-parser) | `lookml-parser` 9.1.0 | 19 / 26 | 6 / 8 | **25 / 34** |
| [Dagster](https://github.com/dagster-io/dagster) | `dagster-looker` 0.29.25 | 16 / 31 | 5 / 8 | **21 / 39** |
| [DataHub](https://github.com/datahub-project/datahub) | `acryl-datahub[lookml]` 1.7.0.14 | 16 / 31 | 1 / 8 | **17 / 39** |
| [OpenMetadata](https://github.com/open-metadata/OpenMetadata) | `openmetadata-ingestion[looker]` 2.0.5.0 | 10 / 29 | 0 / 8 | **10 / 37** |

OpenMetadata reads explores from the Looker API, so the two explore cases do not apply to it.
node-lookml-parser builds no lineage, so the five lineage cases do not apply to it.

## Cases

39 cases in eight categories. [CASES.md](CASES.md) lists each one with its rule and quotes.

| Category | Cases | What it covers |
| --- | ---: | --- |
| Refinements | 13 | Overrides, field-level merges, include order, order within a file, additive `filters`, `final: yes`, `derived_table` merges |
| Includes | 9 | Wildcards, nested includes, relative paths, imported projects, cycles, dashboard files |
| Extends | 4 | Several parents, `extends` added by a refinement, child overrides |
| Model scope | 1 | A refinement does not leak into a model that does not include it |
| Explores | 2 | `view_name`, `from`, join `from`, explore refinements |
| Constants | 2 | `@{NAME}` in `sql_table_name` and derived table SQL |
| Lineage | 5 | `${view.SQL_TABLE_NAME}` in derived tables, chains of derived tables, references to refined views, native derived tables |
| Syntax | 3 | `;` and `#` inside SQL blocks, fields named `errors` and `info` |

A case is a directory with a minimal LookML project and a `case.json` that states the rule, quotes
the Looker documentation it comes from, and lists the expected resolution per model:

```json
{
  "id": "r04_later_include_wins",
  "title": "Refinements apply in include order: the file included last wins",
  "rule": "When two included files refine the same view, the file included last wins.",
  "status": "confirmed",
  "citations": [
    {
      "url": "https://docs.cloud.google.com/looker/docs/lookml-refinements#order",
      "quote": "Refinements from files included last will override refinements from files included earlier."
    }
  ],
  "expect": {"models": {"m": {"views": {"orders": {"sql_table_name": "from_a"}}}}}
}
```

Cases are **confirmed** when the expectation follows from the quoted documentation (31 cases) and
**provisional** when the documentation leaves the behavior open (8 cases). A provisional case states
the open question and names the public source its expectation is pinned to, until it is checked on
a Looker instance, which the [Looker adapter](docs/looker-adapter.md) does through the Looker API
([procedure](docs/confirming-provisional-cases.md)).
`lookml-conformance check-citations` fetches every cited page and fails if a
quote is no longer on it.

## Usage

Requires Python 3.10 or later. The runner has no dependencies.

```bash
git clone https://github.com/josephaxisa/lookml-conformance
cd lookml-conformance
pip install -e .
```

Reproduce the published scorecard. `setup` installs each tool version pinned in
[`adapters.json`](adapters.json) into `.envs/<tool>/` (uses `uv` if installed, otherwise `venv`;
node-lookml-parser needs `npm`):

```bash
lookml-conformance setup --python python3.11
lookml-conformance run                                 # all tools, about 10 seconds
lookml-conformance run --adapter datahub --only r0     # one tool, cases whose id contains "r0"
```

Each adapter process resolves a batch of cases, so a tool's start-up cost is paid once per batch.
`--no-batch` starts one process per case instead.

Score a branch or a local build. Install the branch and this package into one environment, then
pass the adapter command:

```bash
pip install -e ../datahub/metadata-ingestion -e .
lookml-conformance run --command "python -m lookml_conformance.adapters.datahub" --name datahub-branch
```

`run` exits with status 1 when any applicable case fails, so the same command works as a CI step.
`--json` and `--markdown` write the scorecard.

Other commands:

| Command | Does |
| --- | --- |
| `list` | List the cases |
| `validate` | Check every `case.json` against the case format |
| `report results/latest.json` | Render a JSON scorecard as Markdown |
| `catalog` | Regenerate `CASES.md` |
| `check-citations` | Check that every quote is still on its page (needs network) |
| `site` | Regenerate `site/data.json` for the website |
| `adapters` | List the adapters in `adapters.json` and those installed as entry points |
| `new-adapter NAME` | Write a starting point for a new Python adapter |
| `check-adapter` | Check that an adapter's output follows the protocol on every case |

## Using the cases in your own tests

A tool can also run the cases in its own test suite, without installing this package. Copy a
case's `case.json` and `project/` from a tagged release, keep the release's license notice, and
put a short note at the top of the copy:

```text
From lookml-conformance <release>, case <id>
https://github.com/josephaxisa/lookml-conformance/tree/<release>/cases/<category>/<id>
```

Then write one test that resolves each copied `project/` with your tool and checks the result
against `expect` ([how values are compared](docs/case-format.md#expectations)). Mark the cases your
tool fails today as strict expected failures:

```python
KNOWN_FAILURES = {"r09_field_filters_are_additive": "filters are replaced, not appended"}

@pytest.mark.parametrize("case_file", CASES, ids=lambda p: p.parent.name)
def test_lookml_conformance(case_file, request):
    case = json.loads(case_file.read_text())
    if case["id"] in KNOWN_FAILURES:
        request.applymarker(pytest.mark.xfail(reason=KNOWN_FAILURES[case["id"]], strict=True))
    ...
```

A change that breaks a passing case fails the run. A fix that makes a known failure pass also fails
it, until the case is removed from the list. To update, copy the cases again from a newer release.

## Adapters

An adapter runs one tool on LookML projects and prints one JSON line per project. It reports what
the tool produces and nothing more: it must not merge refinements, substitute constants, or fill any
other gap the tool leaves.

| Tool | Adapter command |
| --- | --- |
| OpenMetadata | `python -m lookml_conformance.adapters.openmetadata` |
| DataHub | `python -m lookml_conformance.adapters.datahub` |
| Dagster | `python -m lookml_conformance.adapters.dagster` |
| node-lookml-parser | `node src/lookml_conformance/adapters/node_lookml_parser.js` (set `LOOKML_PARSER_PATH` to test a checkout) |
| Looker itself | `python -m lookml_conformance.adapters.looker` (needs a Looker instance; see [docs/looker-adapter.md](docs/looker-adapter.md)) |

Adding a tool takes one class with one method:

```bash
lookml-conformance new-adapter my-tool      # writes the class, with the steps to fill in
lookml-conformance check-adapter --command "python src/lookml_conformance/adapters/my_tool.py"
```

A tool can also ship its adapter in its own package, registered under the
`lookml_conformance.adapters` entry point group; `lookml-conformance run --adapter my-tool` then
finds it without changes to this repository. See [docs/writing-an-adapter.md](docs/writing-an-adapter.md)
for the walkthrough and [docs/adapter-protocol.md](docs/adapter-protocol.md) for the output format,
also available as a [JSON Schema](docs/adapter-output.schema.json).

## Repository layout

```text
cases/<category>/<id>/       case.json and project/ (a minimal LookML project)
src/lookml_conformance/      loader, judge, runner, scorecards, CLI, Adapter base class
src/lookml_conformance/adapters/   one adapter per tool, plus kit.py with helpers for writing them
adapters.json                tools in the published scorecard: command and pinned version
results/latest.{json,md}     published scorecard
site/                        website (GitHub Pages)
docs/                        case format, adapter protocol and schema, adapter walkthrough
tests/                       unit tests; tests/adapters/ also re-runs installed tools (pytest -m integration)
```

## Development

```bash
uv sync --group dev
uv run pytest                    # unit tests
uv run pytest -m integration     # re-run installed tools against results/latest.json
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
