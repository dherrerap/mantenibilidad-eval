"""Supplementary indicators: informational, they score none of the 11 points (test quality, documentation, frontend,
static security, schema-contract consistency, and the ISO/IEC 5055 weaknesses that no point scores).
"""
import re

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_schema as rs  # noqa: E402
from evaluator.collectors.lint import decide_count, usable
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
    for row in ascmm_indicators(m):
        add(*row)
    return res


def commented_out_functions(fns, reports, max_pct):
    """CWE-1085: functions whose commented-out lines (SonarJS S125 reports, which span the lines of each comment block) exceed
    `max_pct` of the function's lines. Returns [(function, commented lines)]."""
    by_file = {}
    for x in reports:
        by_file.setdefault(x["file"], set()).update(range(x["line"], x["end_line"] + 1))
    out = []
    for f in fns:
        lines = by_file.get(f["file"], set()) & set(range(f["line"], f["line"] + f["loc"]))
        if lines and 100.0 * len(lines) / f["loc"] > max_pct:
            out.append((f, len(lines)))
    return out


def ascmm_indicators(m):
    """Informational ISO/IEC 5055 weaknesses that no point scores (`backing._coverage_ascmm.informational`): count, density per
    KLOC of production code and the reference of the standard. All but CWE-1064 need ESLint (lint_metrics.js)."""
    T = RUBRIC["thresholds"]["ascmm"]; a = m["ast"]; rows = []
    fns = [f for f in a.get("functions", []) if not f["test"]]
    kloc = sum(f["loc"] for f in a["files"] if not f["test"]) / 1000.0
    dens = lambda n: f" ({n / kloc:.2f}/KLOC)" if kloc else ""  # noqa: E731
    many = [f for f in fns if len(f.get("params", [])) > T["params_max"]]
    rows.append(("ascmm_cwe1064", "ASCMM", f"CWE-1064 Functions with more than {T['params_max']} parameters", len(many), "0", not many,
                 f"{len(many)} of {len(fns)} functions{dens(len(many))}. Default of ISO/IEC 5055: {T['params_max']} parameters.",
                 [f"{f['file']}:{f['line']} {f['name']} ({len(f['params'])} parameters)" for f in many]))
    lint, note = usable(m)
    tail = f" {note}." if note else ""
    for cwe, d in RUBRIC.get("lint", {}).get("ascmm", {}).items():
        id_ = "ascmm_" + cwe.lower().replace("-", "").replace("/", "_")
        if lint is None:
            rows.append((id_, "ASCMM", f"{cwe} {d['name']}", None, "0", None, note + "."))
            continue
        reps = lint["ascmm"].get(cwe, [])
        if cwe == "CWE-1085":
            bad = commented_out_functions(fns, reps, T["commented_code_max_pct"])
            rows.append((id_, "ASCMM", f"{cwe} Functions with more than {T['commented_code_max_pct']:g}% commented-out code", len(bad), "0",
                         decide_count(len(bad), lint, note),
                         f"{len(bad)} of {len(fns)} functions{dens(len(bad))}; {len(reps)} commented-out block(s) in total (SonarJS S125).{tail}",
                         [f"{f['file']}:{f['line']} {f['name']} ({n} of {f['loc']} lines)" for f, n in bad]))
            continue
        rules = sorted({x["rule"] for x in reps})
        rows.append((id_, "ASCMM", f"{cwe} {d['name']}", len(reps), str(T["occurrences_max"]), decide_count(len(reps), lint, note),
                     f"{len(reps)} occurrence(s){dens(len(reps))}" + (f" ({', '.join(rules)})" if rules else "") + f".{tail}",
                     [f"{x['file']}:{x['line']} {x['message']}" for x in reps]))
    return rows
