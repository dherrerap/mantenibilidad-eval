"""Decision point *Cyclomatic complexity* (Modularity, Modifiability): C1/C2 share X of functions under the threshold
(MMo-2-G), C3 code duplication (CWE-1041); cognitive complexity (SonarJS S3776) and the cross-check of the McCabe count against
ESLint `complexity` are informational and need ESLint.
"""

from evaluator.collectors.lint import usable
from evaluator.common import RUBRIC, median
from evaluator.criteria import C, apply_manual, level_from


def cognitive_metrics(fns, lint):
    """Informational cognitive complexity from SonarJS S3776 itself: every function it reports, and 0 for the functions it does not
    report. None of it when ESLint did not run (`lint` is None). `_high` = functions above the threshold, worst first."""
    TC = RUBRIC["thresholds"]["cognitive"]["function_threshold"]
    if lint is None:
        return {"cognitive_source": None, "cognitive_threshold": TC, "cognitive_median": None, "cognitive_max": None,
                "functions_cog_above_threshold": None, "_high": []}
    vals = [{"file": x["file"], "line": x["line"], "cog": x["value"]} for x in lint["cognitive"]]
    cogs = sorted([0] * max(len(fns) - len(vals), 0) + [v["cog"] for v in vals])
    high = sorted((v for v in vals if v["cog"] > TC), key=lambda v: -v["cog"])
    return {"cognitive_source": "SonarJS S3776", "cognitive_threshold": TC, "cognitive_median": median(cogs),
            "cognitive_max": cogs[-1] if cogs else None, "functions_cog_above_threshold": len(high), "_high": high}


def cross_check(fns, eslint, threshold):
    """McCabe of ast_metrics.js against ESLint `complexity`, matching functions by file and start line. Checked with ESLint 10.14:
    both count default parameters, &&/||/??, logical assignments, case clauses and catch alike, but ESLint also counts every
    optional chaining `?.`, so differences are expected in code that uses it. X is the share of functions at or under the threshold
    according to ESLint."""
    ours = {}
    for f in fns:
        ours.setdefault((f["file"], f["line"]), f["cc"])
    theirs = {}
    for x in eslint:
        theirs.setdefault((x["file"], x["line"]), x["value"])
    both = [k for k in ours if k in theirs]
    equal = sum(ours[k] == theirs[k] for k in both)
    above = sum(v > threshold for v in theirs.values())
    return {"matched": len(both), "ours": len(ours), "eslint": len(theirs),
            "equal_pct": round(100.0 * equal / len(both), 1) if both else None,
            "max_abs_diff": max((abs(ours[k] - theirs[k]) for k in both), default=None),
            "above_threshold": above, "X": round(1 - above / len(theirs), 4) if theirs else None}


def lint_measures(m, fns, threshold):
    """The informational measures that come from ESLint: cognitive complexity and the McCabe cross-check → (metrics, evidence, text)."""
    lint, note = usable(m)
    met = cognitive_metrics(fns, lint)
    high = met.pop("_high")
    if lint is None:
        return met, [], f" Cognitive complexity not measured ({note})."
    ev = [f"{f['file']}:{f['line']} (cognitive={f['cog']})" for f in high[:3]]
    txt = (f" Cognitive complexity (SonarJS S3776): {len(high)} functions > {met['cognitive_threshold']}, "
           f"max {met['cognitive_max']} (informational).")
    met["mccabe_eslint"] = x = cross_check(fns, lint["mccabe"], threshold)
    if x["matched"]:
        txt += (f" Cross-check with ESLint `complexity`: same value in {x['equal_pct']}% of {x['matched']} matched functions, "
                f"X = {x['X']} (informational).")
    return met, ev, txt + (f" {note}." if note else "")


def eval_cyclomatic(m, manual, opts):
    T = RUBRIC["thresholds"]["cyclomatic"]
    fns = [f for f in m["ast"]["functions"] if not f["test"]]
    B = len(fns); big = [f for f in fns if f["cc"] > T["function_threshold"]]
    X = 1 - len(big) / B if B else None
    ccs = sorted(f["cc"] for f in fns)
    met = {"functions": B, "functions_cc_above_threshold": len(big), "X": X,
           "median": median(ccs), "p90": ccs[int(0.9 * (len(ccs) - 1))] if ccs else None, "max": ccs[-1] if ccs else None}
    if X is None:
        return {}, met, [], "No implemented functions.", (None, None, None)
    ev = [f"{f['file']}:{f['line']} {f['name']} (CC={f['cc']})" for f in sorted(big, key=lambda f: -f["cc"])[:8]]
    crit = {"C1": C(X >= T["partial_X_min"], "X ≥ 0.95 (Partial)", round(X, 4)), "C2": C(X >= T["meets_X_min"], "X ≥ 0.98 (Meets)", round(X, 4))}
    finding = f"X = 1 − {len(big)}/{B} = {X:.3f}; median CC {met['median']}, p90 {met['p90']}, max {met['max']}."
    lmet, lev, ltxt = lint_measures(m, fns, T["function_threshold"])
    met.update(lmet); ev += lev; finding += ltxt
    # C3: CWE-1041 (Use of Redundant Code). Scored: it lowers this point's level. Pending if jscpd did not run.
    T2 = RUBRIC["thresholds"]["duplication"]
    dup = m.get("duplication") or {}
    dup_ok = None if not dup.get("ok") else dup["pct"] <= T2["pct_max"]
    crit["C3"] = C(dup_ok, f"≤ {T2['pct_max']:g}% duplicated lines (CWE-1041)",
                   f"{dup['pct']:.1f}%" if dup.get("ok") else None,
                   source="auto" if dup.get("ok") else "pending (jscpd)")
    if dup.get("ok"):
        met.update({"duplication_pct": dup["pct"], "clones": dup["clones"], "duplication_above_threshold": dup["pct"] > T2["pct_max"]})
        ev += [f"clone {c}" for c in dup["top"][:3]]
        finding += f" Duplication (jscpd): {dup['pct']:.1f}% of lines, {dup['clones']} clones (threshold {T2['pct_max']:g}%, CWE-1041)."
    apply_manual("cyclomatic", crit, manual)
    return crit, met, ev, finding, level_from(crit)
