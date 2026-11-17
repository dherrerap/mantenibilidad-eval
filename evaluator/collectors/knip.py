"""Knip over every package of the app (knip_metrics.js): files no entry point reaches (CWE-561, coupling.C5), unused dependencies
(coupling.C4), unused exports and dependencies used but not declared (informational).

Each directory with a package.json is analyzed as its own project; the package directories nested inside it are left out of it.
None of the app's files is executed: see knip_metrics.js and no_exec_guard.mjs. Without Knip installed the result is
{"ok": False, …} and C4 and C5 stay pending.
"""
import json
import os
import re

from evaluator.collectors.packages import find_packages
from evaluator.common import HERE, RUBRIC, rel, sh

EXTS = "js,mjs,cjs,jsx,ts,tsx,mts,cts"


def available():
    return (HERE / "node_modules" / "knip" / "package.json").exists()


def entry_globs():
    T = RUBRIC["thresholds"]["dead_code"]
    return [f"**/{{{','.join(T['entry_points'])}}}.{{{EXTS}}}"] + list(T.get("entry_globs", []))


def join(rd, p):
    return p if rd == "." else f"{rd}/{p}"


def run_knip(app, out):
    if not available():
        return {"ok": False, "error": "Knip is not installed: run `npm install` in the framework folder"}
    pkgs = find_packages(app); work = out / "knip"; work.mkdir(parents=True, exist_ok=True)
    res = {"ok": True, "version": None, "packages": [], "files": [], "dependencies": [], "devDependencies": [], "binaries": [],
           "unlisted": [], "unresolved": [], "exports": [], "config_load_errors": [], "overridden_plugins": {}}
    env = {**os.environ, "NO_EXEC_ROOT": str(app)}
    for d in pkgs:
        rd = rel(d, app) or "."
        nested = [rel(o, d) for o in pkgs if o != d and str(o.resolve()).startswith(str(d.resolve()) + os.sep)]
        tag = re.sub(r"[^\w.-]", "_", rd)
        req, raw = work / f"{tag}.request.json", work / f"{tag}.json"
        req.write_text(json.dumps({"dir": str(d), "root": str(app), "nested": nested, "entry": entry_globs(),
                                   "config_file": str(work / f"{tag}.knip.json")}), encoding="utf-8")
        # the wrapper also runs under the guard: it calls the plugins' isEnabled() on the package
        rc, so, se = sh(["node", "--import", (HERE / "no_exec_guard.mjs").as_uri(), str(HERE / "knip_metrics.js"), str(req), str(raw)],
                        timeout=900, env=env)
        try:
            r = json.loads(raw.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            r = {"ok": False, "error": (se or so or f"exit {rc}")[-2000:]}
        res["packages"].append({"dir": rd, "ok": r.get("ok", False), "error": r.get("error")})
        if not r.get("ok"):
            res["ok"] = False
            continue
        res["version"] = r["version"]
        res["files"] += [join(rd, f) for f in r["files"]]
        for k in ("dependencies", "devDependencies", "binaries"):
            res[k] += [f"{rd}:{x}" for x in r[k]]
        for k in ("unlisted", "unresolved"):
            res[k] += [{"file": join(rd, x["file"]), "name": x["name"]} for x in r[k]]
        res["exports"] += [{**x, "file": join(rd, x["file"])} for x in r["exports"]]
        res["config_load_errors"] += [f"{rd}: {x}" for x in r["config_load_errors"]]
        if r["overridden_plugins"]:
            res["overridden_plugins"][rd] = r["overridden_plugins"]
    if not pkgs:
        res.update(ok=False, error="no package.json in the app")
    elif not res["ok"]:
        res["error"] = "; ".join(f"{p['dir']}: {(p['error'] or '')[:300]}" for p in res["packages"] if not p["ok"])
    return res
