"""Differential check on real LookML repositories: for every view an explore references, compare
OpenMetadata before/after the fix against node-lookml-parser (reference), per model."""
import json, re, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import logging; logging.disable(logging.CRITICAL)
from metadata.readers.file.local import LocalReader
from metadata.utils.singleton import Singleton
from metadata.ingestion.source.dashboard.looker.bulk_parser import BulkLkmlParser
from old_bulk_parser import BulkLkmlParser as OldParser

norm = lambda s: None if s is None else re.sub(r"\s+", " ", s).strip()

def summarize(view):
    if view is None:
        return None
    fields = sorted(f.name for f in (*view.dimensions, *view.dimension_groups, *view.measures))
    return {"sql_table_name": norm(view.sql_table_name),
            "derived_sql": norm(view.derived_table.sql if view.derived_table else None), "fields": fields}

def run(repo: Path):
    oracle = json.loads(subprocess.run(["node", str(Path(__file__).parent / "oracle_full.js"), str(repo)],
                                       capture_output=True, text=True, timeout=600).stdout or "{}")
    if "error" in oracle:
        return {"repo": repo.name, "oracle_error": oracle["error"][:300]}
    Singleton.clear_all(); t0 = time.time()
    new = BulkLkmlParser(reader=LocalReader(repo)); t_new = time.time() - t0
    Singleton.clear_all(); t0 = time.time()
    old = OldParser(reader=LocalReader(repo)); t_old = time.time() - t0
    stats = {"repo": repo.name, "models": len(oracle), "checked": 0,
             "table_match_new": 0, "table_match_old": 0, "fields_match_new": 0, "fields_match_old": 0,
             "phantom_views_old": sorted(k for k in old._views_cache if k.startswith("+")),
             "phantom_views_new": sorted(k for k in new._views_cache if k.startswith("+")),
             "parse_s_old": round(t_old, 2), "parse_s_new": round(t_new, 2), "mismatches_new": [], "regressions": []}
    for model, data in oracle.items():
        t0 = time.time()
        for view_name in data["explore_views"]:
            ref = data["views"].get(view_name)
            if ref is None:
                continue
            stats["checked"] += 1
            n, o = summarize(new.find_view(view_name, model_name=model)), summarize(old.find_view(view_name))
            src = lambda s: s and (s["sql_table_name"], s["derived_sql"])
            r = (ref["sql_table_name"], ref["derived_sql"])
            tn, to = src(n) == r, src(o) == r
            fn, fo = bool(n) and n["fields"] == ref["fields"], bool(o) and o["fields"] == ref["fields"]
            stats["table_match_new"] += tn; stats["table_match_old"] += to
            stats["fields_match_new"] += fn; stats["fields_match_old"] += fo
            if not (tn and fn):
                stats["mismatches_new"].append({"model": model, "view": view_name, "oracle": ref, "new": n})
            if (to and not tn) or (fo and not fn):
                stats["regressions"].append({"model": model, "view": view_name})
        stats.setdefault("model_resolve_s_max", 0)
        stats["model_resolve_s_max"] = max(stats["model_resolve_s_max"], round(time.time() - t0, 3))
    return stats

if __name__ == "__main__":
    results = [run(Path(p)) for p in sys.argv[1:]]
    print(json.dumps(results, indent=1))
