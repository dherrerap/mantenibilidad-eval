"""Files written for each run (scorecard, profile, traceability, dashboard, manual template) and the token columns of the
comparison.
"""
import csv
import json

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import token_usage as tu  # noqa: E402
from evaluator.common import MODEL_WARNING, model_missing
from evaluator.dashboard import dashboard_html, dashboard_markdown, risk_dashboard
from evaluator.scoring import risk_summary
from evaluator.supplementary import supplementary_indicators


def fmt_rng(a, b):
    return "n/a" if a is None else (f"{a:.1f}" if a == b else f"{a:.1f}–{b:.1f}")


def artifacts_markdown(m):
    arts = m.get("artifacts") or []
    if not arts:
        return []
    L = ["## Input artifacts (Table 27)", "", "| Artifact | Level | Present | Detail | Feeds |", "|---|---|---|---|---|"]
    L += [f"| {a['name']} | {a['level']} | {'yes' if a['present'] else 'no'} | {a['detail']} | {', '.join(a['feeds']) or '—'} |" for a in arts]
    return L + [""]


def write_outputs(out, meta, points, prof, m):
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps({"meta": meta, "points": points}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    risk = risk_summary(points)
    dash = risk_dashboard(points, prof, m)
    (out / "profile.json").write_text(json.dumps({"meta": meta, **prof, "risk": risk, "dashboard": dash}, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "artifacts.json").write_text(json.dumps(m.get("artifacts") or [], indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "risk_dashboard.json").write_text(json.dumps(dash, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "risk_dashboard.md").write_text(chr(10).join(dashboard_markdown(dash, points)), encoding="utf-8")
    (out / "risk_dashboard.html").write_text(dashboard_html(dash, points, f"Risk dashboard — {meta.get('run_id')}"), encoding="utf-8")
    with open(out / "scorecard.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["point", "category", "level", "level_min", "level_max", "severity", "confidence", "missing_artifacts", "pending_criteria", "finding", "evidence"])
        for p in points:
            w.writerow([p["name"], p["category"], p["level"] or ("not evaluable" if not p["evaluable"] else "pending"), p["level_min"], p["level_max"], p["severity"], p["confidence"], " ".join(p["missing_artifacts"]), " ".join(p["pending_criteria"]), p["finding"], " | ".join(p["evidence"][:5])])
    with open(out / "traceability.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["design_decision", "detected_weakness", "affected_subcharacteristics", "level", "evidence", "declarative_gap"])
        for p in points:
            w.writerow([p["finding"], "; ".join(p["weaknesses"]) or "—", ", ".join(p["subcharacteristics"]), p["level"] or "pending", " | ".join(p["evidence"][:5]), p["declarative_gap"] or ""])
    comp = supplementary_indicators(m)
    (out / "supplementary.json").write_text(json.dumps(comp, indent=1, ensure_ascii=False), encoding="utf-8")
    L = [f"# Maintainability profile — {meta.get('run_id')}", "",
         f"Agent: {meta.get('agent')} · Model: {'NOT RECORDED' if model_missing(meta.get('model')) else meta.get('model')} · Prompt level: {meta.get('level')} · Domain: {meta.get('domain')} · {m['date']}", "",
         *([f"> ⚠ **Generator model not recorded.** {MODEL_WARNING}", ""] if model_missing(meta.get("model")) else []),
         f"**Overall maintainability: {fmt_rng(prof['maintainability_min'], prof['maintainability_max'])} / 100**" + ("" if prof["complete"] else "  _(range: there are pending criteria; see manual.template.json)_"), "",
         "| Subcharacteristic | Weight | Score |", "|---|---|---|"]
    for s, v in prof["subcharacteristics"].items():
        L.append(f"| {s} | {int(v['weight'] * 100)}% | {fmt_rng(v['min'], v['max'])} |")
    if prof.get("judge_criteria"):
        L += ["", f"> **Judge decisions ({prof['judge_model']}):** {', '.join(prof['judge_criteria'])}. "
                  f"Without them the result would be {fmt_rng(prof['without_judge']['min'], prof['without_judge']['max'])}. "
                  f"For a person to review: {', '.join(prof['judge_audit']) or '—'}."]
    L += [""] + dashboard_markdown(dash, points) + artifacts_markdown(m)
    L += ["## Risk map (highest risk first)", "",
          "🔴 Fails · 🟡 Partial · 🟢 Meets · ⚪ undecided (pending criteria). *At stake* = overall points lost in the worst case (best case–worst case).", "",
          "| | Decision point | Level | At stake | Pending |", "|---|---|---|---|---|"]
    for r in risk:
        lvl = r["level"] or f"{r['level_min']}…{r['level_max']}"
        stake = f"{r['at_stake_max']:.1f}" if r["at_stake_min"] == r["at_stake_max"] else f"{r['at_stake_min']:.1f}–{r['at_stake_max']:.1f}"
        L.append(f"| {r['light']} | {r['name']} | {lvl} | {stake} | {', '.join(r['pending']) or '—'} |")
    L += ["", "| Decision point | Level | Severity | Confidence | Pending | Finding |", "|---|---|---|---|---|---|"]
    for p in points:
        n = p["level"] or f"{p['level_min']}…{p['level_max']}"
        L.append(f"| {p['name']} | {'▨ not evaluable' if not p['evaluable'] else n} | {p['severity'] or '—'} | {p['confidence']} | {', '.join(p['pending_criteria']) or '—'} | {p['finding']} |")
    if comp:
        L += ["", "## Supplementary indicators (informational; not scored)", "", "| Group | Indicator | Value | Reference | Status |", "|---|---|---|---|---|"]
        L += [f"| {c['group']} | {c['name']} | {c['value']} | {c['reference']} | {c['status']} |" for c in comp]
    gaps = [p for p in points if p["declarative_gap"]]
    if gaps:
        L += ["", "## Declarative gaps (README vs. structure)"] + [f"- {p['name']}: {p['declarative_gap']}" for p in gaps]
    (out / "profile.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    tpl = {"_instructions": "Fill in ok=true/false (and note) on the pending criteria and run 'run' again with --manual manual.json. DV8 values go in 'dv8'.",
           "dv8": {"DL": None, "PC": None, "unhealthy_inheritance": None}}
    for p in points:
        pend = {k: {"ok": None, "suggested": v["suggested"], "note": ""} for k, v in p["criteria"].items() if v["ok"] is None}
        if pend:
            tpl[p["id"]] = pend
    (out / "manual.template.json").write_text(json.dumps(tpl, indent=1, ensure_ascii=False), encoding="utf-8")


TOKEN_COLUMNS = ("tokens_initial_input", "tokens_initial_output", "tokens_initial_total",
                 "tokens_r2_input", "tokens_r2_output", "tokens_r2_total", "tokens_r2_vs_initial")


def token_columns(run_dir):
    """Token columns of the comparison from results/<run>/token_usage.json (None when a phase was not recorded)."""
    sm = tu.summary(tu.load(run_dir / tu.RESULT_FILE)) or {"phases": {}}
    row = {}
    for ph in ("initial", "r2"):
        t = sm["phases"].get(ph) or {}
        for k in ("input", "output", "total"):
            row[f"tokens_{ph}_{k}"] = t.get(f"{k}_tokens")
    row["tokens_r2_vs_initial"] = (sm.get("r2_vs_initial") or {}).get("total_tokens")
    return row
