"""Decision point *Tests* (Testability): C1 CWE-478/484/1075, C2 tests exist and pass, C3 line coverage, C4 branch coverage.
With --mutation, the mutation score of StrykerJS is reported next to them (informational).
"""

from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual


def eval_tests(m, manual, opts):
    T = RUBRIC["thresholds"]["tests"]; a = m["ast"]
    bad = len(a["switchesMissingDefault"]) + len(a["fallthrough"]) + len(a["labeledJumps"])
    ts = m["tests_static"]; tr = m["tests_run"]; exist = ts["test_cases"] > 0
    c2 = False if not exist else (None if not tr["executed"] or not tr.get("ran_any") else tr["all_passed"])
    lines = branches = None
    no_branches = False  # coverage was measured but the report has no branches: C4 does not apply (it is not a 0%)
    if tr["executed"] and tr.get("lines_total"):
        lines = 100.0 * tr["lines_cov"] / tr["lines_total"]
        branches = 100.0 * tr["br_cov"] / tr["br_total"] if tr["br_total"] else None
        no_branches = not tr["br_total"]
    def cov_ok(v, thr):
        if not exist: return False
        return None if v is None else v >= thr
    crit = {"C1": C(bad == 0, "0 CWE-478/484/1075 violations", {"switch_without_default": len(a["switchesMissingDefault"]), "fallthrough": len(a["fallthrough"]), "labeled_jumps": len(a["labeledJumps"])}),
            "C2": C(c2, "Tests exist and pass", f"{ts['test_cases']} cases in {len(ts['test_files'])} files", source="auto" if c2 is not None else "pending (--run-tests)"),
            "C3": C(cov_ok(lines, T["lines_min"]), "Line coverage ≥ 70%", None if lines is None else round(lines, 1), source="auto" if (lines is not None or not exist) else "pending (--run-tests)"),
            "C4": C(cov_ok(branches, T["branches_min"]), "Branch coverage ≥ 50%", None if branches is None else round(branches, 1), source="auto" if (branches is not None or not exist) else "pending (--run-tests)")}
    if no_branches and exist:
        del crit["C4"]  # not applicable: the level is decided by C1–C3
    apply_manual("tests", crit, manual)
    ev = [f"switch without default {x['file']}:{x['line']}" for x in a["switchesMissingDefault"][:3]] + ts["test_files"][:3]
    met = {"cases": ts["test_cases"], "line_coverage": lines, "branch_coverage": branches}
    finding = f"{ts['test_cases']} test cases; line coverage {'n/a' if lines is None else f'{lines:.0f}%'}, branches " \
        f"{'not measured by the coverage report (C4 not applicable)' if no_branches else ('n/a' if branches is None else f'{branches:.0f}%')}."
    mmet, mev, mtxt = mutation_measure(m)
    met.update(mmet)
    return crit, met, ev + mev, finding + mtxt, None


def mutation_measure(m):
    """Informational: the mutation score of StrykerJS (evaluator/collectors/mutation.py), only when the run used --mutation."""
    mu = m.get("mutation")
    if not mu:
        return {}, [], ""
    if not mu.get("ok"):
        return {"mutation_score": None}, [], f" Mutation score not measured ({mu.get('error')})."
    st = mu["statuses"]; det = st.get("Killed", 0) + st.get("Timeout", 0); und = st.get("Survived", 0) + st.get("NoCoverage", 0)
    surv = [s for p in mu["packages"] if p.get("ok") for s in p.get("survivors", [])]
    return ({"mutation_score": mu["score"], "mutants": sum(st.values()), "mutants_detected": det, "mutants_undetected": und},
            [f"surviving mutant: {s}" for s in surv[:3]],
            f" Mutation score ({mu['tool']}): {mu['score']}% ({det} of {det + und} valid mutants detected by the tests; informational).")
