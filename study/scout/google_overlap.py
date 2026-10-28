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

"""Detect copies of Google/Looker-published LookML (looker-open-source, llooker) by file-name and view-name overlap.
Writes google_overlap.json: {repo_id: {best_match, file_containment, view_containment, ...}}"""
import os, re, json, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
GB = os.path.join(ROOT, "_google_blocks")
RE_VIEW_DECL = re.compile(r"^\s*view:\s*\+?\s*([A-Za-z0-9_]+)\s*\{", re.M)
GENERIC = {"users", "events", "orders", "products", "sessions", "customers", "accounts", "dates", "date", "period_over_period",
           "calendar", "transactions", "items", "user", "order", "product", "event", "session", "customer", "account",
           "manifest_lock", "readme"}

def scan(d):
    files, views = set(), set()
    for base, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in fs:
            if f.endswith(".lkml") and not f.endswith(".model.lkml") and f != "manifest.lkml":
                files.add(f.lower())
                if f.endswith(".view.lkml"):
                    try:
                        views.update(v.lower() for v in RE_VIEW_DECL.findall(open(os.path.join(base, f), encoding="utf-8", errors="replace").read()))
                    except OSError:
                        pass
    files = {f for f in files if f.split(".")[0] not in GENERIC}
    views = {v for v in views if v not in GENERIC}
    return files, views

google = {}
for d in sorted(os.listdir(GB)):
    p = os.path.join(GB, d)
    if os.path.isdir(p):
        google[d.replace("__", "/", 1)] = scan(p)
file_index, view_index = collections.defaultdict(set), collections.defaultdict(set)
for gid, (files, views) in google.items():
    for f in files:
        file_index[f].add(gid)
    for v in views:
        view_index[v].add(gid)

out = {}
for d in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, d)
    if "__" not in d or not os.path.isdir(os.path.join(p, ".git")):
        continue
    rid = d.replace("__", "/", 1)
    files, views = scan(p)
    fh, vh = collections.Counter(), collections.Counter()
    for f in files:
        for gid in file_index.get(f, ()):
            fh[gid] += 1
    for v in views:
        for gid in view_index.get(v, ()):
            vh[gid] += 1
    # best match = max over repos of (file_containment + view_containment)
    cands = set(fh) | set(vh)
    best, bs, bfc, bvc, bfs, bvs = None, -1.0, 0.0, 0.0, 0, 0
    for gid in cands:
        fc = fh[gid] / len(files) if files else 0.0
        vc = vh[gid] / len(views) if views else 0.0
        s = fc + vc
        if s > bs:
            best, bs, bfc, bvc, bfs, bvs = gid, s, fc, vc, fh[gid], vh[gid]
    out[rid] = {"best_match": best, "file_containment": round(bfc, 3), "view_containment": round(bvc, 3),
                "shared_files": bfs, "shared_views": bvs, "n_view_files": len(files), "n_views": len(views),
                "any_google_file_share": round(sum(1 for f in files if f in file_index) / len(files), 3) if files else 0.0,
                "shared_file_names": sorted(f for f in files if best and f in google[best][0])[:6]}
json.dump(out, open(os.path.join(ROOT, "google_overlap.json"), "w"), indent=1)
def is_copy(o):
    return (o["file_containment"] >= 0.6 and o["shared_files"] >= 3) or (o["view_containment"] >= 0.6 and o["shared_views"] >= 3) \
        or (o["file_containment"] >= 0.9 and o["view_containment"] >= 0.9 and o["shared_files"] >= 2)
n = sum(1 for v in out.values() if is_copy(v))
print("google blocks indexed:", len(google), "repos scanned:", len(out), "flagged as Google-block copies:", n)
