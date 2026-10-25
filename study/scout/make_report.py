#!/usr/bin/env python3
"""Join pool.json + measured.json -> candidates.json + CANDIDATES.md."""
import json, os, re, collections, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
pool = {r["id"]: r for r in json.load(open(os.path.join(ROOT, "pool.json")))}
measured = json.load(open(os.path.join(ROOT, "measured.json")))
overlap = json.load(open(os.path.join(ROOT, "google_overlap.json")))
log = [l.rstrip("\n").split("\t") for l in open(os.path.join(ROOT, "_search", "search_log.tsv")) if not l.startswith("utc_time")]
SYNTHETIC = {"dhruvingandhi/sample-large-project": "synthetic generated stress project (group_NN explores/models/views, 20k files, 4000 refinements)",
             "markwopata/si-agents-t3os": "agent monorepo; 540 generated model files under .analytics-curated/looker/"}
DERIVATIVE = {"jenny-cai/mozilla-test-spoke": "personal copy of mozilla/looker-spoke-default (imports looker-hub)"}
def google_copy(o):
    return (o["file_containment"] >= 0.6 and o["shared_files"] >= 3) or (o["view_containment"] >= 0.6 and o["shared_views"] >= 3) \
        or (o["file_containment"] >= 0.9 and o["view_containment"] >= 0.9 and o["shared_files"] >= 2)

# --- curated knowledge (owner -> category) ------------------------------------------------------
OWNER_CAT = {
    "mozilla": "non-profit (Mozilla)", "mozilla-mobile": "non-profit (Mozilla)", "bcgov": "government (BC Gov, Canada)",
    "mattermost": "enterprise (Mattermost)", "orica-it-enterprise": "enterprise (Orica)", "QubitProducts": "vendor block (Qubit)",
    "pipeline-looker-blocks": "vendor blocks (Pipeline)", "heap": "vendor block (Heap)", "fivetran": "vendor (Fivetran)",
    "snowplow": "vendor block (Snowplow)", "snowplow-archive": "vendor block (Snowplow, archived)", "rudderlabs": "vendor (RudderStack)",
    "rittmananalytics": "consultancy (Rittman Analytics)", "teamdatatonic": "consultancy (Datatonic)", "joon-solutions": "consultancy (Joon Solutions)",
    "bytecodeio": "consultancy (Bytecode IO)", "4mile": "consultancy (4 Mile Analytics)", "badal-io": "consultancy (Badal)",
    "66degrees": "consultancy (66degrees)", "Mashey": "consultancy (Mashey)", "onesecondbefore": "consultancy (Onesecondbefore)",
    "TasmanAnalytics": "consultancy (Tasman)", "precocity": "consultancy (Precocity)", "Hashpath": "consultancy (Hashpath)",
    "spectacles-ci": "tool vendor demo (Spectacles)", "spectacles-external": "tool vendor demo (Spectacles)",
    "monte-carlo-data": "vendor block (Monte Carlo)", "corelight": "vendor block (Corelight)", "cedar-team": "enterprise (Cedar)",
    "dataminr": "enterprise (Dataminr)", "adtribute": "vendor block (Adtribute/MaestroQA)", "EffinAmazing": "consultancy (Effin Amazing)",
    "Cold-Bore-Capital": "consultancy (Cold Bore Capital)", "doitintl": "vendor (DoiT)", "pendo-io": "vendor block (Pendo)",
    "memsql": "vendor (SingleStore)", "dbt-labs": "vendor (dbt Labs)", "Zenlytic": "tool vendor (Zenlytic)", "hex-inc": "tool vendor (Hex)",
    "interviewstreet": "enterprise (HackerRank)", "topcoder-archive": "enterprise (Topcoder, archived)", "CommentSold": "enterprise (CommentSold)",
    "elementus-io": "enterprise (Elementus)", "beep-saude": "enterprise (Beep Saude)", "tridorian": "consultancy (Tridorian)",
    "infinitelambda": "consultancy (Infinite Lambda)", "Hiflylabs": "consultancy (Hiflylabs)", "Jumbleberry": "enterprise (Jumbleberry)",
    "Cimpress-MCP": "enterprise (Cimpress)", "trifacta": "vendor (Trifacta)", "metriql": "tool vendor (metriql)", "cloudgenera": "vendor (CloudGenera)",
    "GLocation-SAS": "vendor (GLocation)", "SureSkills": "consultancy (SureSkills)", "CobryDev": "consultancy (Cobry)", "glewio": "vendor (Glew)",
}
TOOL_FIXTURES = {  # parser/tool repos or copies of their test resources (not corpus)
    "joshtemple/lkml": "lkml parser (tests/resources)", "Ladvien/rust_lookml_parser": "Rust parser; vendors joshtemple/lkml test resources",
    "autocode07/joshtemple__lkml.4c03bd22": "copy of joshtemple/lkml", "Zenlytic/lookml-zenml": "LookML->ZenML translator; example LookML only",
    "ContrastingSounds/lookml-sublime-syntax": "editor syntax package; sample LookML", "hex-inc/hex-skills": "LLM skill docs with example LookML",
    "Ladvien/vscode-looker": "editor extension", "sgoley/LookML-Syntax-Highlighter": "editor extension", "remisalmon/nanorc": "editor syntax",
    "alison985/awesome-looker": "link list", "iamaziz/lookml_visualizer": "visualiser tool", "Cimpress-MCP/j2v": "generator tool",
    "metriql/metriql-lookml": "metriql integration (generated)", "nick-at/looker-cooker": "export tool", "jkelleman/semantic-metrics-modeling-assistant": "MCP agent",
    "spectacles-ci/tldd": "tool", "Zenlytic/metrics_layer": "metrics layer tool", "infinitelambda/lams_template": "LAMS config template",
    "lkrdev/text-to-lookml-lkml": "generator output stub",
    "G-Schumacher44/strata-oss": "Strata — 'Agentic BI toolkit / deterministic LookML analysis engine' (dead code, lineage); LookML is test fixtures — NB related tool",
}
IMPORT_ALIAS = {  # Looker project name used in include: "//<name>/..." -> repo in corpus
    "looker-hub": "mozilla/looker-hub", "cfms_block": "bcgov/GDX-Analytics-Looker-cfms_block",
    "cmslite_metadata": "bcgov/GDX-Analytics-Looker-CMSLite-Metadata", "snowplow_web_block": "bcgov/GDX-Analytics-Looker-Snowplow-Web-Block",
}
FIXTURE_NAME_PAT = re.compile(r"(parser|lkml$|syntax|highlight|vscode|sublime|zenml|lams|lint|cooker|visualizer|awesome|^lkml)", re.I)
INDIVIDUAL_LOOKER_STAFF_PAT = re.compile(r"looker", re.I)  # e.g. justinlooker, DaveWard-looker: individual Looker-staff sandboxes

def classify(m):
    p = pool.get(m["id"], {})
    reasons = []
    if m["id"] in TOOL_FIXTURES or (p.get("status") == "tool_fixture"):
        return "tool_fixture", [TOOL_FIXTURES.get(m["id"], "known tool")]
    if m["n_model"] >= 100 and m["n_extends"] >= 500:  # joshtemple/lkml test-resource copies
        return "tool_fixture", ["looks like a copy of joshtemple/lkml tests/resources"]
    if m["id"] in SYNTHETIC:
        return "synthetic", [SYNTHETIC[m["id"]]]
    if m["id"] in DERIVATIVE:
        return "derivative_of_corpus_repo", [DERIVATIVE[m["id"]]]
    o = overlap.get(m["id"])
    if o and google_copy(o):
        return "google_block_copy", [f"{o['best_match']}: {o['shared_files']}/{o['n_view_files']} view/explore file names "
                                     f"({o['file_containment']:.0%}) and {o['shared_views']}/{o['n_views']} view names ({o['view_containment']:.0%}) shared"]
    if p.get("status") == "demo_by_name" or m.get("repo_name_demo"):
        reasons.append("repo name/description matches thelook/the_look/faa/healthcare_demo")
    if m["demo_flag_views"]:
        reasons.append("thelook view set present: " + ",".join(m["thelook_view_overlap"]))
    nd, nl = m.get("n_demo_named_files", 0), max(m["n_lkml"], 1)
    if nd and (nd / nl >= 0.3 or nl <= 5):
        reasons.append(f"demo-named files {nd}/{nl}: " + ",".join(m["demo_name_hits"]))
    if reasons:
        return "demo_copy", reasons
    if m["n_lkml"] == 0:
        return "no_lkml", ["no *.lkml files in clone (legacy .lookml=%d)" % m["n_legacy_lookml"]]
    if not m["has_model_file"]:
        return "no_model", ["no *.model.lkml"]
    if not m["has_refinement_or_extends"]:
        return "no_refinement_or_extends", []
    notes = []
    if nd:
        notes.append(f"contains {nd} demo-named file(s) ({','.join(m['demo_name_hits'])}) among {nl} — mixed")
    if o and o["best_match"] and (o["shared_files"] >= 3 or o["shared_views"] >= 3):
        notes.append(f"partial overlap with {o['best_match']}: {o['shared_files']} files/{o['shared_views']} views")
    return "candidate", notes

rows = []
for m in measured:
    p = pool.get(m["id"], {})
    cls, why = classify(m)
    owner = m["id"].split("/")[0]
    cat = OWNER_CAT.get(owner)
    if cat is None:
        cat = "organization (uncategorised)" if p.get("owner_type") == "Organization" else "individual"
        if p.get("owner_type") != "Organization" and INDIVIDUAL_LOOKER_STAFF_PAT.search(owner):
            cat = "individual (Looker-staff handle?)"
    r = collections.OrderedDict()
    r.update({"id": m["id"], "url": p.get("url", "https://github.com/" + m["id"]), "owner": owner, "owner_type": p.get("owner_type"),
              "owner_category": cat, "stars": p.get("stars", 0), "license": p.get("license"), "description": p.get("description", ""),
              "pushed_at": p.get("pushed_at"), "created_at": p.get("created_at"), "api_size_kb": p.get("size_kb"),
              "search_hits": p.get("search_hits", []), "classification": cls, "classification_reasons": why})
    for k, v in m.items():
        if k not in ("id", "clone_dir"):
            r[k] = v
    r["clone_dir"] = m["clone_dir"]
    rows.append(r)

# --- ranking -------------------------------------------------------------------------------------
corpus_names = {r["id"].split("/")[1].lower() for r in rows}
corpus_ids = {r["id"] for r in rows}
def tier(r):
    c = r["owner_category"]
    if c.startswith("individual"):
        return 3
    if "demo" in c:
        return 2
    return 1 if r["owner_type"] == "Organization" else 3
cands = [r for r in rows if r["classification"] == "candidate"]
for r in rows:
    o = overlap.get(r["id"]) or {}
    r["google_overlap_best"] = o.get("best_match")
    r["google_overlap_file_containment"] = o.get("file_containment", 0.0)
    r["google_overlap_view_containment"] = o.get("view_containment", 0.0)
for r in cands:
    r["tier"] = tier(r)
    r["imports_resolvable_in_corpus"] = [f"{x}→{IMPORT_ALIAS[x]}" for x in r["imported_projects"] if x in IMPORT_ALIAS and IMPORT_ALIAS[x] in corpus_ids]
    r["imports_unresolved"] = [x for x in r["imported_projects"] if not (x in IMPORT_ALIAS and IMPORT_ALIAS[x] in corpus_ids)]
    r["score"] = round(3 * min(r["n_refinements"], 100) + min(r["n_extends"], 100) + min(r["n_lkml"], 500) / 10 + 5 * min(r["n_model"], 10), 1)
cands.sort(key=lambda r: (r["tier"], -r["score"]))
for i, r in enumerate(cands, 1):
    r["rank"] = i

json.dump(rows, open(os.path.join(ROOT, "candidates.json"), "w"), indent=1)

# --- markdown ------------------------------------------------------------------------------------
def esc(s): return (s or "").replace("|", "\\|").replace("\n", " ")
def short(r): return f"[{r['id']}]({r['url']})"
L = []
L.append(f"# Non-Google LookML corpus candidates\n\nGenerated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `make_report.py` from `pool.json` (GitHub search metadata) + `measured.json` (grep/regex measurements of shallow clones under `~/work/corpus/<owner>__<repo>`) + `google_overlap.json` (file/view-name overlap against 219 looker-open-source/llooker LookML repos cloned into `_google_blocks/`). No LookML parser was run.\n")
cnt = collections.Counter(r["classification"] for r in rows)
L.append(f"Pool: {len(pool)} distinct repos returned by the searches; {len(rows)} cloned+measured (every non-excluded repo ≤200 MB API size). Classification counts: " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())) + ".\n")
L.append("Shortlist rule: not a tool fixture / synthetic / Google-block copy / demo copy, ≥1 `*.model.lkml`, ≥1 refinement (`view:/explore: +name`) or `extends:`. Tier 1 = organisation-owned real projects/blocks; Tier 2 = tool-vendor demo projects; Tier 3 = individual sandboxes (ranked last; only the top 15 by score are shown here, the rest are in B). Score = 3·refinements + extends + lkml/10 + 5·models (capped).\n")

L.append("## A. Ranked shortlist\n")
L.append("| # | T | repo | owner category | ★ | lic | last commit | HEAD | lkml | models | views | refine (view/explore) | extends | ext.req | includes | `//` imports | manifest | const | imports resolvable in corpus | unresolved imports | notes |")
L.append("|--:|--|---|---|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:-:|:-:|---|---|---|")
shown_t3 = 0
for r in cands:
    if r["tier"] == 3:
        shown_t3 += 1
        if shown_t3 > 15:
            continue
    L.append(f"| {r['rank']} | {r['tier']} | {short(r)} | {esc(r['owner_category'])} | {r['stars']} | {r['license'] or '-'} | {r['last_commit_date'][:10]} | `{r['head_sha'][:8]}` | {r['n_lkml']} | {r['n_model']} | {r['n_view']} | {r['n_refinements']} ({r['n_view_refinements']}/{r['n_explore_refinements']}) | {r['n_extends']} | {r['n_extension_required']} | {r['n_includes']} | {r['n_includes_imported_project']} | {'y' if r['has_manifest'] else '-'} | {'y' if r['has_constant'] else '-'} | {', '.join(r['imports_resolvable_in_corpus']) or '-'} | {', '.join(r['imports_unresolved']) or '-'} | {esc('; '.join(r['classification_reasons']) or r['description'])[:90]} |")

L.append("\n## B. Full measured table (all cloned repos)\n")
L.append("| repo | class | owner cat | ★ | last commit | HEAD | lkml | model | view | explore | refine | extends | includes | `//` imports | manifest | const | thelook overlap | reasons |")
L.append("|---|---|---|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:-:|:-:|---|---|")
for r in sorted(rows, key=lambda r: (r["classification"] != "candidate", -(r["n_refinements"] + r["n_extends"]), -r["stars"], r["id"])):
    L.append(f"| {short(r)} | {r['classification']} | {esc(r['owner_category'])} | {r['stars']} | {r['last_commit_date'][:10]} | `{r['head_sha'][:8]}` | {r['n_lkml']} | {r['n_model']} | {r['n_view']} | {r['n_explore']} | {r['n_refinements']} | {r['n_extends']} | {r['n_includes']} | {r['n_includes_imported_project']} | {'y' if r['has_manifest'] else '-'} | {'y' if r['has_constant'] else '-'} | {','.join(r['thelook_view_overlap']) or '-'} | {esc('; '.join(r['classification_reasons']))[:90]} |")

L.append("\n## C. Tool fixtures (not corpus)\n")
for r in [x for x in rows if x["classification"] == "tool_fixture"]:
    L.append(f"- {short(r)} — {esc('; '.join(r['classification_reasons']))} (lkml={r['n_lkml']}, models={r['n_model']}, refine={r['n_refinements']}, extends={r['n_extends']})")
L.append("- Not LookML-primary and therefore not returned by `language:LookML` search (known fixture holders, listed for completeness, not cloned): spectacles-ci/spectacles, ww-tech/lookml-tools, datahub-project/datahub (metadata-ingestion/tests/integration/lookml), open-metadata/OpenMetadata, dagster-io/dagster (dagster-looker tests), MetaphorData/connectors, fabio-looker/node-lookml-parser.")

L.append("\n## D. Excluded as demo copies (thelook / the_look / faa / healthcare_demo / Looker demo view sets)\n")
demo = [x for x in rows if x["classification"] == "demo_copy"]
L.append(f"{len(demo)} measured repos. Those that would otherwise qualify (≥1 model and ≥1 refinement/extends) are listed first; the rest are summarised.\n")
L.append("| repo | owner cat | ★ | last commit | lkml | model | refine | extends | reason |")
L.append("|---|---|--:|---|--:|--:|--:|--:|---|")
for r in sorted(demo, key=lambda r: (-(r["has_model_file"] and r["has_refinement_or_extends"]), -(r["n_refinements"] + r["n_extends"]), r["id"])):
    if r["has_model_file"] and r["has_refinement_or_extends"]:
        L.append(f"| {short(r)} | {esc(r['owner_category'])} | {r['stars']} | {r['last_commit_date'][:10]} | {r['n_lkml']} | {r['n_model']} | {r['n_refinements']} | {r['n_extends']} | {esc('; '.join(r['classification_reasons']))[:100]} |")
others = [r["id"] for r in demo if not (r["has_model_file"] and r["has_refinement_or_extends"])]
L.append(f"\nOther demo copies without refinement/extends ({len(others)}): " + ", ".join(others))
unmeasured_demo = sorted(k for k, v in pool.items() if v["status"] == "demo_by_name" and k not in {r["id"] for r in rows})
if unmeasured_demo:
    L.append(f"\nFlagged by name in search results but not cloned ({len(unmeasured_demo)}): " + ", ".join(unmeasured_demo))
gl = collections.Counter(v["owner"] for v in pool.values() if v["status"] == "excluded_google_looker_owner")
L.append(f"\nExcluded Google/Looker-owned repos in search results: {sum(gl.values())} (" + ", ".join(f"{k}={v}" for k, v in gl.most_common(12)) + ").")

L.append("\n## D2. Excluded as copies of looker-open-source / llooker blocks, synthetic, or derivative repos\n")
L.append("Detected by file-name and view-name containment against the 219 LookML repos of looker-open-source + llooker (rule: ≥60 % of view/explore file names or view names shared with one Google repo, ≥3 shared; or ≥90 %/≥90 % with ≥2 shared). Only repos that would otherwise have qualified (≥1 model, ≥1 refinement/extends) are tabulated; the rest are summarised.\n")
L.append("| repo | class | owner cat | ★ | last commit | lkml | model | refine | extends | reason |")
L.append("|---|---|---|--:|---|--:|--:|--:|--:|---|")
gcopy = [x for x in rows if x["classification"] in ("google_block_copy", "synthetic", "derivative_of_corpus_repo")]
for r in sorted(gcopy, key=lambda r: (-(r["has_model_file"] and r["has_refinement_or_extends"]), -(r["n_refinements"] + r["n_extends"]), r["id"])):
    if r["has_model_file"] and r["has_refinement_or_extends"]:
        L.append(f"| {short(r)} | {r['classification']} | {esc(r['owner_category'])} | {r['stars']} | {r['last_commit_date'][:10]} | {r['n_lkml']} | {r['n_model']} | {r['n_refinements']} | {r['n_extends']} | {esc('; '.join(r['classification_reasons']))[:120]} |")
others2 = [r["id"] for r in gcopy if not (r["has_model_file"] and r["has_refinement_or_extends"])]
L.append(f"\nOther Google-block copies without refinement/extends ({len(others2)}): " + ", ".join(others2))

L.append("\n## E. Search queries, timestamps, total_count\n")
L.append("All unauthenticated GitHub REST `search/repositories` calls (8 s sleep between calls; GitHub search omits forks by default, so `fork` exclusion is implicit — no fork appeared in any result). Raw JSON: `~/work/corpus/_search/<file>.json`.\n")
L.append("| UTC time | file | HTTP | total_count | items | query |")
L.append("|---|---|--:|--:|--:|---|")
for l in log:
    if len(l) >= 7:
        L.append(f"| {l[0]} | {l[1]} | {l[2]} | {l[3]} | {l[4]} | `{l[6].replace('https://api.github.com/search/repositories?', '')}` |")
L.append("\nExplicit non-search checks: `git ls-remote` (no API cost) for spectacles-ci/eye-exam, code-dot-org/looker, mattermost/looker, montrealanalytics/looker, das42/looker → all not found/private; `GET /repos/spectacles-ci/eye-exam` (2026-10-08T06:16Z) → HTTP 404 `{\"message\":\"Not Found\"}`; `GET /orgs/looker-open-source/repos` (4 pages, 337 repos) and `GET /orgs/llooker/repos` (1 page, 70 repos) used only to build the Google-block overlap index. `user:montrealanalytics` search returned HTTP 422 (org does not exist under that login).")
open(os.path.join(ROOT, "CANDIDATES.md"), "w").write("\n".join(L) + "\n")
print("candidates:", len(cands), "rows:", len(rows), dict(cnt))
for r in cands[:40]:
    print(f"{r['rank']:3d} T{r['tier']} {r['id'][:46]:46s} {r['owner_category'][:30]:30s} ref={r['n_refinements']:3d} ext={r['n_extends']:3d} mod={r['n_model']:2d} lkml={r['n_lkml']:4d} imp={r['n_includes_imported_project']:3d} {r['last_commit_date'][:10]}")
