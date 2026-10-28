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

"""Rigorous re-classification of the residual (after-fix) mismatches in the corpus differential.

Classes (checked in this order):
  extends        view block declares `extends:` (OpenMetadata keeps extends as a view->view edge, no flattening)
  unresolved     OpenMetadata-fixed returned no view at all
  src_differs    upstream source string differs (sub-class: constant_subst if only @{...}/liquid differs)
  fields_only    source identical, only the field list differs (shows the set difference)
"""
import json, re, sys, collections
from pathlib import Path

res_dir = Path(sys.argv[1]).expanduser()
runs_dir = res_dir.parent

def view_block(repo_dir, name):
    pat = re.compile(r"^\s*view:\s*" + re.escape(name) + r"\s*\{")
    for f in repo_dir.rglob("*.lkml"):
        try:
            lines = f.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if pat.match(line):
                depth, out = 0, []
                for l in lines[i:]:
                    out.append(l); depth += l.count("{") - l.count("}")
                    if depth <= 0 and len(out) > 1:
                        break
                return "\n".join(out), str(f.relative_to(repo_dir))
    return "", None

totals = collections.Counter()
grand = collections.Counter()
per_repo = {}
field_diff_examples = []
for jf in sorted(res_dir.glob("*.json")):
    if jf.name == "summary.json":
        continue
    s = json.load(open(jf))[0]
    grand["checked"] += s["checked"]; grand["models"] += s["models"]
    for k in ("table_match_old", "table_match_new", "fields_match_old", "fields_match_new"):
        grand[k] += s[k]
    grand["phantom_old"] += len(s["phantom_views_old"]); grand["phantom_new"] += len(s["phantom_views_new"])
    grand["regressions"] += len(s["regressions"])
    repo_dir = runs_dir / s["repo"]
    c = collections.Counter()
    for mm in s.get("mismatches_new", []):
        ref, new = mm["oracle"], mm["new"]
        block, path = view_block(repo_dir, mm["view"])
        if re.search(r"^\s*extends:", block, re.M):
            cls = "extends"
        elif new is None:
            cls = "unresolved"
        else:
            r = (ref.get("sql_table_name"), ref.get("derived_sql"))
            n = (new.get("sql_table_name"), new.get("derived_sql"))
            if r != n:
                rs, ns = " ".join(str(x) for x in r), " ".join(str(x) for x in n)
                cls = "src_differs:constant_subst" if re.sub(r"@\{[^}]*\}", "", rs) == re.sub(r"@\{[^}]*\}", "", ns) else "src_differs"
            else:
                cls = "fields_only"
                missing = sorted(set(ref["fields"]) - set(new["fields"]))
                extra = sorted(set(new["fields"]) - set(ref["fields"]))
                field_diff_examples.append((s["repo"], mm["model"], mm["view"], path, missing[:6], extra[:6]))
        c[cls] += 1; totals[cls] += 1
    per_repo[s["repo"]] = dict(c)

print("GRAND:", dict(grand))
print("RESIDUAL CLASSES:", dict(totals))
for r, c in per_repo.items():
    if c: print(f"  {r}: {c}")
print("\nfields_only examples (repo, model, view, file, missing-in-OM, extra-in-OM):")
for e in field_diff_examples[:20]:
    print(" ", e)
