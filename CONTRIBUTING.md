# Contributing

## Before you begin

### Sign our Contributor License Agreement

Contributions to this project must be accompanied by a
[Contributor License Agreement](https://cla.developers.google.com/about) (CLA).
You (or your employer) retain the copyright to your contribution; this simply
gives us permission to use and redistribute your contributions as part of the
project.

If you or your current employer have already signed the Google CLA (even if it
was for a different project), you probably don't need to do it again.

Visit <https://cla.developers.google.com/> to see your current agreements or to
sign a new one.

### Review our Community Guidelines

This project follows [Google's Open Source Community
Guidelines](https://opensource.google/conduct/).

## Setup

```bash
uv sync --group dev
uv run pytest
```

Before a pull request: `uv run ruff check .`, `uv run ruff format .`, `uv run mypy`, and
`uv run pytest`. CI also checks that `CASES.md` and `site/data.json` are current.

## Adding a case

1. Pick the category and the next free id, for example `cases/refinements/r14_<summary>/`.
2. Write the smallest LookML project in `project/` that isolates one rule. Use `orders` as the view
   name where it fits, so cases read alike.
3. Write `case.json` (format: [docs/case-format.md](docs/case-format.md)). Quote the Looker
   documentation word for word and link the closest section anchor. If the documentation does not
   settle the behavior, mark the case `provisional`, state the question, and name the public source
   the expectation is pinned to.
4. Run:

   ```bash
   lookml-conformance validate
   lookml-conformance check-citations
   lookml-conformance catalog
   ```

5. Run the tools (`lookml-conformance run`) and include the regenerated `results/latest.json`,
   `results/latest.md` and `site/data.json`:

   ```bash
   lookml-conformance run --json results/latest.json --markdown results/latest.md
   lookml-conformance site
   ```

One case tests one rule. If a case fails a tool for two independent reasons, split it.

## Adding a tool

Follow [docs/writing-an-adapter.md](docs/writing-an-adapter.md). In short:

1. `lookml-conformance new-adapter <tool>` and implement `resolve()`.
2. `lookml-conformance check-adapter --command "<your adapter command>"` until the output follows
   the protocol on every case.
3. Add the tool to `adapters.json` with its pinned version under `install`, run
   `lookml-conformance setup <tool>`, and regenerate the scorecard and site data as above.
4. `uv run pytest -m integration` checks that the published scorecard reproduces.

The adapter must report what the tool produces and nothing more.

## Updating a tool version

Change the pin in `adapters.json`, run `lookml-conformance setup <tool>`, regenerate the scorecard
and the site data, and note notable changes in the commit message.
