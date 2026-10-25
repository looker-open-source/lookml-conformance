#!/usr/bin/env python3
"""Merge raw search JSON into a pool, apply EXCLUDE rules, and emit a clone list.
Writes pool.json (every repo seen, with status) and clone_list.txt."""
import json, glob, os, re, sys, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
GOOGLE_OWNERS = {"looker", "llooker", "looker-open-source", "google", "googlecloudplatform", "googleapis",
                 "google-marketing-solutions", "googleclouddataproc"}
TOOL_FIXTURES = {"joshtemple/lkml", "spectacles-ci/spectacles", "ww-tech/lookml-tools", "datahub-project/datahub",
                 "open-metadata/openmetadata", "dagster-io/dagster", "metaphordata/connectors",
                 "fabio-looker/node-lookml-parser"}
DEMO_PAT = re.compile(r"(thelook|the_look|healthcare_demo|\bfaa\b|ecommerce[_ -]?demo)", re.I)

def main():
    pool = {}
    hits = collections.defaultdict(list)
    for f in sorted(glob.glob(os.path.join(ROOT, "_search", "*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for it in d.get("items") or []:
            fn = it["full_name"]
            hits[fn].append(os.path.basename(f)[:-5])
            if fn in pool:
                continue
            lic = it.get("license") or {}
            pool[fn] = {
                "id": fn, "owner": it["owner"]["login"], "owner_type": it["owner"]["type"], "repo": it["name"],
                "url": it["html_url"], "description": (it.get("description") or "")[:200],
                "stars": it.get("stargazers_count", 0), "forks": it.get("forks_count", 0), "is_fork": it.get("fork", False),
                "license": lic.get("spdx_id") or None, "pushed_at": it.get("pushed_at"), "created_at": it.get("created_at"),
                "size_kb": it.get("size", 0), "topics": it.get("topics") or [], "archived": it.get("archived", False),
                "language": it.get("language"), "default_branch": it.get("default_branch"),
            }
    for fn, r in pool.items():
        r["search_hits"] = sorted(set(hits[fn]))
        o = r["owner"].lower()
        if o in GOOGLE_OWNERS or "google" in o or "looker" == o:
            r["status"] = "excluded_google_looker_owner"
        elif r["is_fork"]:
            r["status"] = "excluded_fork"
        elif fn.lower() in TOOL_FIXTURES:
            r["status"] = "tool_fixture"
        elif DEMO_PAT.search(r["repo"]) or DEMO_PAT.search(r["description"] or ""):
            r["status"] = "demo_by_name"
        else:
            r["status"] = "eligible"
    with open(os.path.join(ROOT, "pool.json"), "w") as f:
        json.dump(sorted(pool.values(), key=lambda r: (-r["stars"], r["id"])), f, indent=1)
    c = collections.Counter(r["status"] for r in pool.values())
    print("pool size:", len(pool), dict(c))
    # Which owners dominate the google/looker exclusions?
    print("excluded owners:", collections.Counter(r["owner"] for r in pool.values() if r["status"].startswith("excluded_google")).most_common(10))
    return pool

if __name__ == "__main__":
    main()
