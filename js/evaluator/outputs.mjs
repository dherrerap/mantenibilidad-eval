// outputs.mjs — Files written for each run (scorecard, profile, traceability, dashboard, manual template) and the token columns of
// the comparison. Port of evaluator/outputs.py: every file must be byte-identical to the Python one.
import fs from "node:fs";
import path from "node:path";
import { csvRow, dumps, fixed, get, num, str, truthy } from "../lib/py.mjs";
import { ascmmMarkdown } from "./ascmm.mjs";
import { MODEL_WARNING, modelMissing } from "./common.mjs";
import { dashboardHtml, dashboardMarkdown, riskDashboard } from "./dashboard.mjs";
import { riskSummary } from "./scoring.mjs";
import { supplementaryIndicators } from "./supplementary.mjs";
import * as tu from "./tokens.mjs";

export const fmtRng = (a, b) => (a === null || a === undefined ? "n/a" : num(a) === num(b) ? fixed(a, 1) : `${fixed(a, 1)}–${fixed(b, 1)}`);

export function artifactsMarkdown(m) {
  const arts = get(m, "artifacts") || [];
  if (!arts.length) return [];
  return ["## Input artifacts (Table 27)", "", "| Artifact | Level | Present | Detail | Feeds |", "|---|---|---|---|---|",
    ...arts.map((a) => `| ${a.name} | ${a.level} | ${a.present ? "yes" : "no"} | ${str(a.detail)} | ${a.feeds.join(", ") || "—"} |`), ""];
}

/** Section of profile.md: the tokens the generator agent used per phase. */
export function tokenMarkdown(runDir) {
  const sm = tu.summary(tu.load(path.join(runDir, tu.RESULT_FILE)));
  const L = ["## AI token consumption", ""];
  if (!sm || !Object.keys(sm.phases).length) return [...L, "No token record for this run (see `token_usage.py` and docs/generating-apps.md).", ""];
  L.push("Tokens the generator agent used to create the application (**initial**) and to implement the additional requirements (**R2**). " +
    "Input includes the prompt-cache reads and writes; output includes reasoning. Not part of the maintainability score.", "",
    "| Phase | Input | Output | **Total** | Requests |", "|---|---|---|---|---|");
  for (const [ph, label] of [["initial", "Initial"], ["r2", "R2"]]) {
    const t = get(sm.phases, ph);
    L.push(truthy(t) ? `| ${label} | ${tu.fmt(t.input_tokens)} | ${tu.fmt(t.output_tokens)} | **${tu.fmt(t.total_tokens)}** | ${str(get(t, "requests", "n/a"))} |`
      : `| ${label} | — | — | **missing** | — |`);
  }
  const ratio = get(get(sm, "r2_vs_initial") || {}, "total_tokens");
  if (ratio !== null) L.push(`| R2 / initial | | | **×${fixed(ratio, 2)}** | |`);
  return [...L, ""];
}

const write = (out, name, text) => fs.writeFileSync(path.join(out, name), text, "utf8");

export function writeOutputs(out, meta, points, prof, m) {
  fs.mkdirSync(out, { recursive: true });
  write(out, "scorecard.json", dumps({ meta, points }, 1));
  const risk = riskSummary(points);
  const dash = riskDashboard(points, prof, m);
  write(out, "profile.json", dumps({ meta, ...prof, risk, dashboard: dash }, 1));
  write(out, "artifacts.json", dumps(get(m, "artifacts") || [], 1));
  write(out, "risk_dashboard.json", dumps(dash, 1));
  write(out, "risk_dashboard.md", dashboardMarkdown(dash, points).join("\n"));
  write(out, "risk_dashboard.html", dashboardHtml(dash, points, `Risk dashboard — ${str(get(meta, "run_id"))}`));
  let csv = csvRow(["point", "category", "level", "level_min", "level_max", "severity", "confidence", "missing_artifacts", "pending_criteria", "finding", "evidence"]);
  for (const p of points)
    csv += csvRow([p.name, p.category, p.level || (!p.evaluable ? "not evaluable" : "pending"), p.level_min, p.level_max, p.severity, p.confidence,
      p.missing_artifacts.join(" "), p.pending_criteria.join(" "), p.finding, p.evidence.slice(0, 5).join(" | ")]);
  write(out, "scorecard.csv", csv);
  let tr = csvRow(["design_decision", "detected_weakness", "affected_subcharacteristics", "level", "evidence", "declarative_gap"]);
  for (const p of points)
    tr += csvRow([p.finding, p.weaknesses.join("; ") || "—", p.subcharacteristics.join(", "), p.level || "pending", p.evidence.slice(0, 5).join(" | "), p.declarative_gap || ""]);
  write(out, "traceability.csv", tr);
  const comp = supplementaryIndicators(m);
  write(out, "supplementary.json", dumps(comp, 1));
  const noModel = modelMissing(get(meta, "model"));
  const L = [`# Maintainability profile — ${str(get(meta, "run_id"))}`, "",
    `Agent: ${str(get(meta, "agent"))} · Model: ${noModel ? "NOT RECORDED" : str(get(meta, "model"))} · Prompt level: ${str(get(meta, "level"))} · Domain: ${str(get(meta, "domain"))} · ${str(m.date)}`, "",
    ...(noModel ? [`> ⚠ **Generator model not recorded.** ${MODEL_WARNING}`, ""] : []),
    `**Overall maintainability: ${fmtRng(prof.maintainability_min, prof.maintainability_max)} / 100**` + (prof.complete ? "" : "  _(range: there are pending criteria; see manual.template.json)_"), "",
    "| Subcharacteristic | Weight | Score |", "|---|---|---|"];
  for (const [s, v] of Object.entries(prof.subcharacteristics)) L.push(`| ${s} | ${Math.trunc(num(v.weight) * 100)}% | ${fmtRng(v.min, v.max)} |`);
  if (truthy(get(prof, "judge_criteria")))
    L.push("", `> **Judge decisions (${str(prof.judge_model)}):** ${prof.judge_criteria.join(", ")}. ` +
      `Without them the result would be ${fmtRng(prof.without_judge.min, prof.without_judge.max)}. ` +
      `For a person to review: ${prof.judge_audit.join(", ") || "—"}.`);
  L.push("", ...tokenMarkdown(out), ...dashboardMarkdown(dash, points), ...artifactsMarkdown(m));
  L.push("## Risk map (highest risk first)", "",
    "🔴 Fails · 🟡 Partial · 🟢 Meets · ⚪ undecided (pending criteria). *At stake* = overall points lost in the worst case (best case–worst case).", "",
    "| | Decision point | Level | At stake | Pending |", "|---|---|---|---|---|");
  for (const r of risk) {
    const lvl = r.level || `${str(r.level_min)}…${str(r.level_max)}`;
    const stake = num(r.at_stake_min) === num(r.at_stake_max) ? fixed(r.at_stake_max, 1) : `${fixed(r.at_stake_min, 1)}–${fixed(r.at_stake_max, 1)}`;
    L.push(`| ${r.light} | ${r.name} | ${lvl} | ${stake} | ${r.pending.join(", ") || "—"} |`);
  }
  L.push("", "| Decision point | Level | Severity | Confidence | Pending | Finding |", "|---|---|---|---|---|---|");
  for (const p of points) {
    const n = p.level || `${str(p.level_min)}…${str(p.level_max)}`;
    L.push(`| ${p.name} | ${!p.evaluable ? "▨ not evaluable" : n} | ${p.severity || "—"} | ${p.confidence} | ${p.pending_criteria.join(", ") || "—"} | ${p.finding} |`);
  }
  if (truthy(get(prof, "ascmm"))) L.push("", ...ascmmMarkdown(prof.ascmm));
  if (comp.length) {
    L.push("", "## Supplementary indicators (informational; not scored)", "", "| Group | Indicator | Value | Reference | Status |", "|---|---|---|---|---|");
    L.push(...comp.map((c) => `| ${c.group} | ${c.name} | ${str(c.value)} | ${c.reference} | ${c.status} |`));
  }
  const gaps = points.filter((p) => p.declarative_gap);
  if (gaps.length) L.push("", "## Declarative gaps (README vs. structure)", ...gaps.map((p) => `- ${p.name}: ${p.declarative_gap}`));
  write(out, "profile.md", L.join("\n") + "\n");
  const tpl = { _instructions: "Every pending criterion of this run. Fill in ok=true/false (and note), save it as manual_review.json in this folder and " +
    "run `python cli.py evaluate --rescore` (or `python evaluate.py rescore <this folder>`). DV8 values go in 'dv8'. " +
    "manual_review.draft.json (manual_template.py) has the same criteria with evidence and suggestions.",
  dv8: { DL: null, PC: null, unhealthy_inheritance: null } };
  for (const p of points) {
    const pend = Object.fromEntries(Object.entries(p.criteria).filter(([, v]) => v.ok === null).map(([k, v]) => [k, { ok: null, suggested: v.suggested, note: "" }]));
    if (Object.keys(pend).length) tpl[p.id] = pend;
  }
  write(out, "manual.template.json", dumps(tpl, 1));
}

export const TOKEN_COLUMNS = ["tokens_initial_input", "tokens_initial_output", "tokens_initial_total", "tokens_r2_input", "tokens_r2_output", "tokens_r2_total", "tokens_r2_vs_initial"];

/** Token columns of the comparison from results/<run>/token_usage.json (null when a phase was not recorded). */
export function tokenColumns(runDir) {
  const sm = tu.summary(tu.load(path.join(runDir, tu.RESULT_FILE))) || { phases: {} };
  const row = {};
  for (const ph of ["initial", "r2"]) {
    const t = get(sm.phases, ph) || {};
    for (const k of ["input", "output", "total"]) row[`tokens_${ph}_${k}`] = get(t, `${k}_tokens`);
  }
  row.tokens_r2_vs_initial = get(get(sm, "r2_vs_initial") || {}, "total_tokens");
  return row;
}
