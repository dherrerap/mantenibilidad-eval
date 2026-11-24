"""The Automated Source Code Maintainability Measure (ISO/IEC 5055:2021) of a run: the occurrences of every weakness the framework
detects, with their density per KLOC of production code.

ISO/IEC 5055 measures maintainability by counting the occurrences of its 29 weaknesses, and Annex C.1 proposes normalizing that count
by size (ASCMM-density = ASCMM / AFP) to compare applications of different size. Automated Function Points are not computed here, so
the size is the KLOC of production code (`backing._coverage_ascmm.normalization`). Applications generated at N1 and N3 differ in size,
so a count alone favours the smaller one.

The 15 scored weaknesses take their count from the decision point that scores them (the same value that decided its criterion, so
the density can never contradict the level), the 7 informational ones from the supplementary indicators (group ASCMM). A count is None
when it was not measured (a pending criterion, a tool that did not run, a point that is not evaluable); the totals then carry `≥`.
"""
from evaluator.common import RUBRIC
from evaluator.supplementary import ascmm_indicators


def crit_value(pt, cid, key=None):
    """Integer count kept in a criterion's value: an int, a dict entry (`key`), the size of a dict or list; None if not measured."""
    c = (pt.get("criteria") or {}).get(cid)
    if not c:
        return None
    v = c.get("value")
    if key is not None:
        return v.get(key) if isinstance(v, dict) else None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, (dict, list)):
        return len(v)
    return None


def met_value(pt, key):
    v = (pt.get("metrics") or {}).get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# (CWE, ISO/IEC 5055 title, what one occurrence is, point, count from the point's result)
SCORED = [
    ("CWE-478", "Missing Default Case in Multiple Condition Expression", "switch", "tests", lambda p: crit_value(p, "C1", "switch_without_default")),
    ("CWE-484", "Omitted Break Statement in Switch", "case", "tests", lambda p: crit_value(p, "C1", "fallthrough")),
    ("CWE-561", "Dead Code", "file", "coupling", lambda p: crit_value(p, "C5")),
    ("CWE-1041", "Use of Redundant Code", "clone", "cyclomatic", lambda p: met_value(p, "clones")),
    ("CWE-1047", "Modules with Circular Dependencies", "cycle", "coupling", lambda p: crit_value(p, "C1")),
    ("CWE-1048", "Invokable Control Element with Large Number of Outward Calls", "function", "cohesion", lambda p: met_value(p, "functions_fanout_above")),
    ("CWE-1051", "Initialization with Hard-Coded Network Resource Configuration Data", "literal", "configuration", lambda p: crit_value(p, "C1")),
    ("CWE-1052", "Excessive Use of Hard-Coded Literals in Initialization", "literal", "configuration", lambda p: crit_value(p, "C2")),
    ("CWE-1054", "Invocation of a Control Element at an Unnecessarily Deep Horizontal Layer", "dependency", "layers", lambda p: met_value(p, "violations")),
    ("CWE-1062", "Parent Class with References to Child Class", "pattern", "hierarchies", lambda p: crit_value(p, "C3")),
    ("CWE-1074", "Class with Excessively Deep Inheritance", "class", "hierarchies", lambda p: crit_value(p, "C1")),
    ("CWE-1075", "Unconditional Control Flow Transfer outside of Switch Block", "jump", "tests", lambda p: crit_value(p, "C1", "labeled_jumps")),
    ("CWE-1080", "Source Code File with Excessive Number of Lines of Code", "file", "cohesion", lambda p: crit_value(p, "C4")),
    ("CWE-1086", "Class with Excessive Number of Child Classes", "class", "hierarchies", lambda p: crit_value(p, "C2")),
    ("CWE-1121", "Excessive McCabe Cyclomatic Complexity", "function", "cyclomatic", lambda p: met_value(p, "functions_cc_above_threshold")),
]


def per_kloc(n, kloc):
    return None if n is None or not kloc else round(n / kloc, 3)


def ascmm_profile(m, points):
    """{"kloc", "weaknesses": [{cwe, name, unit, point, scored, count, per_kloc}], "scored" / "all": {"occurrences", "per_kloc",
    "complete", "not_measured"}}. `occurrences` sums the measured counts: with `complete` False it is a lower bound."""
    kloc = round(sum(f["loc"] for f in m["ast"]["files"] if not f["test"]) / 1000.0, 3)
    pts = {p["id"]: p for p in points}
    rows = []
    for cwe, name, unit, pid, get in SCORED:
        pt = pts.get(pid) or {}
        # a not-applicable point measured the app and found nothing to evaluate (no own inheritance hierarchy): zero occurrences, not "not measured"
        n = None if not pt.get("evaluable", True) else 0 if pt.get("applicable", True) is False else get(pt)
        rows.append({"cwe": cwe, "name": name, "unit": unit, "point": pid, "scored": True, "count": n, "per_kloc": per_kloc(n, kloc)})
    for r in ascmm_indicators(m):  # (id, group, name, value, reference, ok, detail, evidence)
        cwe, _, name = r[2].partition(" ")
        rows.append({"cwe": cwe, "name": name, "unit": "function" if cwe in ("CWE-1064", "CWE-1085") else "occurrence", "point": None,
                     "scored": False, "count": r[3], "per_kloc": per_kloc(r[3], kloc)})

    def total(rs):
        n = sum(r["count"] for r in rs if r["count"] is not None)
        missing = [r["cwe"] for r in rs if r["count"] is None]
        return {"occurrences": n, "per_kloc": per_kloc(n, kloc), "complete": not missing, "not_measured": missing}
    return {"kloc": kloc, "size_basis": "KLOC of production code (ISO/IEC 5055 Annex C.1 uses AFP)", "weaknesses": rows,
            "scored": total([r for r in rows if r["scored"]]), "all": total(rows)}


def fmt_total(t):
    lo = "" if t["complete"] else "≥ "
    return f"{lo}{t['occurrences']} ({lo}{t['per_kloc'] if t['per_kloc'] is not None else 'n/a'}/KLOC)"


COLUMNS = ("kloc", "ascmm_scored", "ascmm_scored_per_kloc", "ascmm_all", "ascmm_all_per_kloc", "ascmm_complete")


def ascmm_columns(prof):
    """Values of COLUMNS for comparison.csv (a total with ascmm_complete False is a lower bound); None for an older profile."""
    a = prof.get("ascmm")
    if not a:
        return [None] * len(COLUMNS)
    return [a["kloc"], a["scored"]["occurrences"], a["scored"]["per_kloc"], a["all"]["occurrences"], a["all"]["per_kloc"], a["all"]["complete"]]


def ascmm_comparison_md(runs):
    """Section of comparison.md and report.md: runs = [(run_id, profile)]."""
    rows = [(r, p["ascmm"]) for r, p in runs if p.get("ascmm")]
    if not rows:
        return []
    L = ["## ISO/IEC 5055 weaknesses (ASCMM)", "",
         "Occurrences of the detected weaknesses and their density per KLOC of production code: compare densities, since the applications "
         "differ in size (ISO/IEC 5055 Annex C.1). ≥ = some weakness not measured, so the total is a lower bound.", "",
         "| Run | KLOC | Scored | Scored / KLOC | All detected | All / KLOC |", "|---|---|---|---|---|---|"]
    for r, a in rows:
        ge = lambda t: "" if t["complete"] else "≥ "  # noqa: E731
        L.append(f"| {r} | {a['kloc']} | {ge(a['scored'])}{a['scored']['occurrences']} | {ge(a['scored'])}{a['scored']['per_kloc']} | "
                 f"{ge(a['all'])}{a['all']['occurrences']} | {ge(a['all'])}{a['all']['per_kloc']} |")
    cwes = [w["cwe"] for w in rows[0][1]["weaknesses"]]
    L += ["", "Per weakness (occurrences / per KLOC):", "", "| CWE | " + " | ".join(r for r, _ in rows) + " |", "|---|" + "---|" * len(rows)]
    for c in cwes:
        cells = []
        for _, a in rows:
            w = next((x for x in a["weaknesses"] if x["cwe"] == c), None)
            cells.append("n/a" if not w or w["count"] is None else f"{w['count']} / {w['per_kloc']}")
        L.append(f"| {c} | " + " | ".join(cells) + " |")
    return L + [""]


def ascmm_markdown(a):
    """Section of profile.md."""
    cov = RUBRIC["backing"]["_coverage_ascmm"]
    L = ["## ISO/IEC 5055 weaknesses (ASCMM)", "",
         f"Occurrences of every weakness the framework detects ({len(cov['scored'])} scored, {len(cov['informational'])} informational, "
         f"{len(cov['not_detected'])} of the {cov['applicable']} applicable not detected), and their density per KLOC of production code "
         f"({a['kloc']} KLOC; ISO/IEC 5055 Annex C.1 normalizes by AFP, which is not computed). n/a = not measured.", "",
         "| CWE | Weakness | Occurrences | Per KLOC | Counted as | Scored in |", "|---|---|---|---|---|---|"]
    for r in a["weaknesses"]:
        L.append(f"| {r['cwe']} | {r['name']} | {'n/a' if r['count'] is None else r['count']} | {'n/a' if r['per_kloc'] is None else r['per_kloc']} | "
                 f"{r['unit']} | {r['point'] or 'informational'} |")
    L += ["", f"**ASCMM, scored weaknesses:** {fmt_total(a['scored'])} · **all detected:** {fmt_total(a['all'])}"
              + (f". Not measured: {', '.join(a['all']['not_measured'])}." if a["all"]["not_measured"] else "."), ""]
    return L
