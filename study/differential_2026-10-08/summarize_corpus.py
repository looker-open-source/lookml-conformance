#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Summarise the non-Google corpus differential results and classify the remaining mismatches.

Usage: python3 summarize_corpus.py ~/work/corpus_runs/results  [--md out.md]
Classes for mismatches that remain after the fix (mismatches_new):
  extends      the view extends another view (OpenMetadata models extends as a view->view lineage edge
               and does not flatten sql_table_name/fields; the reference parser flattens) -- by design
  constant     the reference substituted a @{constant} / liquid; OpenMetadata keeps the literal
  fields_only  the upstream table matches, only the field list differs
  other        anything else (needs a look)
"""
import json
import re
import sys
from pathlib import Path

res_dir = Path(sys.argv[1]).expanduser()
runs_dir = res_dir.parent
md_out = Path(sys.argv[sys.argv.index("--md") + 1]) if "--md" in sys.argv else None

VIEW_RE_T = r"^\s*view:\s*{name}\s*\{{"


def view_block(repo_dir: Path, name: str) -> str:
    pat = re.compile(VIEW_RE_T.format(name=re.escape(name)))
    for f in repo_dir.rglob("*.lkml"):
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if pat.match(line):
                depth, out = 0, []
                for l in lines[i:]:
                    out.append(l)
                    depth += l.count("{") - l.count("}")
                    if depth <= 0 and len(out) > 1:
                        break
                return "\n".join(out)
    return ""


def classify(repo_dir: Path, mm: dict) -> str:
    ref, new = mm["oracle"], mm["new"]
    block = view_block(repo_dir, mm["view"])
    if re.search(r"^\s*extends:", block, re.M):
        return "extends"
    ref_src = ref.get("sql_table_name") or ref.get("derived_sql") or ""
    new_src = (new or {}).get("sql_table_name") or (new or {}).get("derived_sql") or ""
    if "@{" in new_src or "{%" in new_src or "@{" in block:
        return "constant"
    same_src = ((ref.get("sql_table_name"), ref.get("derived_sql")) ==
                ((new or {}).get("sql_table_name"), (new or {}).get("derived_sql")))
    if same_src:
        return "fields_only"
    return "other"


rows = []
for jf in sorted(res_dir.glob("*.json")):
    try:
        data = json.loads(jf.read_text())
    except json.JSONDecodeError:
        rows.append({"repo": jf.stem, "error": "no/invalid JSON"}); continue
    s = data[0] if isinstance(data, list) else data
    if "oracle_error" in s:
        rows.append({"repo": s["repo"], "error": "oracle: " + s["oracle_error"][:120]}); continue
    repo_dir = runs_dir / s["repo"]
    classes = {}
    examples = {}
    for mm in s.get("mismatches_new", []):
        c = classify(repo_dir, mm)
        classes[c] = classes.get(c, 0) + 1
        examples.setdefault(c, f"{mm['model']}.{mm['view']}: ref={mm['oracle'].get('sql_table_name') or mm['oracle'].get('derived_sql') or None!r} new={(mm['new'] or {}).get('sql_table_name') if mm['new'] else 'unresolved'!r}")
    rows.append({"repo": s["repo"], "models": s["models"], "checked": s["checked"],
                 "table": f"{s['table_match_old']} → {s['table_match_new']}",
                 "fields": f"{s['fields_match_old']} → {s['fields_match_new']}",
                 "phantom": f"{len(s['phantom_views_old'])} → {len(s['phantom_views_new'])}",
                 "phantom_names": s["phantom_views_old"][:6],
                 "regressions": len(s["regressions"]),
                 "parse": f"{s['parse_s_old']} / {s['parse_s_new']}",
                 "classes": classes, "examples": examples})

lines = ["| Repository | Models | Explore views checked | Upstream source = reference (before → after) | Fields = reference (before → after) | Phantom `+view` models (before → after) | Regressions | Remaining mismatches after fix (class: n) |",
         "|---|--:|--:|---|---|---|--:|---|"]
for r in rows:
    if "error" in r:
        lines.append(f"| {r['repo']} | — | — | — | — | — | — | {r['error']} |"); continue
    cls = ", ".join(f"{k}: {v}" for k, v in sorted(r["classes"].items())) or "none"
    lines.append(f"| {r['repo']} | {r['models']} | {r['checked']} | {r['table']} | {r['fields']} | {r['phantom']} | {r['regressions']} | {cls} |")
lines.append("")
lines.append("Examples of remaining mismatches (one per class per repository):")
for r in rows:
    for c, ex in r.get("examples", {}).items():
        lines.append(f"- `{r['repo']}` · {c}: {ex}")
    if r.get("phantom_names"):
        lines.append(f"- `{r['repo']}` · phantom data models before the fix: {r['phantom_names']}")
text = "\n".join(lines)
print(text)
if md_out:
    md_out.write_text(text + "\n")
json.dump(rows, open(res_dir / "summary.json", "w"), indent=1)
