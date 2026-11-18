"""Scoring (protocol step 9): the 11 points with their level, severity and confidence, the maintainability profile per
subcharacteristic, the judge and live-database inputs, and the ranked risk list.
"""
import json
import re
from pathlib import Path

from evaluator.artifacts import artifact_findings
from evaluator.ascmm import ascmm_profile
from evaluator.common import RUBRIC
from evaluator.criteria import level_from, pdict
from evaluator.points import EVALUATORS, MUST


# What the README usually says about each point (used to detect declared-vs-implemented gaps)
# Whole words only: a bare "log" matched "login"/"catalog", "api" matched every README with an /api route, "index" matched index.js.
DECLARED_PATTERNS = {"layers": r"\blayer(s|ed)?\b|\bcontrollers?\b|\bservices? layer\b|\brepositor(y|ies)\b",
                     "cyclomatic": None, "cohesion": r"\bcohesi(on|ve)\b|\bresponsibilit(y|ies)\b|single[- ]responsibility",
                     "hierarchies": None, "technologies": r"\bversions?\b|\bstack\b|\breact\b|\bexpress\b",
                     "coupling": r"\bcoupl(ed|ing)\b|dependency injection|\bdecoupl",
                     "data_model": r"\bschema\b|data model|entity[- ]relationship|\bindex(es)? on\b|\bindexes\b",
                     "contracts": r"\bopenapi\b|\bswagger\b|\bapi contract\b|\bapi spec(ification)?\b",
                     "observability": r"\blogg(ing|er)\b|\bwinston\b|\bpino\b|health[- ]?check|\bobservab|\bmetrics\b",
                     "tests": r"\b(unit|integration|automated) tests?\b|\bjest\b|\bvitest\b|node --test|\bcoverage\b|npm (run )?test",
                     "configuration": r"\.env\b|environment variables?|\bconfiguration\b"}


def evaluate_points(m, manual, opts):
    pts = []
    sc = RUBRIC["level_score"]
    for pid, fn in EVALUATORS.items():
        arts = [a for a in (m.get("artifacts") or []) if pid in a["feeds"]]
        miss_core = [a for a in arts if a["level"] == "core" and not a["present"]]
        miss_comp = [a for a in arts if a["level"] == "complementary" and not a["present"]]
        evaluable = not miss_core
        if evaluable:
            crits, met, ev, finding, forced = fn(m, manual, opts)
        else:  # a core artifact is missing: the point cannot be evaluated (this is not "Meets")
            crits, met, ev, forced = {}, {}, [], (None, None, None)
            finding = "Not evaluable: missing core artifact(s): " + ", ".join(a["name"] for a in miss_core) + "."
        if forced and (forced[0] or forced[1] != forced[2]):  # forced, or pending range (level None, lo ≠ hi)
            level, lo, hi = forced
        elif crits:
            level, lo, hi = level_from(crits, MUST.get(pid, ()))
        else:
            level = lo = hi = None
        pend = [k for k, v in crits.items() if v["ok"] is None]
        declared = bool(re.search(DECLARED_PATTERNS[pid], m["readme"], re.I)) if (m["readme"] and DECLARED_PATTERNS[pid]) else False
        gap = None
        if DECLARED_PATTERNS[pid]:  # only points whose decision is usually declared in the documentation
            if level == "Fails" and declared: gap = "declared but not supported by the structure"
            elif level == "Meets" and not declared: gap = "implemented but not declared"
        art_findings = [{"artifact": a["id"], "name": a["name"], "severity": "Critical" if a.get("absence") == "high_finding" else "Marginal"} for a in miss_comp]
        severity = RUBRIC["level_severity"].get(level) if level else ("Undetermined" if lo != hi else None)
        if not evaluable:
            severity = "Not evaluable"
        elif any(f["severity"] == "Critical" for f in art_findings):
            severity = "Critical"  # a Critical finding (IEEE 1028, 6.8.3) forces the top rank in use even if the level is better
        confidence = "n/a" if not evaluable else ("high" if not miss_comp else ("medium" if len(miss_comp) == 1 else "low"))
        pts.append({**pdict(pid), "level": level, "level_min": lo, "level_max": hi,
                    "evaluable": evaluable, "confidence": confidence, "missing_artifacts": [a["id"] for a in miss_core + miss_comp],
                    "artifact_findings": art_findings,
                    "complete": level is not None, "pending_criteria": pend,
                    "severity": severity,
                    "finding": finding, "metrics": met, "criteria": crits, "evidence": ev,
                    "weaknesses": [f"{k}: {v['desc']} → {v['value']}" for k, v in crits.items() if v["ok"] is False],
                    "declared_in_readme": declared, "declarative_gap": gap,
                    "score_min": sc[lo] if lo else None, "score_max": sc[hi] if hi else None})
    return pts


def load_pg(out, m):
    """Adds to `m` what pg_analysis.py dumped (<out>/pg_schema.json): the catalog of the real database. Without the file the static
    schema is used."""
    f = Path(out) / "pg_schema.json"
    if f.exists():
        m["pg"] = json.loads(f.read_text(encoding="utf-8"))
    else:
        m.pop("pg", None)
    return m


def load_conformance(out, m):
    """Adds to `m` the runtime conformance to the OpenAPI contract (<out>/contract_conformance.json, written by acceptance_check.py
    --app through Prism). Informational: it feeds the metrics of the Contracts point, never its level."""
    f = Path(out) / "contract_conformance.json"
    if f.exists():
        m["conformance"] = json.loads(f.read_text(encoding="utf-8"))
    else:
        m.pop("conformance", None)
    return m


def load_judge(out, manual):
    """Adds to `manual` the judge's decisions (<out>/judge.json) under the private key '_judge'; removes it if there is no file."""
    f = Path(out) / "judge.json"
    if f.exists():
        manual["_judge"] = json.loads(f.read_text(encoding="utf-8"))
    else:
        manual.pop("_judge", None)
    return manual


def evaluate_profile(m, manual, opts):
    """Points and profile with the judge's decisions; if there are any, adds the range that results without them (`without_judge`)."""
    pts = evaluate_points(m, manual, opts); prof = profile(pts)
    prof["not_evaluable"] = [p["id"] for p in pts if not p["evaluable"]]
    prof["artifact_findings"] = artifact_findings(m)
    prof["ascmm"] = ascmm_profile(m, pts)  # ISO/IEC 5055 occurrences and density per KLOC (informational)
    if manual.get("_judge"):
        without = profile(evaluate_points(m, {k: v for k, v in manual.items() if k != "_judge"}, opts))
        prof["without_judge"] = {"min": without["maintainability_min"], "max": without["maintainability_max"], "complete": without["complete"]}
        prof["judge_criteria"] = sorted(f"{p['id']}.{c}" for p in pts for c, v in p["criteria"].items() if str(v["source"]).startswith("judge"))
        prof["judge_model"] = manual["_judge"].get("meta", {}).get("judge_model")
        prof["judge_audit"] = manual["_judge"].get("audit", [])
    return pts, prof


def profile(points):
    W = RUBRIC["subcharacteristic_weights"]; subs = {}
    for s in W:
        ps = [p for p in points if s in p["subcharacteristics"] and p["score_min"] is not None]
        tot = [p for p in points if s in p["subcharacteristics"]]
        lo = sum(p["score_min"] for p in ps) / len(ps) if ps else None
        hi = sum(p["score_max"] for p in ps) / len(ps) if ps else None
        subs[s] = {"weight": W[s], "points": [p["id"] for p in tot], "evaluable_points": len(ps),
                   "min": None if lo is None else round(100 * lo, 1), "max": None if hi is None else round(100 * hi, 1)}
    ok = all(v["min"] is not None for v in subs.values())
    lo = round(sum(v["weight"] * v["min"] for v in subs.values() if v["min"] is not None), 1) if ok else None
    hi = round(sum(v["weight"] * v["max"] for v in subs.values() if v["max"] is not None), 1) if ok else None
    return {"subcharacteristics": subs, "maintainability_min": lo, "maintainability_max": hi,
            "complete": all(p["complete"] for p in points)}


TRAFFIC = {"Meets": "🟢", "Partial": "🟡", "Fails": "🔴"}


PENDING_LIGHT = "⚪"


def traffic_light(point):
    """Traffic light of a point: green/yellow/red when its level is decided, white when it is still a range."""
    return TRAFFIC.get(point["level"], PENDING_LIGHT)


def risk_summary(points):
    """Condensed risk view: every point with its traffic light and the overall-score points it puts at stake.

    A point's impact is how many of the 100 overall points it controls: each subcharacteristic it feeds gives it
    weight / (number of points in that subcharacteristic). `at_stake_max` is the loss in the worst case (lowest score
    of the range) and `at_stake_min` in the best case; pending points still rank by their worst case.
    Returns the list sorted from highest to lowest risk."""
    W = RUBRIC["subcharacteristic_weights"]
    count = {s: sum(1 for p in points if s in p["subcharacteristics"]) for s in W}
    rows = []
    for p in points:
        if p["score_min"] is None:
            continue
        impact = 100 * sum(W[s] / count[s] for s in p["subcharacteristics"] if s in W)
        rows.append({"id": p["id"], "name": p["name"], "light": traffic_light(p), "level": p["level"],
                     "level_min": p["level_min"], "level_max": p["level_max"], "pending": p["pending_criteria"],
                     "impact": round(impact, 1),
                     "at_stake_min": round((1 - p["score_max"]) * impact, 1),
                     "at_stake_max": round((1 - p["score_min"]) * impact, 1)})
    return sorted(rows, key=lambda r: (-r["at_stake_max"], -r["at_stake_min"], r["id"]))
