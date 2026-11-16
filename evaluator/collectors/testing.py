"""Tests: static count of test cases, execution of the test suites and coverage (c8, node --test, Jest).
"""
import json
import os
import re
import shutil
from pathlib import Path

from evaluator.common import BIN, sh, walk


def static_tests(ast, app):
    files = [f["path"] for f in ast["files"] if f["test"]]
    n = 0
    for f in files:
        try:
            n += len(re.findall(r"\b(?:it|test)(?:\.each)?\s*\(", (Path(app) / f).read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            pass
    return {"test_files": files, "test_cases": n}


def parse_lcov(lcov, d):
    """Sums LF/LH/BRF/BRH from an lcov.info. Node only reports the files the tests load, so unloaded .js/.ts
    sources are added with 0 covered lines (equivalent to Jest's collectCoverageFrom); their branches cannot be
    counted without instrumenting them and stay out of the denominator."""
    tot = {"lines_total": 0, "lines_cov": 0, "br_total": 0, "br_cov": 0, "unloaded": 0}
    seen = set()
    for ln in lcov.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("SF:"): seen.add(os.path.normcase(os.path.normpath(str((d / ln[3:]) if not os.path.isabs(ln[3:]) else ln[3:]))))
        elif ln.startswith("LF:"): tot["lines_total"] += int(ln[3:])
        elif ln.startswith("LH:"): tot["lines_cov"] += int(ln[3:])
        elif ln.startswith("BRF:"): tot["br_total"] += int(ln[4:])
        elif ln.startswith("BRH:"): tot["br_cov"] += int(ln[4:])
    for f in walk(d):
        f = Path(f)
        if f.suffix not in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"): continue
        if re.search(r"\.(test|spec)\.", f.name) or {"tests", "__tests__", "coverage"} & set(f.parts): continue
        if os.path.normcase(os.path.normpath(str(f))) in seen: continue
        try: n = sum(1 for x in f.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip())
        except OSError: continue
        tot["lines_total"] += n; tot["unloaded"] += 1
    return tot


def run_tests(app, pkgs, test_cmd, out):
    res = {"executed": True, "packages": [], "lines_total": 0, "lines_cov": 0, "br_total": 0, "br_cov": 0, "all_passed": True, "ran_any": False}
    for p in pkgs:
        script = p["scripts"].get("test", "")
        if not script or "no test specified" in script:
            continue
        d = Path(app) / p["dir"]
        if not (d / "node_modules").exists():
            sh(["npm", "install", "--no-audit", "--no-fund"], cwd=d, timeout=900)
        native = (not test_cmd) and bool(re.search(r"\bnode\b.*--test\b|node:test", script))
        lcov = d / "coverage" / "lcov.info"
        c8 = BIN / ("c8.cmd" if os.name == "nt" else "c8")
        runner = "node:test"
        if native and c8.exists():
            # c8 --all also instruments the sources that no test loads: lines and branches with the full denominator
            runner = "c8"
            cmd = [str(c8), "--all", "--src=.", "--reporter=lcovonly", "--reports-dir=coverage",
                   "--exclude=**/{tests,test,__tests__,coverage,dist,build}/**", "--exclude=**/*.{test,spec}.*",
                   "--exclude=**/*.config.*", shutil.which("node") or "node", "--test"]
        elif native:
            # without c8: Node's native runner (node --test); branches of unloaded files stay out of the denominator
            lcov.parent.mkdir(exist_ok=True)
            cmd = [shutil.which("node") or "node", "--test", "--experimental-test-coverage",
                   "--test-coverage-exclude=**/*.test.*", "--test-coverage-exclude=**/{tests,__tests__,coverage}/**",
                   "--test-reporter=spec", "--test-reporter-destination=stdout",
                   "--test-reporter=lcov", f"--test-reporter-destination={lcov}"]
        else:
            cmd = test_cmd.split() if test_cmd else ["npm", "test", "--silent", "--", "--coverage",
                                                     "--coverageReporters=json-summary", "--watchAll=false",
                                                     # without this Jest only measures the files the tests import (inflated coverage)
                                                     "--collectCoverageFrom=**/*.{js,jsx,ts,tsx}", "--collectCoverageFrom=!**/node_modules/**",
                                                     "--collectCoverageFrom=!**/{tests,__tests__,coverage,dist,build}/**", "--collectCoverageFrom=!**/*.{test,spec}.*"]
        env = {**os.environ, "CI": "true"}
        cs = d / "coverage" / "coverage-summary.json"
        for stale in (lcov, cs):  # a report left by an earlier run must not be read as the result of this one
            stale.unlink(missing_ok=True)
        rc, so, se = sh(cmd, cwd=d, timeout=900, env=env)
        entry = {"dir": p["dir"], "rc": rc, "tail": (so + se)[-400:]}
        res["ran_any"] = True
        if rc != 0:
            res["all_passed"] = False
        if native and lcov.exists():
            t = parse_lcov(lcov, d)
            res["lines_total"] += t["lines_total"]; res["lines_cov"] += t["lines_cov"]
            res["br_total"] += t["br_total"]; res["br_cov"] += t["br_cov"]
            entry["coverage"] = {"lines": round(100.0 * t["lines_cov"] / t["lines_total"], 1) if t["lines_total"] else 0.0,
                                 "branches": round(100.0 * t["br_cov"] / t["br_total"], 1) if t["br_total"] else None,
                                 "runner": runner, "unloaded_files": t["unloaded"]}
        elif cs.exists():
            t = json.loads(cs.read_text(encoding="utf-8"))["total"]
            res["lines_total"] += t["lines"]["total"]; res["lines_cov"] += t["lines"]["covered"]
            res["br_total"] += t["branches"]["total"]; res["br_cov"] += t["branches"]["covered"]
            entry["coverage"] = {"lines": t["lines"]["pct"], "branches": t["branches"]["pct"]}
        res["packages"].append(entry)
    return res
