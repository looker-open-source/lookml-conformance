# The Looker adapter

**Not yet run on a Looker instance.** Treat its results as unverified until Stage 1 of
[the procedure](confirming-provisional-cases.md#stage-1-prove-the-setup) passes on a real instance.

The Looker adapter resolves each case on a real Looker instance through the Looker API, so the
scorecard shows what Looker itself does. It is how provisional cases are checked; the procedure for
that is [confirming-provisional-cases.md](confirming-provisional-cases.md). Nothing runs on the
database: the adapter reads explore metadata and the SQL Looker generates.

The adapter has unit tests against a simulated API (`tests/adapters/test_looker.py`). Its first runs
on a real instance must be checked as described in the procedure before its verdicts are trusted.

## What it does for each case

1. **Stage the files.** In the local clone given as `LOOKER_REPO`, it checks out the branch
   `LOOKER_BRANCH` (default `lookml-conformance`), deletes every file except `.git`, copies in the
   case's `project/`, edits the model files (see below), commits, force-pushes, and keeps the
   commit hash.
2. **Put Looker on that commit.** It switches the API session to the development workspace
   (`PATCH /session`), checks out the branch in the Looker project (`PUT` or `POST
   /projects/{id}/git_branch`), resets it to the remote (`POST /projects/{id}/reset_to_remote`) and
   reads the branch back (`GET /projects/{id}/git_branch`). If Looker does not report the pushed
   commit after four attempts, the case is an adapter error. A case is never scored against other
   files.
3. **Configure models.** For each model file in the case, if Looker has no model of that name it
   creates one for the project with all connections allowed (`POST /lookml_models`). A model of
   that name in another project is an error.
4. **Validate.** It runs the LookML validator (`POST /projects/{id}/validate`) and reports each
   message as one line of the output's `errors`. Validator messages never change a verdict.
5. **Read the result.** For each model it lists the explores (`GET /lookml_models/{model}`), reads
   each explore's metadata (`GET /lookml_models/{model}/explores/{name}`), and for each view in the
   explore asks for the SQL of a one-field query (`POST /queries/run/sql`). The SQL is generated,
   not run.
6. **Report.** It converts what Looker returned into the adapter protocol; the judge compares that
   with `case.json` as for any other tool.

Runs are serialized: a lock file in the repository's `.git` directory stops two adapter processes
from using the branch at once, and the runner should be given `--jobs 1`.

### Changes to the case files

The pushed copy differs from the case in two ways only:

- **Connection.** Every `connection: "..."` in a model file becomes `connection: "<LOOKER_CONNECTION>"`.
- **Probe explores.** Looker exposes a view only through an explore. For each view the project
  defines (`view: name {`) that a model file names in no `explore:`, `view_name:`, `from:` or
  `join:`, the adapter appends `explore: lc_probe__<view> { from: <view> }` to that model. Probe
  explores are read last, are not reported as explores, and validator messages that mention them
  are dropped. Probes are added in e02, e03, e04 and l01 to l05. **No provisional case gets a
  probe**, so for those the connection line is the only change.

### Where each reported value comes from

| Value | Source | Interpretation by the adapter |
| --- | --- | --- |
| `sql_table_name` | The generated SQL: the FROM or JOIN item whose alias is the view, with backticks and double quotes removed. If the view has no field to query, the explore metadata's `sql_table_name` with ` AS <alias>` removed. | A SQL scanner written for this adapter |
| `derived_table.sql` | The body of the WITH clause entry or subquery the view's alias refers to, whitespace collapsed | Same scanner |
| lineage (`upstream`) | Every table after FROM or JOIN in that body, following WITH clause entries and subqueries | Same scanner |
| fields, field `sql`, `type`, `label` | Explore metadata; `label` is Looker's `label_short` | None |
| dimension groups | Member fields regrouped: timeframes from the name suffixes, label from `field_group_label`, type `time` for `date_*` members and `duration` for `duration_*` | A mapping written for this adapter |
| measure `filters` | Explore metadata, with a `view.` prefix removed from field names | Small |
| explore `view_name`, `label`, joins | Explore metadata | None |
| explore `from` | Inferred: when the base view's alias is the explore name and the metadata's `view_name` differs, `from` is that `view_name` | An inference |
| `extends`, `derived_table` parameters other than `sql` | Not exposed by the API; reported as unknown | The adapter declares `derived_table_params: false`, so r11 is N/A. No case asserts `extends`. |
| exposed views (`absent_views`) | The views reported through explores. A view with no explore cannot appear. | None |

When Looker refuses an explore (for example because of a LookML error), the view of that name is
reported as an error carrying Looker's message (`Looker rejected explore orders: ...`), so the
verdict says so instead of "view not resolved". When Looker lists no explores for a model, the
output's `errors` says so.

### Assumptions not yet observed on an instance

These follow from the Looker API reference and are checked by the first steps of the procedure:

1. Creating the branch and calling `reset_to_remote` makes Looker fetch the pushed commit. If not,
   step 2 fails with an error; it cannot pass silently.
2. Explore metadata and generated SQL reflect the files checked out in the development workspace.
3. For BigQuery, Looker writes derived tables as WITH clause entries. The scanner also handles
   subqueries in FROM.
4. The meanings of `view_name` for an explore with `from`, of `field_group_label`, and of the
   field names in measure filters.

### Raw output

With `LOOKER_DUMP` set, the adapter writes, per case, to `<dump>/<case id>/`:

| File | Contents |
| --- | --- |
| `commit.txt` | The commit that was pushed and that Looker reported |
| `validation.json` | The validator response, unfiltered |
| `model__<model>.json` | The model, with its list of explores |
| `explore__<model>__<explore>.json` | The explore metadata |
| `sql__<model>__<explore>__<alias>.sql` | The generated SQL for one view |

These files, not the adapter's parsed values, are the evidence for a case.

Imported projects need a second Looker project and are not supported yet; i05, i06 and i07 are
scored N/A.

## One-time setup

You need a Looker instance on which you are an admin. These steps create a trial Looker (Google
Cloud core) instance. The trial converts to a paid Standard instance when it ends, so delete it
when you are done (last section).

### 1. Google Cloud project

In Cloud Shell (console.cloud.google.com, the `>_` icon):

```bash
gcloud projects create lookml-check-$RANDOM --set-as-default
PROJECT=$(gcloud config get-value project)
gcloud billing accounts list
gcloud billing projects link $PROJECT --billing-account=<BILLING_ACCOUNT_ID>
gcloud services enable looker.googleapis.com servicenetworking.googleapis.com bigquery.googleapis.com
```

### 2. OAuth client

In the console:

1. **APIs & Services > OAuth consent screen**: user type **External**, any app name, your email as
   the support email and as a test user.
2. **APIs & Services > Credentials > Create credentials > OAuth client ID**: type
   **Web application**, name `looker`, no redirect URIs yet. Copy the client ID and secret.

### 3. Instance

```bash
gcloud looker instances create lookml-check \
  --region=us-central1 \
  --edition=core-trial \
  --oauth-client-id=<CLIENT_ID> \
  --oauth-client-secret=<CLIENT_SECRET> \
  --async
gcloud looker instances describe lookml-check --region=us-central1 --format='value(state,lookerUri)'
```

If `core-trial` is rejected, use `core-trial-standard`. Creation takes about an hour. When the
state is `ACTIVE`, add `<lookerUri>/oauth2callback` under **Authorized redirect URIs** of the OAuth
client and save. That can take from minutes to a few hours to apply. Then open `<lookerUri>` and
sign in with Google; you are the admin.

### 4. BigQuery connection

No query runs, but Looker needs a working connection to generate SQL. An empty dataset is enough:

```bash
bq --project_id=$PROJECT mk --dataset --location=US lookml_check
PNUM=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
SA="serviceAccount:service-${PNUM}@gcp-sa-looker.iam.gserviceaccount.com"
for ROLE in roles/serviceusage.serviceUsageConsumer roles/bigquery.jobUser roles/bigquery.dataEditor; do
  gcloud projects add-iam-policy-binding $PROJECT --member="$SA" --role="$ROLE" --condition=None
done
```

In Looker, **Admin > Database > Connections > Default BigQuery Connection** (or **Review
connection** on the Home page): billing and storage project are your project ID, primary dataset
`lookml_check`, authentication Application Default Credentials. Save, then **Test**. Note the
connection name exactly as shown.

### 5. Git repository and Looker project

1. Create an empty private GitHub repository, for example `lookml-looker-check`, and clone it with
   one commit on `main`:

   ```bash
   git clone git@github.com:<you>/lookml-looker-check.git ~/lookml-looker-check
   cd ~/lookml-looker-check && echo "Scratch repo for the lookml-conformance Looker adapter." > README.md
   git add README.md && git commit -m "Init" && git push -u origin main
   ```

2. In Looker, turn on **Development Mode**, then **Develop > Projects > New LookML Project**:
   **Blank Project**, named `lookml_check`.
3. In the project, **Configure Git** with `git@github.com:<you>/lookml-looker-check.git`. Add the
   deploy key Looker shows to the GitHub repository (**Settings > Deploy keys**) and tick
   **Allow write access**.

### 6. API key

**Admin > Users >** your user **> Edit Keys > New API Key**. Copy the client ID and secret.

## Run

```bash
pip install -e .          # in this repository, any Python 3.10+

export LOOKERSDK_BASE_URL=https://<uuid>.looker.app
export LOOKERSDK_CLIENT_ID=<api client id>
export LOOKERSDK_CLIENT_SECRET=<api client secret>
export LOOKER_PROJECT=lookml_check
export LOOKER_REPO=~/lookml-looker-check
export LOOKER_CONNECTION="<connection name>"
export LOOKER_DUMP=looker-dump            # optional: raw API responses per case

lookml-conformance run --command "python -m lookml_conformance.adapters.looker" --name looker \
  --jobs 1 --json results/looker.json --markdown results/looker.md
```

Each case takes a few seconds to half a minute. `--only TEXT` runs the cases whose id contains
`TEXT`. To resolve one project and print the adapter's output directly:

```bash
python -m lookml_conformance.adapters.looker cases/refinements/r04_later_include_wins/project
```

## Clean up

```bash
gcloud looker instances delete lookml-check --region=us-central1
gcloud projects delete $PROJECT      # optional
```
