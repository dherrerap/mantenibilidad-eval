"""Decision point *Cyclomatic complexity* (Modularity, Modifiability): C1/C2 share X of functions under the threshold
(MMo-2-G), C3 code duplication (CWE-1041); cognitive complexity is informational.
"""

from evaluator.common import RUBRIC, median
from evaluator.criteria import C, apply_manual, level_from


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
    TC = RUBRIC["thresholds"]["cognitive"]["function_threshold"]
    cogs = sorted(f.get("cog", 0) for f in fns)  # old metrics.json files have no "cog"
    high = [f for f in fns if f.get("cog", 0) > TC]  # informational: does not change the level
    met.update({"cognitive_median": median(cogs), "cognitive_max": cogs[-1] if cogs else None, "functions_cog_above_threshold": len(high)})
    ev += [f"{f['file']}:{f['line']} {f['name']} (cognitive={f.get('cog')})" for f in sorted(high, key=lambda f: -f["cog"])[:3]]
    finding += f" Cognitive complexity: {len(high)} functions > {TC}, max {met['cognitive_max']} (informational)."
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
