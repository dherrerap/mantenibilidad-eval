#!/usr/bin/env node
// manual_template.mjs — For an already evaluated run, the manual review templates: <res>/manual_review.md (each criterion with its
// evidence and a suggestion) and <res>/manual_review.draft.json (manual.json format, ok=null). Port of manual_template.py; see its
// docstring for the flow.
//   node js/manual_template.mjs results/<run>
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dumps, get, loadJson, readText, sorted, splitlines, str } from "./lib/py.mjs";
import { RUBRIC } from "./evaluator/common.mjs";

const MODEL_LINES = 70;  // lines of each model file copied into the guide

export function load(res) {
  return [loadJson(fs.readFileSync(path.join(res, "metrics.json"), "utf8")), RUBRIC];
}

function fanIn(m) {
  const fi = {};
  for (const x of m.graph.modules) for (const d of x.deps) if (get(d, "local")) fi[d.to] = (fi[d.to] ?? 0) + 1;
  return fi;
}

export function cohesionEvidence(m, T) {
  const fns = m.ast.functions.filter((f) => !f.test);
  const high = sorted(fns.filter((f) => f.fanout > T.fanout_max), (f) => -f.fanout);
  const prod = m.ast.files.filter((f) => !f.test);
  const fi = fanIn(m);
  const largest = sorted(prod, (f) => -f.loc).slice(0, 5);
  const small = prod.filter((f) => f.loc < 10).map((f) => f.path);
  const gods = prod.filter((f) => f.loc >= T.god_loc_min && (fi[f.path] ?? 0) >= T.god_fanin_min).map((f) => `${f.path} (LOC ${f.loc}, fan-in ${fi[f.path] ?? 0})`);
  const suggested = !gods.length && (prod.length ? small.length / prod.length <= 0.3 : true);
  const md = [`- Functions with fan-out > ${Math.trunc(T.fanout_max)}: ${high.length} of ${fns.length}`,
    ...high.slice(0, 10).map((f) => `  - \`${f.file}:${f.line}\` ${f.name} (fan-out ${f.fanout}, ${f.loc} LOC)`),
    `- 'God' modules (LOC ≥ ${str(T.god_loc_min)} and fan-in ≥ ${str(T.god_fanin_min)}): ` + (gods.join(", ") || "none"),
    "- Largest files: " + largest.map((f) => `\`${f.path}\` (${f.loc})`).join(", "),
    `- Production files with < 10 LOC (possible fragmentation): ${small.length} of ${prod.length}` + (small.length ? ": " + small.slice(0, 8).map((p) => `\`${p}\``).join(", ") : "")];
  return [md, suggested];
}

/** Table of the extracted relational schema and the code of the files that decided it. */
export function modelEvidence(m, app) {
  const T = m.schema.tables;
  const table = ["| Table | Source | Columns | Primary key | Foreign keys | Unique | Checks | Indexes |", "|---|---|---|---|---|---|---|---|"];
  for (const [name, t] of Object.entries(T)) {
    const fks = t.foreign_keys.map((f) => `${f.columns.join("+")}→${f.ref_table}`).join(", ") || "—";
    table.push(`| ${name} | ${t.source} | ${Object.keys(t.columns).length} | ${t.primary_key.join(", ") || "**none**"} | ${fks} | ${t.unique.length} | ${t.checks.length} | ${t.indexes.length} |`);
  }
  const sources = [];
  for (const f of sorted([...new Set(Object.values(T).filter((t) => get(t, "file")).map((t) => t.file.split(":")[0]))])) {
    const p = path.join(app, f);
    if (!fs.existsSync(p)) continue;
    const lines = splitlines(readText(p));
    const lang = f.toLowerCase().endsWith(".sql") ? "sql" : "js";
    sources.push(`<details><summary><code>${f}</code> (${lines.length} lines)</summary>\n\n\`\`\`${lang}\n` + lines.slice(0, MODEL_LINES).join("\n") + "\n```\n</details>");
  }
  return [table, sources, { C1: null, C3: null, C4: null }];
}

function contractsEvidence(m, rub) {
  const deps = new Set(m.packages.packages.flatMap((p) => [...Object.keys(p.dependencies), ...Object.keys(p.devDependencies)]));
  return [sorted(rub.libs_validation.filter((x, i, a) => deps.has(x) && a.indexOf(x) === i)), m.contract.files.length > 0, m.ast.routes.length];
}

const scorecardPoints = (res) => {
  const f = path.join(res, "scorecard.json");
  return fs.existsSync(f) ? loadJson(fs.readFileSync(f, "utf8")).points : null;
};

const DESIGN = { layers: ["C2"], cohesion: ["C3"], data_model: ["C1", "C2", "C3", "C4", "C5", "C6"], contracts: ["C4"] };

/** Pending criteria outside the design-judgment ones: those left pending because a measurement did not run. */
export function otherPending(res) {
  const pts = scorecardPoints(res);
  if (!pts) return [];
  return pts.flatMap((p) => get(p, "pending_criteria", []).filter((cid) => !(DESIGN[p.id] || []).includes(cid)).map((cid) => [p, cid, p.criteria[cid]]));
}

function otherPendingMd(rows) {
  if (!rows.length) return [];
  return ["## Other pending criteria (a measurement did not run)", "",
    "These are not design judgments: the evaluator could not measure them. The best fix is to provide what is missing and evaluate again " +
    "(install the tool, run with a network, run the tests, run DV8, correct --as-of…); the reason is in each row. If you measure it yourself, " +
    "you can also decide it here.", "", "| Point | Criterion | Statement | Why it is pending |", "|---|---|---|---|",
    ...rows.map(([p, cid, c]) => `| ${p.name} | ${cid} | ${c.desc} | ${c.source} |`), ""];
}

export function writeTemplates(res) {
  res = path.resolve(res);
  const [m, rub] = load(res);
  const app = m.app, T = rub.thresholds.cohesion;
  const [cohMd, cohSug] = cohesionEvidence(m, T);
  const [table, sources] = modelEvidence(m, app);
  const pts = scorecardPoints(res);
  const dm = pts ? pts.find((x) => x.id === "data_model") ?? null : null;
  const dmRows = [], dmItems = {};
  for (const cid of ["C1", "C2", "C3", "C4", "C5", "C6"]) {
    const c = get(get(dm || {}, "criteria") || {}, cid);
    if (!c) { dmRows.push(`| ${cid} | — | run the evaluation first |`); dmItems[cid] = null; continue; }
    let resTxt;
    if (c.ok === null) { resTxt = `suggestion: ${c.suggested ? "true" : "false"} (heuristic; decide it)`; dmItems[cid] = c.suggested; }
    else { resTxt = `${c.ok ? "met" : "NOT met"} (${c.source})`; dmItems[cid] = c.ok; }
    dmRows.push(`| ${cid} | ${c.desc} | ${resTxt} |`);
  }
  const [libs, hasContract, nRoutes] = contractsEvidence(m, rub);
  const contractSug = libs.length > 0 && hasContract;
  const lp = pts ? pts.find((x) => x.id === "layers") ?? null : null;
  const layers = lp && get(lp, "pending_criteria", []).includes("C2") ? lp : null;
  const layersMd = layers ? ["## Layers · C2 — violations ≤ 5% of inter-layer dependencies", "", layers.finding, "", "Evidence (detected violations):", "",
    ...layers.evidence.map((e) => `- ${e}`), "", "Review `detected_layers.json` (each file carries its layer and the directory that decided it) and decide:",
    "- **true** if the separation is real (e.g. the doubtful dependencies are legitimate in this architecture, or the layers are connected through dependency injection).",
    "- **false** if there is improper coupling between layers.", "Alternative: define the classification in a `.layers.json` inside the app and evaluate again.", ""] : [];
  const L = [`# Manual review — ${path.basename(res)}`, "",
    "Fill in `ok: true/false` in `manual_review.draft.json` (save it as `manual_review.json`). The suggestions are indicative.", "", ...layersMd,
    "## Cohesion · C3 — checklist with no findings", "", "Criterion: there is no 'god' module, no mixing of unrelated responsibilities in one module, and no excessive fragmentation.", "",
    ...cohMd, "", `**Suggestion:** ${cohSug ? "true" : "false"} (no 'god' module and no high fragmentation). Mixed responsibilities must be judged by reading the modules with the highest fan-out.`, "",
    "## Data model", "", `${Object.keys(m.schema.tables).length} table(s) detected.`, "", ...table, "", "| Criterion | Statement | Result |", "|---|---|---|", ...dmRows, "",
    "C2 (normalization consistent with access, up to 3NF) and C5 (no unjustified redundancy) are suggestions: read the schema, the queries and " +
    "`docs/entity-relationship-model.md` before deciding. The measured criteria can also be overridden if the evidence misled the program " +
    "(for example, a relation that the static analysis could not see).", "", "Schema code:", "", ...sources, "",
    "## Contracts · C4 — input validation consistent with the contract", "", `- Machine-readable contract: ${hasContract ? "yes" : "no"}; implemented routes: ${nRoutes}.`,
    `- Declared validation libraries: ${libs.join(", ") || "none"}.`,
    `**Suggestion:** ${contractSug ? "true" : "false"}` + (hasContract ? "" : " (without a contract there is nothing to compare the validation against)."), ""];
  const others = otherPending(res);
  L.push(...otherPendingMd(others));
  fs.writeFileSync(path.join(res, "manual_review.md"), L.join("\n"), "utf8");
  const item = (sug, note) => ({ ok: null, suggested: sug, note });
  const draft = { _instructions: "Change ok to true/false, save as manual_review.json and run the evaluation again.",
    ...(layers ? { layers: { C2: item(null, "") } } : {}), cohesion: { C3: item(cohSug, "") },
    data_model: Object.fromEntries(["C1", "C2", "C3", "C4", "C5", "C6"].map((cid) => [cid, item(dmItems[cid], "")])), contracts: { C4: item(contractSug, "") } };
  for (const [p, cid] of others) (draft[p.id] ??= {})[cid] = item(null, "");  // measurement-pending: no suggestion
  fs.writeFileSync(path.join(res, "manual_review.draft.json"), dumps(draft, 1), "utf8");
  return `${path.basename(res)}: manual_review.md and manual_review.draft.json`;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (!process.argv[2]) { console.error("usage: node js/manual_template.mjs results/<run>"); process.exit(2); }
  console.log(writeTemplates(process.argv[2]));
}
