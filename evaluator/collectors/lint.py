"""ESLint + eslint-plugin-sonarjs over the app's production files (lint_metrics.js).

The rules come from rubric.json: `lint.ascmm` (ISO/IEC 5055 weaknesses that no other collector detects) plus three measurement
rules configured from `thresholds`: S1192 `sonarjs/no-duplicate-string` (configuration.C2), S3776 `sonarjs/cognitive-complexity`
(informational cognitive complexity) and ESLint `complexity` (a cross-check of the McCabe count of ast_metrics.js). The two
complexity rules run with a limit of 0 so that they report the value of every function.

Without ESLint installed (`npm install`) the result is {"ok": False, …}: configuration.C2 stays pending and the cognitive complexity
and the ASCMM indicators that need ESLint are not measured (there is no approximation to fall back to).
"""
import json
import re

from evaluator.common import HERE, RUBRIC, sh

S1192, S3776, MCCABE = "sonarjs/no-duplicate-string", "sonarjs/cognitive-complexity", "complexity"


def lint_rules():
    """{rule id: ESLint setting} and {rule id: CWE} for this rubric."""
    T = RUBRIC["thresholds"]["configuration"]
    rules = {S1192: ["error", {"threshold": T["dup_literal_threshold"], "ignoreStrings": ",".join(T["dup_literal_ignore"])}],
             S3776: ["error", 0], MCCABE: ["error", {"max": 0}]}
    cwe = {}
    for c, d in RUBRIC.get("lint", {}).get("ascmm", {}).items():
        for r, setting in d["rules"].items():
            rules[r] = setting; cwe[r] = c
    return rules, cwe


def usable(m):
    """(lint, note) for a metrics dictionary: `lint` is None when ESLint did not run (no result, or an old metrics.json), and
    `note` says why, or lists the files ESLint could not parse (their reports are missing, so a count of 0 is not proven)."""
    lint = m.get("lint") or {}
    if not lint.get("ok"):
        return None, "ESLint did not run: " + (lint.get("error") or "no lint result in metrics.json (evaluate the app again)")[:160]
    pe = lint.get("parse_errors") or []
    return lint, (f"ESLint could not parse {len(pe)} file(s): " + ", ".join(sorted({x["file"] for x in pe})[:5])) if pe else None


def decide_count(n, lint, note):
    """ok of an occurrence count that must be 0: False with any occurrence (certain), None when ESLint did not run or some file did not
    parse (a 0 is not proven), True otherwise."""
    if lint is not None and n:
        return False
    return None if lint is None or note else True


def available():
    return all((HERE / "node_modules" / p / "package.json").exists() for p in ("eslint", "eslint-plugin-sonarjs", "typescript-eslint"))


NUM = re.compile(r"(?:complexity of|Complexity from) (\d+)")


def run_lint(app, out, files):
    """Runs lint_metrics.js on `files` (app-relative production files) and summarizes the reports by use."""
    if not available():
        return {"ok": False, "error": "ESLint is not installed: run `npm install` in the framework folder"}
    rules, cwe = lint_rules()
    req = out / "lint_request.json"; raw = out / "lint_raw.json"
    req.write_text(json.dumps({"files": files, "rules": rules}), encoding="utf-8")
    rc, so, se = sh(["node", str(HERE / "lint_metrics.js"), str(app), str(req), str(raw)], timeout=900)
    try:
        r = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        r = {"ok": False, "error": (se or so or f"exit {rc}")[-2000:]}
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "")[-2000:]}
    return summarize(r, cwe)


TIMES = re.compile(r"\b(\d+) times\b")


def summarize(r, cwe):
    """Reports of lint_metrics.js grouped by use: per-function McCabe and cognitive values, S1192 literals, occurrences per CWE."""
    res = {"ok": True, "versions": r["versions"], "files": r["files"], "parse_errors": r["parse_errors"],
           "mccabe": [], "cognitive": [], "dup_strings": [], "ascmm": {c: [] for c in RUBRIC.get("lint", {}).get("ascmm", {})}}
    seen = set()
    for x in r["messages"]:
        loc = {"file": x["file"], "line": x["line"]}
        if x["rule"] in (MCCABE, S3776):
            n = NUM.search(x["message"])
            if n:
                res["mccabe" if x["rule"] == MCCABE else "cognitive"].append({**loc, "value": int(n.group(1))})
        elif x["rule"] == S1192:
            n = TIMES.search(x["message"])
            res["dup_strings"].append({**loc, "literal": x.get("text"), "times": int(n.group(1)) if n else None})
        elif x["rule"] in cwe and (x["rule"], x["file"], x["line"]) not in seen:
            # one occurrence per rule and line: no-mixed-operators reports each operator of `a && b || c`
            seen.add((x["rule"], x["file"], x["line"]))
            res["ascmm"][cwe[x["rule"]]].append({**loc, "end_line": x["endLine"], "rule": x["rule"], "message": x["message"][:160]})
    return res
