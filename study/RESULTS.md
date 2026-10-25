# Non-Google LookML corpus — OpenMetadata before/after differential (2026-10-08)

Companion to [`blocks_differential_table.md`](blocks_differential_table.md) (which covers 12
`looker-open-source` blocks + 3 synthetic cases). This study evaluates whether per-model LookML
refinement and include resolution holds on LookML written by independent organisations at
production scale without regressions.

## 1. Headline (18 repositories, 108 models, 3,051 explore views)

| Metric (OpenMetadata `BulkLkmlParser`, baseline `ee588e9c77` → branch `om-fix`) | Before | After |
|---|--:|--:|
| Explore views whose **upstream source** (`sql_table_name` / `derived_table.sql`) equals the reference parser | 2,939 | **2,979** |
| Explore views whose **field list** equals the reference parser | 2,711 | **2,922** |
| **Phantom `+view` data models** (refinement declarations ingested as if they were views) | 211 | **0** |
| **Regressions** (a view correct before and wrong after) | — | **0** |

- The largest independent LookML estate on GitHub, **Mozilla's** (`looker-spoke-default`, 49 models,
  565 files, 224 refinements, imports the 3,433-file `looker-hub`), goes from 1,760 to 1,923 views with
  the correct field list and from 155 phantom data models to none.
- 10 of the 18 repositories use refinements; the other 8 (`extends`- and import-heavy, no refinements)
  act as regression controls. All 8 are unchanged except two Mattermost views that are now resolved
  correctly — attributable to per-model include resolution (OM-3), the only patch mechanism that can
  fire in a repository without refinements.
- 132 explore views still differ from the reference after the fix. **None is a refinement defect**
  (§4): 124 are `extends` views (OpenMetadata models `extends` as a view→view lineage edge and does
  not flatten the parent, by design), 5 are views with duplicate field names in the source (a LookML
  error the two parsers represent differently), 3 are a quirk of the *reference parser* (it emits a
  lone `;` inside a `sql:` block as `;,`; OpenMetadata's text is the faithful one). All 132 are
  identical before and after.

## 2. Method

1. **Discovery** (`scout/`, same day): GitHub REST searches for `language:LookML` (7,723 repositories
   total; top-1,000 by stars and top-1,000 recently pushed, plus topic/keyword searches) gave a pool
   of 1,996 repositories; 1,782 non-Google ones were shallow-cloned and measured
   (`scout/measure.py`), and 219 `looker-open-source` / `llooker` repositories were cloned separately
   to detect copies of Google's own blocks (`scout/google_overlap.py`). Classification: 156
   candidates, 295 demo copies (`thelook` etc.), 282 Google-block copies (~32 % of public LookML is
   Google-derived and was excluded), 21 tool fixtures, the rest without a model file or without any
   refinement/`extends`. Full ranked list: `scout/CANDIDATES_2026-10-08.md`.
2. **Selection:** every Tier-1 (organisation-owned) candidate whose imported projects were also
   public and resolvable, plus the top individual sandboxes by refinement count, up to 18. Imported
   projects were copied to `imported_projects/<name>/` (the layout both OpenMetadata and the
   reference parser use for `//project/...` includes) with the dependency's own `*.model.lkml`
   removed so they are not scored as part of the importing project (`run_corpus.sh`).
3. **Differential** (`harness/differential.py`, unchanged from the
   Google-block run): for each model, every view referenced by an explore is resolved three ways —
   reference parser (`node-lookml-parser` 9.1.0, `oracle_full.js`), OpenMetadata **baseline**
   (`harness/old_bulk_parser.py`, byte-identical to `bulk_parser.py` at `ee588e9c77`) and
   OpenMetadata **fixed** (`om-fix` = refinement merge + per-model include scoping). "Checked" counts only views the reference
   could resolve in that model. A view counts as matching when `(sql_table_name, derived_sql)` and
   the sorted field-name list equal the reference. Phantoms = keys in `_views_cache` starting with
   `+`. A regression is any view that matched before and not after.
4. **Residual classification** (`classify_residuals.py`): for each view still mismatching after the
   fix, in order — view block declares `extends:` → `extends`; OpenMetadata returned no view →
   `unresolved`; source strings differ → `src_differs` (sub-class `constant_subst` when only a
   `@{…}` differs); otherwise `fields_only` (set difference of field names reported).
5. **Environment:** personal machine, Python 3.10.2, `openmetadata-ingestion` editable install from the local
   clone, `lkml` 1.3.7, Node 22, `node-lookml-parser` 9.1.0. Wall clock for the 18 runs: 22 min
   (06:30–06:53 UTC); the three Mozilla spokes each parse the full hub twice (~125 s per parse).

## 3. Results per repository

Commits are the shallow-clone HEADs recorded in `differential_2026-10-08/commits.txt`.
"Table" = explore views whose upstream source equals the reference; "Fields" = whose field list
equals the reference; both before → after. "Residual" = mismatches remaining after the fix, by class.

| # | Repository @ commit (last commit) | Owner | Models | Checked | Table | Fields | Phantom `+view` | Regr. | Residual |
|--:|---|---|--:|--:|---|---|---|--:|---|
| 1 | [mozilla/looker-spoke-default](https://github.com/mozilla/looker-spoke-default) @ `469e3e0` (2026-09-02), imports `looker-hub` | non-profit | 49 | 1,965 | 1,885 → 1,921 | 1,760 → 1,923 | **155 → 0** | 0 | extends 42 · reference `;` quirk 2 |
| 2 | [mozilla/looker-spoke-dev](https://github.com/mozilla/looker-spoke-dev) @ `09b54c1` (2025-03-28), imports `looker-hub` | non-profit | 3 | 4 | 4 → 4 | 2 → 4 | 2 → 0 | 0 | none |
| 3 | [mozilla/looker-spoke-temporary-default](https://github.com/mozilla/looker-spoke-temporary-default) @ `52cddbf` (2021-03-11), imports `looker-hub` | non-profit | 3 | 30 | 18 → 18 | 16 → 16 | 0 → 0 | 0 | extends 14 |
| 4 | [mozilla/looker-hub](https://github.com/mozilla/looker-hub) @ `8c1f514` (2026-10-07) | non-profit | 1 | 0 | — | — | 0 → 0 | 0 | `hub.model.lkml` is a stub (all includes commented out); its 3,433 files are exercised through rows 1–3 |
| 5 | [mattermost/mattermost-looker](https://github.com/mattermost/mattermost-looker) @ `0fa7e00` (2024-12-23) | enterprise | 7 | 241 | 239 → **241** | 239 → **241** | 0 → 0 | 0 | none |
| 6 | [bcgov/GDX-Analytics-Looker-Snowplow-Web-Block](https://github.com/bcgov/GDX-Analytics-Looker-Snowplow-Web-Block) @ `d53a6f0` (2026-08-13), imports `cfms_block`, `cmslite_metadata` | government (BC, Canada) | 1 | 91 | 90 → 90 | 47 → 47 | 0 → 0 | 0 | extends 44 |
| 7 | [bytecodeio/bytecode-looker-hackathon](https://github.com/bytecodeio/bytecode-looker-hackathon) @ `917342c` (2019-12-16) | consultancy | 5 | 153 | 153 → 153 | 153 → 153 | 0 → 0 | 0 | none |
| 8 | [QubitProducts/looker-source-block](https://github.com/QubitProducts/looker-source-block) @ `873bc36` (2019-06-11) | vendor block | 2 | 13 | 0 → 0 | 0 → 0 | 0 → 0 | 0 | extends 13 (every explore view extends a base) |
| 9 | [adtribute/looker-maestroqa](https://github.com/adtribute/looker-maestroqa) @ `0cc93cb` (2020-11-04) | vendor block | 3 | 34 | 34 → 34 | 34 → 34 | 0 → 0 | 0 | none |
| 10 | [joon-solutions/Felix-the-field-agent](https://github.com/joon-solutions/Felix-the-field-agent) @ `5262026` (2025-05-30) | consultancy | 1 | 18 | 16 → 16 | 15 → 17 | 2 → 0 | 0 | extends 1 · reference `;` quirk 1 |
| 11 | [4mile/looker_bqml-staging](https://github.com/4mile/looker_bqml-staging) @ `4c2f0ed` (2022-10-18) | consultancy | 1 | 16 | 16 → 16 | 9 → 9 | 0 → 0 | 0 | extends 7 |
| 12 | [bytecodeio/looker-snowflake-sample](https://github.com/bytecodeio/looker-snowflake-sample) @ `0a9c5e6` (2021-08-24) | consultancy | 1 | 7 | 7 → 7 | 6 → 6 | 0 → 0 | 0 | extends 1 |
| 13 | [Ruthmcel/Publictest](https://github.com/Ruthmcel/Publictest) @ `4db16fd` (2019-07-12) | individual (560 files, 17 models) | 17 | 333 | 333 → 333 | 328 → 328 | 0 → 0 | 0 | duplicate field names 5 |
| 14 | [jimosullivan1099/hmis_csv](https://github.com/jimosullivan1099/hmis_csv) @ `cefaa27` (2021-10-07) | individual | 2 | 39 | 39 → 39 | 10 → **39** | **29 → 0** | 0 | none |
| 15 | [eferreria/ca_detection](https://github.com/eferreria/ca_detection) @ `d32280c` (2025-07-10) | individual | 3 | 57 | 56 → 57 | 52 → 56 | 6 → 0 | 0 | extends 1 |
| 16 | [antfido/thc_looker](https://github.com/antfido/thc_looker) @ `41bbd82` (2026-05-31) | individual | 1 | 4 | 4 → 4 | 1 → 4 | 9 → 0 | 0 | none |
| 17 | [ludovicapierdom24/stellantis_welding_poc](https://github.com/ludovicapierdom24/stellantis_welding_poc) @ `f844d6f` (2026-06-30) | individual | 1 | 10 | 10 → 10 | 4 → 10 | 7 → 0 | 0 | none |
| 18 | [Pieter-devries/youtube_analytics](https://github.com/Pieter-devries/youtube_analytics) @ `85d3dcd` (2026-04-27) | individual | 7 | 36 | 35 → 36 | 35 → 35 | 1 → 0 | 0 | extends 1 |
| | **Total** | | **108** | **3,051** | **2,939 → 2,979** | **2,711 → 2,922** | **211 → 0** | **0** | 132 (extends 124 · dup. fields 5 · reference `;` quirk 3) |

Repositories with refinements: rows 1, 2, 6 (explore refinements only), 10, 12 (explore), 14–18.
Regression controls (no refinements): rows 3, 4, 5, 7, 8, 9, 11, 13.

## 4. The 132 residual mismatches — none is a refinement defect

| Class | n | Repositories | What it is | Before/after |
|---|--:|---|---|---|
| `extends` | 124 | Mozilla spoke-default 42, spoke-temporary-default 14, BC Gov 44, Qubit 13, 4 Mile 7, five singles | The explore view `extends:` another view. The reference parser flattens the parent's `sql_table_name`/fields into the child; OpenMetadata deliberately keeps `extends` as a view→view lineage edge and resolves the child's own body only. Same class as `e01`–`e03` in the conformance suite; expected failures for this tool, to be marked `xfail` in OM-4. | identical |
| duplicate field names | 5 | Ruthmcel/Publictest (`sales` ×4 models, `ar_transaction_status`) | The source view declares the same field name more than once (`filled`, `last_filled`, `reportable_sales`, `returned`, `rx_autofill_enable`, `sold`, `will_call_arrival` in `sales.view.lkml`) — a LookML validation error. The reference keys fields by name within each type, so a repeat within a type collapses to one; OpenMetadata keeps every declaration as a list entry. The *sets* of field names are identical in both directions. | identical |
| reference `;` quirk | 3 | Mozilla `search.search_funnel_forecasts`, `firefox_accounts.auth_entrypoint_conversion`; Joon `parsed_query` | The `sql:` block contains a lone `;` (inside a SQL comment or a JS UDF). `node-lookml-parser` 9.1.0 returns the block with `;,` in place of `;` (verified on a 6-line fixture, independent of `strings`/`modelAssembly` options). **OpenMetadata's text is the faithful one.** Logged as a reference-parser deviation in the suite's `STATUS.md`; verify against the parser's tokenizer before raising it with its maintainer. | identical |

Mozilla spoke-default example of the `extends` class: `accounts_backend/views/events_stream_with_extras.view.lkml`
(`view: events_stream_with_extras { extends: [events_stream_table] … }` over the hub's
`//looker-hub/accounts_backend/views/events_stream_table.view.lkml`) — the reference reports the
parent's table `mozdata.accounts_backend.events_stream` and 108 fields; OpenMetadata reports the
child's 5 own fields and no table, before and after.

## 5. What this does and does not show

- **Shows:** on independent, production LookML (Mozilla, Mattermost, BC Government, four
  consultancies, two vendor blocks, six individuals) the two patches remove every phantom data
  model (211), add 211 correct field lists and 40 correct upstream tables, and break nothing. The
  Mozilla hub-and-spoke layout — cross-project includes (`//looker-hub/...`) refined per spoke — is
  exactly the pattern the fix targets, and it is the largest refinement corpus on public GitHub.
- **Does not show:** behaviour on private estates (most enterprise LookML is private; see
  `scout/` caveats), DataHub/Dagster/Metaphor behaviour (separate adapters, not yet run on this
  corpus), or Looker's own ground truth — the reference is `node-lookml-parser`, which the suite's
  `STATUS.md` records as deviating from the Looker docs on four documented cases. For the
  before/after claim this does not matter (both OpenMetadata variants are compared to the same
  reference and the regression count is 0); for absolute-correctness claims it does.
- **Not claimed:** nothing about Looker itself, nothing about user impact (no deployment data),
  nothing about these organisations endorsing the fix. They have not been contacted.

## 6. Reproduce

```bash
# 1. clone OpenMetadata at ee588e9c77; copy baseline bulk_parser.py to harness/old_bulk_parser.py
# 2. reference parser
mkdir -p ~/work/oracle && (cd ~/work/oracle && npm i lookml-parser@9.1.0)
# 3. corpus: clone the 18 repositories (+ 3 imported projects) listed in differential_2026-10-08/commits.txt at those commits into ~/work/corpus/<owner>__<repo>
# 4. run
bash differential_2026-10-08/run_corpus.sh            # prepares ~/work/corpus_runs/<name>/ and writes results/<name>.json
python3 differential_2026-10-08/summarize_corpus.py ~/work/corpus_runs/results --md summary.md
python3 differential_2026-10-08/classify_residuals.py ~/work/corpus_runs/results
```

Files in `differential_2026-10-08/`: one JSON per repository (full per-view mismatch records, phantom
lists, parse times), `commits.txt`, `run_log.txt`, `summary.md` (first-pass classes; superseded by
`classify_residuals.py` for the `constant` class, which over-fired on identical liquid strings),
`run_corpus.sh`, `summarize_corpus.py`, `classify_residuals.py`.

## 7. Follow-ups

- Reference `;` quirk: fixed in `fabio-looker/node-lookml-parser` PR #43 (commit `d63578c`, 2026-10-12) and covered by suite case `p01_single_semicolon_inside_sql_block`.
- Multi-tool corpus run: run the `DataHub` and `Dagster` adapters (`src/lookml_conformance/adapters/`) across the same 18 prepared run directories.
