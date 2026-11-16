"""Supplementary indicators: informational, they score none of the 11 points (test quality, documentation, frontend,
static security, schema-contract consistency).
"""
import re

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_schema as rs  # noqa: E402
from evaluator.common import RUBRIC


README_TOPICS = {"installation": r"install|npm i", "execution": r"\brun|execut|npm (run )?start|docker", "tests": r"test",
                 "API": r"api|endpoint|route", "configuration": r"\.env|variable|config"}


def supplementary_indicators(m):
    """Informational indicators that score none of the 11 points: test quality, documentation, frontend,
    static security and schema-contract consistency. Each carries an 'ok' / 'review' / 'n/a' status against a reference."""
    R = RUBRIC["thresholds"]["supplementary"]; a = m["ast"]; res = []

    def add(id_, group, name, value, ref, ok, detail, ev=()):
        res.append({"id": id_, "group": group, "name": name, "value": value, "reference": ref,
                    "status": "n/a" if ok is None else ("ok" if ok else "review"), "detail": detail, "evidence": list(ev)[:5]})

    tc = a.get("testCases", [])
    no_asserts = [t for t in tc if not t["asserts"]]
    add("tests_without_assertions", "Tests", "Test cases without assertions", len(no_asserts), "0",
        None if not tc else not no_asserts, f"{len(no_asserts)} of {len(tc)} cases contain no assert/expect.", [f"{t['file']}:{t['line']}" for t in no_asserts])
    loc_t = sum(f["loc"] for f in a["files"] if f["test"]); loc_p = sum(f["loc"] for f in a["files"] if not f["test"])
    ratio = loc_t / loc_p if loc_p else None
    add("tests_loc_ratio", "Tests", "Test LOC / production LOC", None if ratio is None else round(ratio, 2), f"≥ {R['test_ratio_min']}",
        None if ratio is None else ratio >= R["test_ratio_min"], f"{loc_t} test lines against {loc_p} production lines.")
    tfiles = {f["path"] for f in a["files"] if f["test"]}
    integ = {i["file"] for i in a["imports"] if i["file"] in tfiles and i["spec"] in RUBRIC["libs_integration_test"]}
    add("tests_integration", "Tests", "Integration test files (HTTP or database)", len(integ), "≥ 1",
        None if not tfiles else bool(integ), f"{len(integ)} of {len(tfiles)} test files touch the API or the database.")

    docs = a.get("docs", [])
    ndoc = sum(d["documented"] for d in docs)
    dpct = 100.0 * ndoc / len(docs) if docs else None
    add("doc_jsdoc", "Documentation", "Top-level functions and methods with JSDoc (%)", None if dpct is None else round(dpct, 1), f"≥ {R['jsdoc_min_pct']}%",
        None if dpct is None else dpct >= R["jsdoc_min_pct"], f"{ndoc} of {len(docs)} functions documented.",
        [f"{d['file']}:{d['line']} {d['name']}" for d in docs if not d["documented"]])
    rd = m.get("readme", "")
    covered = [k for k, rx in README_TOPICS.items() if re.search(rx, rd, re.I)]
    add("doc_readme", "Documentation", "Topics covered by the README", f"{len(covered)}/{len(README_TOPICS)}", f"{len(README_TOPICS)}/{len(README_TOPICS)}",
        bool(rd) and len(covered) == len(README_TOPICS), ("No README. " if not rd else "") + "Missing: " + (", ".join(k for k in README_TOPICS if k not in covered) or "none") + ".")

    comps = a.get("components", []); hooks = a.get("hooks", [])
    if comps or hooks:
        big = [c for c in comps if c["loc"] > R["component_loc_max"]]
        many = [c for c in comps if c["props"] > R["component_props_max"]]
        nodeps = [h for h in hooks if h["noDeps"]]
        add("fe_large_components", "Frontend", f"Components over {R['component_loc_max']} lines", len(big), "0", not big,
            f"{len(big)} of {len(comps)} components.", [f"{c['file']}:{c['line']} {c['name']} ({c['loc']} lines)" for c in big])
        add("fe_props", "Frontend", f"Components with more than {R['component_props_max']} props", len(many), "0", not many,
            f"{len(many)} of {len(comps)} components (a sign of prop drilling or lack of composition).",
            [f"{c['file']}:{c['line']} {c['name']} ({c['props']} props)" for c in many])
        add("fe_hooks_without_deps", "Frontend", "useEffect/useCallback/useMemo without a dependency array", len(nodeps), "0", not nodeps,
            f"{len(nodeps)} of {len(hooks)} hooks run on every render.", [f"{h['file']}:{h['line']} {h['hook']}" for h in nodeps])
        ft = [f for f in a["files"] if f["test"] and f["frontend"]]
        add("fe_tests", "Frontend", "Frontend test files", len(ft), "≥ 1", bool(ft), f"{len(ft)} test files in the frontend.")

    sec = a.get("security", {})
    for id_, key, name in (("sec_eval", "evalCalls", "Use of eval / new Function"), ("sec_secrets", "secrets", "Literal credentials in the code"),
                           ("sec_sql", "sqlInjection", "Raw SQL built by interpolation or concatenation")):
        xs = sec.get(key, [])
        add(id_, "Static security", name, len(xs), "0", not xs, f"{len(xs)} finding(s).", [f"{x['file']}:{x['line']}" for x in xs])

    props = set(m["contract"].get("properties") or [])
    fields = {c["name"] for t in m["schema"]["tables"].values() for c in t["columns"].values()}
    norm_props = {rs.fold(p) for p in props}
    if props and fields:
        missing = sorted(f for f in fields if rs.fold(f) not in norm_props)
        cov = 100.0 * (len(fields) - len(missing)) / len(fields)
        add("contract_schema", "Contract", "Table columns present in the contract (%)", round(cov, 1), f"≥ {R['contract_fields_min_pct']}%",
            cov >= R["contract_fields_min_pct"], f"{len(fields) - len(missing)} of {len(fields)} fields appear as a property in the contract.", [f"missing {c}" for c in missing])
    return res
