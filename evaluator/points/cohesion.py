"""Decision point *Cohesion* (Modularity, Modifiability): C1 functions with high fan-out, C2 DV8 Decoupling Level,
C3 checklist (god modules, fragmentation; heuristic), C4 oversized files (CWE-1080).
"""

from evaluator.common import RUBRIC, pct
from evaluator.criteria import C, apply_manual, heur
from evaluator.graph import fan_in


def eval_cohesion(m, manual, opts):
    T = RUBRIC["thresholds"]["cohesion"]
    fns = [f for f in m["ast"]["functions"] if not f["test"]]
    hi = [f for f in fns if f["fanout"] > T["fanout_max"]]
    p = pct(len(hi), len(fns))
    fi = fan_in(m); locs = {f["path"]: f["loc"] for f in m["ast"]["files"]}
    gods = [f"{k} (LOC={locs.get(k)}, fan-in={v})" for k, v in fi.items()
            if locs.get(k, 0) >= T["god_loc_min"] and v >= T["god_fanin_min"]]
    prod = [f for f in m["ast"]["files"] if not f["test"]]
    frag = pct(sum(1 for f in prod if f["loc"] < 10), len(prod)) if prod else 0
    dl = (manual.get("dv8") or {}).get("DL")
    c1 = C(p is not None and p <= T["pct_fanout_max"], "≤ 5% of functions with fan-out > 5", f"{len(hi)}/{len(fns)} = {p:.1f}%" if p is not None else None)
    c2 = C(None if dl is None else dl >= T["DL_min"], "DV8 DL ≥ 60%", dl, source="dv8" if dl is not None else "pending (DV8)")
    c3 = heur(C(None, "Checklist with no findings ('god' module, mixed responsibilities, fragmentation)",
                {"suggested_god_modules": gods, "files_under_10_loc_pct": round(frag, 1)}, suggested=(not gods and frag < 40)), opts)
    # C4: CWE-1080 (Source Code File with Excessive Number of Lines of Code), default threshold 1000.
    oversized = sorted(((f["path"], f["loc"]) for f in prod if f["loc"] > T["file_loc_max"]), key=lambda x: -x[1])
    c4 = C(len(oversized) == 0, f"0 production files with more than {T['file_loc_max']} LOC (CWE-1080)", len(oversized))
    crit = {"C1": c1, "C2": c2, "C3": c3, "C4": c4}
    apply_manual("cohesion", crit, manual)
    ev = [f"{f['file']}:{f['line']} {f['name']} (fan-out={f['fanout']})" for f in sorted(hi, key=lambda f: -f["fanout"])[:5]] + gods[:3] \
        + [f"{p_}: {l} LOC" for p_, l in oversized[:3]]
    il = (manual.get("dv8") or {}).get("IL")
    return crit, {"pct_fanout": p, "suggested_god_modules": gods, "oversized_files": len(oversized), "IL": il}, ev, \
        f"{len(hi)} of {len(fns)} functions with fan-out > {T['fanout_max']}; {len(gods)} candidate 'god' module(s); {len(oversized)} file(s) over {T['file_loc_max']} LOC.", None
