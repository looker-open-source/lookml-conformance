# LookML Corpus Study (1,996 → 1,782 → 156 → 18 Repositories)

This directory contains the empirical LookML corpus harvest, selection funnel, and differential study across public LookML repositories on GitHub.

## Layout

- **`RESULTS.md`**: Full report of the 18-repository non-Google LookML differential study (108 models, 3,051 explore views).
- **`blocks_differential_table.md`** & **`blocks_commits.txt`**: Companion differential table across 12 public `looker-open-source` LookML Blocks (193 explore views).
- **`scout/`**: Discovery and selection funnel (`search2.sh`, `clone.sh`, `measure.py`, `google_overlap.py`, `build_pool.py`, `make_report.py`, and `CANDIDATES_2026-10-08.md`):
  - `1,996` distinct repositories returned by GitHub search (`language:LookML` + topic/keyword queries)
  - `1,782` non-Google repositories shallow-cloned and measured alongside `219` `looker-open-source` / `llooker` repositories to filter out Google block copies (`282`, ~32% of public LookML) and demo copies (`295`, `thelook` / `faa` / `healthcare_demo`)
  - `156` independent candidate repositories with `>= 1` `*.model.lkml` and `>= 1` refinement (`view:/explore: +name`) or `extends:`
  - `18` repositories selected for the full differential run (all Tier-1 organization estates with resolvable public imports, plus top individual sandboxes by refinement count)
- **`harness/`**: Differential and end-to-end execution drivers (`differential.py`, `om_e2e.py`, `oracle.js`, `oracle_full.js`, `run_differential.sh`, `run_om_e2e.sh`).
- **`differential_2026-10-08/`**: Per-repository JSON differential outputs across the 18 repositories (`mozilla_looker-spoke-default.json`, `mattermost_mattermost-looker.json`, `bcgov_GDX-Analytics-Looker-Snowplow-Web-Block.json`, etc.), pinned commit SHAs (`commits.txt`), runner (`run_corpus.sh`), and residual classifiers (`summarize_corpus.py`, `classify_residuals.py`, `summary.md`).
