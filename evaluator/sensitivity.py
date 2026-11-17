"""Sensitivity of the overall score to the weighting scheme.

The subcharacteristic weights (30/24/24/22) come from a panel whose concordance is not significant (Kendall's W = 0.158,
`backing.subcharacteristic_weights`), so a conclusion drawn from the overall score must hold under other reasonable weights.
Each run is scored again from its points under these scenarios:

- `panel`: the weights of `subcharacteristic_weights` (the reference).
- `uniform`: 25% per subcharacteristic.
- every weight set in `sensitivity.weight_sets` of rubric.json (for example each expert's own Borda weights), normalized to 1.
- `equal_points`: the plain mean of the evaluable points, without subcharacteristics (a point counts once however many it feeds).
- `without_<point>`: the panel weights with that point removed from every subcharacteristic (leave-one-out).

For each scenario it reports the score of every run, the ranking of the runs and its agreement with the panel ranking (Kendall's
tau-b, whether the top run is the same, the largest rank shift), and the order of the levels and agents by mean score.
Rankings use the midpoint of each score range; a run whose overall score is not computable in a scenario stays out of it.
"""
from evaluator.common import RUBRIC

GROUP_KEYS = ("level", "agent")


def scenarios():
    """[(name, description, spec)], spec = {"weights": {...}} | {"flat": True} | {"weights": …, "drop": pid}."""
    W = RUBRIC["subcharacteristic_weights"]
    out = [("panel", "panel weights " + "/".join(f"{100 * w:g}" for w in W.values()), {"weights": W}),
           ("uniform", "25% per subcharacteristic", {"weights": {s: 1 / len(W) for s in W}})]
    for name, ws in (RUBRIC.get("sensitivity", {}).get("weight_sets") or {}).items():
        if name.startswith("_"):
            continue
        tot = sum(ws.get(s, 0) for s in W)
        if tot > 0:
            out.append((name, "weight set " + name, {"weights": {s: ws.get(s, 0) / tot for s in W}}))
    out.append(("equal_points", "every evaluable point with the same weight", {"flat": True}))
    out += [(f"without_{pid}", f"panel weights without {pid}", {"weights": W, "drop": pid}) for pid in RUBRIC["points"]]
    return out


def overall(points, spec):
    """(min, max) of the overall score of a run under `spec`, with the same rules as scoring.profile(): a subcharacteristic is the
    mean of its evaluable points and the total needs every subcharacteristic with a positive weight to have one. (None, None) if not."""
    ps = [p for p in points if p.get("score_min") is not None and p["id"] != spec.get("drop")]
    if spec.get("flat"):
        if not ps:
            return None, None
        return tuple(round(100 * sum(p[k] for p in ps) / len(ps), 1) for k in ("score_min", "score_max"))
    lo = hi = 0.0
    for s, w in spec["weights"].items():
        sub = [p for p in ps if s in p["subcharacteristics"]]
        if not sub:
            if w > 0:
                return None, None
            continue
        lo += w * 100 * sum(p["score_min"] for p in sub) / len(sub)
        hi += w * 100 * sum(p["score_max"] for p in sub) / len(sub)
    return round(lo, 1), round(hi, 1)


def ranks(values):
    """{key: rank} with 1 = highest value; ties share the mean rank."""
    order = sorted(values, key=lambda k: -values[k]); out = {}; i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in order[i:j + 1]:
            out[k] = int(r) if r == int(r) else r
        i = j + 1
    return out


def kendall_tau_b(a, b):
    """Kendall's tau-b between two {key: value} maps over their common keys; None with fewer than 2 keys or a constant side."""
    ks = [k for k in a if k in b]
    if len(ks) < 2:
        return None
    conc = disc = ta = tb = 0
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            x = (a[ks[i]] > a[ks[j]]) - (a[ks[i]] < a[ks[j]]); y = (b[ks[i]] > b[ks[j]]) - (b[ks[i]] < b[ks[j]])
            if x == 0 and y == 0:
                continue
            if x == 0:
                ta += 1
            elif y == 0:
                tb += 1
            elif x == y:
                conc += 1
            else:
                disc += 1
    den = ((conc + disc + ta) * (conc + disc + tb)) ** 0.5
    return None if den == 0 else round((conc - disc) / den, 3)


def group_order(mids, meta, key):
    """Groups (levels or agents) ordered by mean midpoint, best first: [(group, mean)]."""
    g = {}
    for r, v in mids.items():
        g.setdefault(meta[r].get(key) or "?", []).append(v)
    return sorted(((k, round(sum(v) / len(v), 1)) for k, v in g.items()), key=lambda x: (-x[1], x[0]))


def sensitivity(runs):
    """runs: [(meta, points)] → dict with the scenarios, the per-run summary and the stability verdicts (see the module docstring)."""
    meta = {m["run_id"]: m for m, _ in runs}; out = {"scenarios": [], "runs": {}, "groups": {}}
    ref_mid = ref_rank = ref_groups = None
    for name, desc, spec in scenarios():
        scores = {m["run_id"]: overall(pts, spec) for m, pts in runs}
        mids = {r: round((lo + hi) / 2, 2) for r, (lo, hi) in scores.items() if lo is not None}
        rk = ranks(mids)
        groups = {k: group_order(mids, meta, k) for k in GROUP_KEYS}
        sc = {"name": name, "description": desc, "scores": {r: list(v) for r, v in scores.items()}, "ranks": rk, "groups": groups}
        if name == "panel":
            ref_mid, ref_rank, ref_groups = mids, rk, groups
        else:
            common = [r for r in rk if r in ref_rank]
            top = lambda x: {r for r in x if x[r] == 1}  # noqa: E731
            sc.update({"tau_b": kendall_tau_b(ref_mid, mids), "same_top": bool(common) and top(rk) == top(ref_rank),
                       "max_rank_shift": max((abs(rk[r] - ref_rank[r]) for r in common), default=0),
                       "groups_same_order": {k: [g for g, _ in groups[k]] == [g for g, _ in ref_groups[k]] for k in GROUP_KEYS}})
        out["scenarios"].append(sc)
    for m, _ in runs:
        r = m["run_id"]; rs = [s["ranks"][r] for s in out["scenarios"] if r in s["ranks"]]
        sv = [v for s in out["scenarios"] for v in s["scores"][r] if v is not None]
        out["runs"][r] = {"panel_rank": ref_rank.get(r), "best_rank": min(rs, default=None), "worst_rank": max(rs, default=None),
                          "score_low": min(sv, default=None), "score_high": max(sv, default=None)}
    alt = [s for s in out["scenarios"] if s["name"] != "panel"]
    out["stable"] = {"top": all(s["same_top"] for s in alt),
                     **{k: all(s["groups_same_order"][k] for s in alt) for k in GROUP_KEYS},
                     "min_tau_b": min((s["tau_b"] for s in alt if s["tau_b"] is not None), default=None)}
    out["changes"] = {"top": [s["name"] for s in alt if not s["same_top"]],
                      **{k: [s["name"] for s in alt if not s["groups_same_order"][k]] for k in GROUP_KEYS}}
    return out


def fmt_score(v):
    lo, hi = v
    if lo is None:
        return "n/a"
    return f"{lo:.1f}" if lo == hi else f"{lo:.1f}–{hi:.1f}"


def fmt_rank(x):
    return "—" if x is None else (f"{x:g}")


def sensitivity_md(s, heading="##"):
    """Markdown section of the report."""
    runs = list(s["runs"]); alt = [x for x in s["scenarios"] if x["name"] != "panel"]
    L = [f"{heading} Weight sensitivity", "",
         "The panel weights have a non-significant concordance (Kendall's W = 0.158), so every run is scored again under other weights: "
         "uniform 25%, every point with the same weight, each point removed in turn" +
         (", and the weight sets of `sensitivity.weight_sets` in `rubric.json`" if any(not x["name"].startswith(("uniform", "equal_points", "without_")) for x in alt) else "") +
         ". Ranks use the midpoint of each score range (1 = best). τ = Kendall's tau-b against the panel ranking.", ""]
    if len(runs) < 2:
        return L + ["A single run: there is no ranking to compare. Scores per scenario are in `_comparison/sensitivity.json`.", ""]
    st, ch = s["stable"], s["changes"]
    verdict = lambda ok, names: "holds in every scenario" if ok else "changes under " + ", ".join(f"`{n}`" for n in names)  # noqa: E731
    L += [f"- **Best run**: {verdict(st['top'], ch['top'])}.",
          f"- **Order of the levels** by mean score: {verdict(st['level'], ch['level'])}.",
          f"- **Order of the agents** by mean score: {verdict(st['agent'], ch['agent'])}.",
          f"- **Lowest τ** against the panel ranking: {'n/a' if st['min_tau_b'] is None else st['min_tau_b']}.", "",
          "| Scenario | " + " | ".join(runs) + " | τ | Best run same | Levels | Agents |", "|---|" + "---|" * (len(runs) + 4)]
    for x in s["scenarios"]:
        cells = [f"{fmt_score(x['scores'][r])} (#{fmt_rank(x['ranks'].get(r))})" for r in runs]
        if x["name"] == "panel":
            L.append("| **panel** | " + " | ".join(cells) + " | — | — | " + " > ".join(g for g, _ in x["groups"]["level"]) + " | " + " > ".join(g for g, _ in x["groups"]["agent"]) + " |")
        else:
            yn = lambda b: "yes" if b else "**no**"  # noqa: E731
            L.append(f"| {x['name']} | " + " | ".join(cells) + f" | {'n/a' if x['tau_b'] is None else x['tau_b']} | {yn(x['same_top'])} | "
                     f"{yn(x['groups_same_order']['level'])} | {yn(x['groups_same_order']['agent'])} |")
    L += ["", "| Run | Panel rank | Rank across scenarios | Overall across scenarios |", "|---|---|---|---|"]
    for r, v in s["runs"].items():
        L.append(f"| {r} | {fmt_rank(v['panel_rank'])} | {fmt_rank(v['best_rank'])}–{fmt_rank(v['worst_rank'])} | "
                 f"{fmt_score((v['score_low'], v['score_high']))} |")
    return L + [""]
