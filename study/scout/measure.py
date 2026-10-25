#!/usr/bin/env python3
"""Measure LookML repos cloned under ~/work/corpus/<owner>__<repo>.
Usage: measure.py [dir ...]  (default: all <owner>__<repo> dirs). Writes measured.json.
Pure grep/find-style measurement — no LookML parser is used."""
import json, os, re, subprocess, sys, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
THELOOK_VIEWS = {"order_items", "inventory_items", "users", "products", "distribution_centers"}
DEMO_NAME_PAT = re.compile(r"(thelook|the_look|healthcare_demo|\bfaa\b|faa_)", re.I)
RE_REFINE = re.compile(r"^\s*(view|explore):\s*\+", re.M)
RE_VIEW_DECL = re.compile(r"^\s*view:\s*\+?\s*([A-Za-z0-9_]+)\s*\{", re.M)
RE_EXPLORE_DECL = re.compile(r"^\s*explore:\s*\+?\s*([A-Za-z0-9_]+)\s*\{", re.M)
RE_EXTENDS = re.compile(r"^\s*extends:", re.M)
RE_EXTENSION_REQ = re.compile(r"^\s*extension:\s*required", re.M)
RE_INCLUDE = re.compile(r"^\s*include:", re.M)
RE_INCLUDE_IMPORT = re.compile(r"^\s*include:\s*\"//", re.M)
RE_INCLUDE_IMPORT_NAME = re.compile(r"^\s*include:\s*\"//([^/\"]+)", re.M)
RE_CONSTANT = re.compile(r"^\s*constant:", re.M)
RE_LOCAL_DEP = re.compile(r"^\s*(local_dependency|remote_dependency):", re.M)
RE_CONN = re.compile(r"^\s*connection:\s*\"([^\"]*)\"", re.M)

def sh(cmd, cwd):
    try:
        return subprocess.check_output(cmd, cwd=cwd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return ""

def measure(d):
    name = os.path.basename(d)
    owner, _, repo = name.partition("__")
    m = collections.OrderedDict()
    m["id"] = f"{owner}/{repo}"
    m["clone_dir"] = d
    m["head_sha"] = sh("git rev-parse HEAD", d)
    m["last_commit_date"] = sh("git log -1 --format=%cI", d)
    m["repo_size_kb"] = int(sh("du -sk . | cut -f1", d) or 0)
    lkml = []
    for base, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules")]
        for f in files:
            if f.endswith(".lkml") or f.endswith(".lookml"):
                lkml.append(os.path.join(base, f))
    rel = [os.path.relpath(p, d) for p in lkml]
    m["n_lkml"] = sum(1 for p in rel if p.endswith(".lkml"))
    m["n_legacy_lookml"] = sum(1 for p in rel if p.endswith(".lookml"))
    m["n_model"] = sum(1 for p in rel if p.endswith(".model.lkml"))
    m["n_view"] = sum(1 for p in rel if p.endswith(".view.lkml"))
    m["n_explore"] = sum(1 for p in rel if p.endswith(".explore.lkml"))
    m["n_dashboard_lookml"] = sum(1 for p in rel if p.endswith(".dashboard.lookml"))
    m["has_manifest"] = any(os.path.basename(p) == "manifest.lkml" for p in rel)
    m["model_files"] = sorted(p for p in rel if p.endswith(".model.lkml"))[:20]
    cnt = collections.Counter()
    views, explores, conns = set(), set(), set()
    refine_files = set()
    imported = set()
    for p, r in zip(lkml, rel):
        if not r.endswith(".lkml"):
            continue
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        n_ref = len(RE_REFINE.findall(t))
        cnt["refinements"] += n_ref
        if n_ref:
            refine_files.add(r)
        cnt["view_refinements"] += len(re.findall(r"^\s*view:\s*\+", t, re.M))
        cnt["explore_refinements"] += len(re.findall(r"^\s*explore:\s*\+", t, re.M))
        cnt["extends"] += len(RE_EXTENDS.findall(t))
        cnt["extension_required"] += len(RE_EXTENSION_REQ.findall(t))
        cnt["includes"] += len(RE_INCLUDE.findall(t))
        cnt["includes_imported_project"] += len(RE_INCLUDE_IMPORT.findall(t))
        imported.update(RE_INCLUDE_IMPORT_NAME.findall(t))
        cnt["constants"] += len(RE_CONSTANT.findall(t))
        cnt["project_dependencies"] += len(RE_LOCAL_DEP.findall(t))
        cnt["lines"] += t.count("\n")
        views.update(RE_VIEW_DECL.findall(t))
        explores.update(RE_EXPLORE_DECL.findall(t))
        conns.update(RE_CONN.findall(t))
    for k in ["refinements", "view_refinements", "explore_refinements", "extends", "extension_required",
              "includes", "includes_imported_project", "constants", "project_dependencies", "lines"]:
        m["n_" + k] = cnt[k]
    m["n_files_with_refinements"] = len(refine_files)
    m["imported_projects"] = sorted(imported)[:10]
    m["n_distinct_views"] = len(views)
    m["n_distinct_explores"] = len(explores)
    m["connections"] = sorted(conns)[:10]
    m["has_constant"] = cnt["constants"] > 0
    m["has_model_file"] = m["n_model"] > 0
    m["has_refinement_or_extends"] = (cnt["refinements"] + cnt["extends"]) > 0
    overlap = sorted(THELOOK_VIEWS & views)
    m["thelook_view_overlap"] = overlap
    m["demo_flag_views"] = len(overlap) >= 4
    m["demo_flag_name"] = bool(DEMO_NAME_PAT.search(repo)) or any(DEMO_NAME_PAT.search(r) for r in rel)
    m["demo_name_hits"] = sorted({DEMO_NAME_PAT.search(r).group(0).lower() for r in rel if DEMO_NAME_PAT.search(r)})[:5]
    m["n_demo_named_files"] = sum(1 for r in rel if DEMO_NAME_PAT.search(r))
    m["repo_name_demo"] = bool(DEMO_NAME_PAT.search(repo))
    m["sample_views"] = sorted(views)[:12]
    return m

def main():
    dirs = sys.argv[1:] or sorted(os.path.join(ROOT, x) for x in os.listdir(ROOT)
                                  if "__" in x and os.path.isdir(os.path.join(ROOT, x, ".git")))
    out = [measure(d) for d in dirs]
    with open(os.path.join(ROOT, "measured.json"), "w") as f:
        json.dump(out, f, indent=1)
    for m in out:
        print(f'{m["id"]:45s} lkml={m["n_lkml"]:4d} model={m["n_model"]:2d} view={m["n_view"]:4d} refine={m["n_refinements"]:3d} '
              f'extends={m["n_extends"]:3d} inc//={m["n_includes_imported_project"]:2d} manifest={int(m["has_manifest"])} '
              f'demoV={int(m["demo_flag_views"])} demoN={int(m["demo_flag_name"])} {m["last_commit_date"][:10]}')

if __name__ == "__main__":
    main()
