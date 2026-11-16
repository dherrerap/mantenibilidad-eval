"""Criteria and levels: how a criterion is built, how manual review and the judge fill it, and how a level (or a range of
levels, when criteria are pending) follows from the criteria (Table 26).
"""

from evaluator.common import RUBRIC


def C(ok, desc, value=None, source="auto", suggested=None):
    return {"ok": ok, "desc": desc, "value": value, "source": source, "suggested": suggested}


def apply_manual(pid, crits, manual):
    for cid, v in (manual.get(pid) or {}).items():
        if cid in crits and cid != "note":
            ok = v.get("ok") if isinstance(v, dict) else v
            if ok is None:
                continue
            crits[cid]["ok"] = bool(ok)
            crits[cid]["source"] = "manual"
            if isinstance(v, dict) and v.get("note"):
                crits[cid]["value"] = v["note"]
    # the judge (judge.py) only fills what is still pending: manual review and automatic measurements take precedence
    jz = manual.get("_judge") or {}
    for cid, d in (jz.get("decisions", {}).get(pid) or {}).items():
        if cid in crits and crits[cid]["ok"] is None and d.get("ok") is not None:
            crits[cid]["ok"] = bool(d["ok"])
            crits[cid]["source"] = f"judge ({jz.get('meta', {}).get('judge_model', '?')})"
            crits[cid]["value"] = d.get("justification") or crits[cid]["value"]


def heur(crit, opts):
    """Heuristic-source criterion: only counts if heuristics are accepted."""
    if crit["suggested"] is not None:
        crit["source"] = "heuristic"
        crit["ok"] = crit["suggested"] if opts.accept_heuristics else None
    return crit


def level_from(crits, must=()):
    """Returns (level, level_min, level_max). None in a criterion = pending."""
    pm = RUBRIC["partial_min_fraction"]

    def lvl(vals):
        if any(not vals[k] for k in must if k in vals):
            return "Fails"
        n, k = len(vals), sum(vals.values())
        return "Meets" if k == n else ("Partial" if k / n >= pm else "Fails")

    lo = lvl({k: bool(v["ok"]) for k, v in crits.items()})
    hi = lvl({k: (True if v["ok"] is None else bool(v["ok"])) for k, v in crits.items()})
    return (lo if lo == hi else None), lo, hi


def level_from_pct(value, meets_ok, partial_ok):
    return "Meets" if meets_ok(value) else ("Partial" if partial_ok(value) else "Fails")


def pdict(pid):
    d = RUBRIC["points"][pid]
    return {"id": pid, **d}
