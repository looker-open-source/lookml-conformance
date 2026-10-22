# Confirming the provisional cases on Looker

Eight cases are provisional: the Looker documentation does not settle their behavior, so their
expectations are pinned to a public source instead. This procedure checks each of them on a Looker
instance once, and keeps the evidence.

The [Looker adapter](looker-adapter.md) does the work. Its verdicts are a first pass; the
evidence for a case is Looker's own output, which the adapter saves: the commit Looker was on, the
validator response and the generated SQL. Stage 1 proves that the setup reads the files it pushes
before any provisional result is trusted.

| Case | Open question |
| --- | --- |
| r06 | Does a refinement apply when the model includes it before the base view? |
| r10 | After `final: yes`, does Looker still resolve the view, and to which table? |
| r12 | Does a refinement of a view that does not exist create a view? |
| i01 | In which order do files matched by one wildcard apply? |
| i02 | Where do a nested include's declarations land in the include order? |
| i03 | Does including a file a second time move it to the later position? |
| i08 | What happens with files that include each other? |
| e01 | Does a view that extends a refined view inherit the refinement? |

Five variant projects go with them (`scripts/s4/make_variants.py`): one negative control and four
projects that each answer a second question the base case cannot.

## Before you start

Complete the one-time setup in [looker-adapter.md](looker-adapter.md#one-time-setup) and export the
variables listed under [Run](looker-adapter.md#run). Then, in this repository:

```bash
pip install -e .
EVIDENCE=results/looker/$(date +%F)
mkdir -p $EVIDENCE
export LOOKER_DUMP=$EVIDENCE/dump
python scripts/s4/make_variants.py $EVIDENCE/variants
LOOKER="python -m lookml_conformance.adapters.looker"
```

## Stage 1: prove the setup

Do not continue past a step that fails.

**1.1 A confirmed case.** r04 is settled by the documentation: the file included last wins, and
the model includes `b` then `a`.

```bash
lookml-conformance run --command "$LOOKER" --name looker --jobs 1 --only r04_
grep -i "from" $LOOKER_DUMP/r04_later_include_wins/sql__m__orders__orders.sql
```

Pass: the verdict is `pass` and the SQL reads `FROM from_a AS orders`.

**1.2 The negative control.** The same project with the two includes swapped must give the other
table. This shows the result follows the pushed files, not a cache or an earlier case.

```bash
$LOOKER $EVIDENCE/variants/s4-r04-swapped > $EVIDENCE/control.jsonl
grep -i "from" $LOOKER_DUMP/s4-r04-swapped/sql__m__orders__orders.sql
```

Pass: `FROM from_b AS orders`.

**1.3 The commit.** The commit Looker reported is the one pushed:

```bash
cat $LOOKER_DUMP/s4-r04-swapped/commit.txt
git -C $LOOKER_REPO rev-parse HEAD
```

Pass: the two hashes are equal.

**1.4 The Looker UI agrees with the API.** In Looker, with Development Mode on, open the project
`lookml_check`. It is on the branch `lookml-conformance` with the files of `s4-r04-swapped`. Explore
`orders` (model `m`), select the `Id` dimension, and open the **SQL** tab without running the query.

Pass: the SQL tab shows `FROM from_b AS orders`, as in the saved SQL file.

Write the four results in `$EVIDENCE/NOTES.md` (template below).

## Stage 2: run the cases and the variants

Run the whole suite, not only the provisional cases: a confirmed case that fails on Looker for a
reason other than an unobservable key (see Stage 3) is a finding too.

```bash
lookml-conformance run --command "$LOOKER" --name looker --jobs 1 \
  --json $EVIDENCE/scorecard.json --markdown $EVIDENCE/scorecard.md
$LOOKER $EVIDENCE/variants/s4-r10b $EVIDENCE/variants/s4-r12b \
  $EVIDENCE/variants/s4-i01b $EVIDENCE/variants/s4-e01b > $EVIDENCE/variants.jsonl
```

`run` exits with status 1 when any case fails. Some confirmed cases may fail on Looker; Stage 3
says how to read them. It takes about 10 to 20 minutes.

## Stage 3: read the evidence

For each case, read the files named below in `$LOOKER_DUMP/<case id>/`, not only the verdict. Every
case dump has `commit.txt` and `validation.json`; check that `validation.json` has no message you
cannot explain.

The adapter declares what the API cannot show, so those cases are N/A rather than failures: r11
(`derived_table.datagroup_trigger`) and the imported-project cases (i05, i06, i07).

Cases with `order_variants` run once per layout. Read the dump of the layout as written,
`$LOOKER_DUMP/<case id>/`; the exchanged layouts, `$LOOKER_DUMP/<case id>.exchange-<n>/`, must give
the same answer, and a difference means the setup or Looker depends on file names.

| Case | Read | Expectation holds if | Otherwise |
| --- | --- | --- | --- |
| r06 | `sql__m__orders__orders.sql`; warnings in `validation.json` | `FROM refined AS orders` | `raw.orders`: the refinement does not apply when included before its base. Expect `raw.orders`. |
| r10 | `validation.json` first, then `sql__m__orders__orders.sql` | An error about the refinement after `final: yes`, and either `FROM a.final AS orders` or a rejected explore (the verdict passes with `accepted for a project Looker rejects: ... Looker rejected explore orders`). Record which: a rejected explore means tools should report an error, and the case can then assert that. | `b.later`: the later refinement applies despite the error, and the rule is wrong. |
| s4-r10b | `validation.json`, `sql__m__orders__orders.sql` | No error, `FROM a.final AS orders` | An error means `final: yes` also rejects refinements applied before it. |
| r12 | `sql__m__orders__orders.sql`, `validation.json` | `FROM raw.orders AS orders`. Record whether the validator reports an error, a warning or nothing for `+ghost`. | A different table means the stray refinement affects other views. |
| s4-r12b | `validation.json`; `explore__m__ghost.json` if it exists | Looker rejects `explore: ghost` | If the explore loads and `sql__m__ghost__ghost.sql` reads `FROM x.y`, a refinement can create a view and the rule is wrong. |
| i01 | `sql__m__orders__orders.sql` | `FROM from_b AS orders` | `from_a`: files do not apply in lexical path order. |
| s4-i01b | `sql__m__orders__orders.sql` | Either answer is a result | `from_a`: byte order (`B_r` sorts before `a_r`). `from_b`: case-insensitive order. The case's rule says "lexical"; this says which. |
| i02 | `sql__m1__orders__orders.sql`, `sql__m2__orders__orders.sql` | `m1` reads `FROM a`, `m2` reads `FROM c` | `m1` reading `b`: a nested include lands after the including file's own declarations, as node-lookml-parser does, and the DataHub fixture is wrong. |
| i03 | `sql__m__orders__orders.sql` | `FROM a AS orders` | `b`: a second include moves the file to the later position. |
| i08 | `validation.json`, `sql__m__orders__orders.sql` | `FROM b AS orders`. Record any message about the include cycle. | `raw.orders`: the refinement in the cycle is dropped. A rejected explore: Looker refuses the cycle. |
| e01 | `sql__main__orders_ext__orders_ext.sql`, `explore__main__orders_ext.json` | `FROM analytics.orders_clean AS orders_ext`, and fields `extra` and `id` in the explore. | `raw.orders`: `extends` copies the view before refinements apply. |
| s4-e01b | `sql__main__orders_ext__orders_ext.sql` | Either answer is a result | `analytics.orders_clean`: the refinement reaches the extending view even when included after it. `raw.orders`: include position matters. |

## Stage 4: record

Keep `$EVIDENCE` in the repository: the scorecard, the dumps, the variants' output and
`NOTES.md`. The dumps hold the instance's host name and the project and connection names; nothing
else about the instance.

`NOTES.md` template:

```markdown
# Looker check, <date>

- Looker version: <from scorecard.md or the adapter output>
- Edition: Looker (Google Cloud core) trial, BigQuery connection
- Adapter commit: <git rev-parse HEAD of this repository>

## Stage 1

| Step | Result |
| --- | --- |
| 1.1 r04 | pass, FROM from_a |
| 1.2 control | FROM from_b |
| 1.3 commit | equal |
| 1.4 UI | SQL tab matches |

## Cases

### r06
- SQL: `FROM ... AS orders` (dump/r06_refinement_included_before_its_base/sql__m__orders__orders.sql)
- Validator: <messages, verbatim, or none>
- Conclusion: expectation holds / changes to <...>

<one section per case and variant>
```

### Update the cases

For each provisional case, from its section in `NOTES.md`
([case format](case-format.md#status-and-basis)):

1. If Looker resolved the project differently from the expectation, change `expect` to what Looker
   did, and the `title` and `rule` if they no longer describe it.
2. Set `"status": "confirmed"` and `"basis": ["observation"]`, delete the `provisional` block, and
   add the observation:

   ```json
   "observations": [
     {
       "looker_version": "<version>",
       "date": "<YYYY-MM-DD>",
       "finding": "<what Looker resolved, and any validator message that matters>",
       "evidence": "results/looker/<YYYY-MM-DD>/dump/<case id>"
     }
   ]
   ```

3. If Looker gave no result the expectation can hold (for example, it rejected the explore in
   i08), leave the case provisional, record the finding in `NOTES.md`, and decide what the case
   should assert before changing it. r10 accepts a rejected explore, since the case is marked
   `invalid_in_looker`.

The variants are not cases. Their findings go in `NOTES.md` and can sharpen a case's rule, for
example i01's "lexical path order" once s4-i01b shows which order Looker uses.

Then regenerate and rescore, since expectations may have changed:

```bash
lookml-conformance validate
lookml-conformance catalog
lookml-conformance run --json results/latest.json --markdown results/latest.md
lookml-conformance site
```

Update the results table in `README.md` from `results/latest.md`.

## What this establishes

- What one Looker version did with each case, with the commit, the validator output and the
  generated SQL to show it.
- It does not establish that later versions behave the same. Looker's undocumented behavior can
  change; the check can be repeated with the same commands.
- The SQL is in the BigQuery dialect. The cases compare table names, which the dialect does not
  change.
