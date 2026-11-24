#!/usr/bin/env node
// evaluate.mjs — Command line of the evaluation (port of evaluate.py; see it for the protocol and the security note on --run-tests).
//   node js/evaluate.mjs run <app_dir> --out results/<run> --agent claude --model "claude-sonnet-5-5" --level N2 --domain ecommerce
//        [--run-tests [--mutation]] [--test-cmd "…"] [--offline] [--as-of YYYY-MM-DD] [--accept-heuristics] [--manual manual.json]
//        [--layers layers.json] [--allow-missing-model] [--run-id ID]
//   node js/evaluate.mjs rescore results/<run> [results/<run2> …]
//   node js/evaluate.mjs aggregate results/ [--out results/_comparison]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { csvRow, dumps, dumpsAscii, fixed, get, loadJson, str } from "./lib/py.mjs";
import { ascmmColumns, ascmmComparisonMd, COLUMNS as ASCMM_COLUMNS } from "./evaluator/ascmm.mjs";
import { collect } from "./evaluator/collectors/index.mjs";
import { MODEL_WARNING, RUBRIC, modelMissing } from "./evaluator/common.mjs";
import { TOKEN_COLUMNS, fmtRng, tokenColumns } from "./evaluator/outputs.mjs";
import { score, rescore } from "./evaluator/pipeline.mjs";
import { sensitivity, sensitivityMd } from "./evaluator/sensitivity.mjs";
import * as tu from "./evaluator/tokens.mjs";

export const MODEL_ERROR = "The generator model is missing. Pass the model that generated the application with --model \"<model>\" " +
  "(for example --model \"claude-sonnet-5-5\"); it is a variable of the experiment and the results cannot be interpreted without it. " +
  "To evaluate anyway, add --allow-missing-model: profile.md and report.md will then carry a warning.";

const readJson = (p) => loadJson(fs.readFileSync(p, "utf8"));
const write = (p, t) => fs.writeFileSync(p, t, "utf8");

export async function cmdRun(a) {
  if (modelMissing(a.model) && !a.allow_missing_model) throw new Error("ERROR: " + MODEL_ERROR);
  const out = path.resolve(a.out);
  fs.mkdirSync(out, { recursive: true });
  const app = path.resolve(a.app);
  console.log(`[1/4] Collecting evidence from ${app} …`);
  const m = await collect(app, out, a);
  const meta = { run_id: a.run_id || path.basename(out), agent: a.agent ?? null, model: a.model ?? null, model_missing: modelMissing(a.model), level: a.level ?? null,
    domain: a.domain ?? null, accept_heuristics: Boolean(a.accept_heuristics), run_tests: Boolean(a.run_tests), offline: Boolean(a.offline), date: m.date, as_of: m.as_of,
    mutation: Boolean(a.mutation), manual_file: a.manual ? path.resolve(a.manual) : null };  // so that `rescore` reads the same review
  write(path.join(out, "meta.json"), dumpsAscii(meta, 1));
  write(path.join(out, "metrics.json"), dumps(m, 1));
  write(path.join(out, "detected_layers.json"), dumpsAscii(Object.fromEntries(Object.entries(m.layers).map(([p, c]) => [p, { layer: c, origin: get(m.layers_origin, p) }])), 1));
  console.log("[2/4] Evaluating the 11 points …");
  // the same scoring as `rescore`, on the evidence just collected (re-read, as Python does, so that it is the saved one)
  const [, prof] = score(out, readJson(path.join(out, "metrics.json")), meta, meta.manual_file);
  console.log("[3/4] Scorecard, traceability and profile written");
  console.log(`[4/4] Maintainability: ${fmtRng(prof.maintainability_min, prof.maintainability_max)}/100 · complete=${prof.complete ? "True" : "False"} → ${out}`);
}

export function cmdRescore(a) {
  for (const r of a.res) {
    const [meta, , prof] = rescore(path.resolve(r));
    console.log(`Re-scored ${str(get(meta, "run_id", path.basename(r)))}: Maintainability: ${fmtRng(prof.maintainability_min, prof.maintainability_max)}/100` +
      ` · complete=${prof.complete ? "True" : "False"}`);
  }
}

export function cmdAggregate(a) {
  const root = path.resolve(a.dir);
  const runs = fs.readdirSync(root).sort().map((d) => path.join(root, d)).filter((d) => fs.existsSync(path.join(d, "metrics.json")));
  if (!runs.length) throw new Error("No runs with metrics.json in " + root);
  const ms = Object.fromEntries(runs.map((d) => [path.basename(d), readJson(path.join(d, "metrics.json"))]));
  const old = Object.entries(ms).filter(([, x]) => !("schema" in x)).map(([n]) => n);
  if (old.length) throw new Error("These runs were produced by the MERN evaluator (no relational schema in metrics.json): " + old.join(", ") +
    ". Re-run 'evaluate' on them, or check out the tag v0.1.0-mern to aggregate them as they were.");
  const rows = [];
  for (const d of runs) {  // each run re-scored with its current inputs (manual review, DV8, live database, judge)
    const meta = readJson(path.join(d, "meta.json"));
    const [pts, prof] = score(d, ms[path.basename(d)], meta, get(meta, "manual_file"));
    const accF = path.join(d, "acceptance.json");
    const acc = fs.existsSync(accF) ? get(readJson(accF), "acceptance_pct") : null;
    rows.push([meta, pts, prof, [acc, tokenColumns(d)]]);
  }
  const out = a.out ? path.resolve(a.out) : path.join(root, "_comparison");
  fs.mkdirSync(out, { recursive: true });
  const ids = Object.keys(RUBRIC.points);
  let csv = csvRow(["run_id", "agent", "level", "domain", ...ids, ...Object.keys(RUBRIC.subcharacteristic_weights), "maintainability_min", "maintainability_max", "complete",
    "acceptance_pct", ...TOKEN_COLUMNS, ...ASCMM_COLUMNS]);
  for (const [meta, pts, prof, [acc, tok]] of rows) {
    const lv = Object.fromEntries(pts.map((p) => [p.id, p.level || (p.applicable === false ? "not applicable" : `${str(p.level_min)}…${str(p.level_max)}`)]));
    csv += csvRow([meta.run_id, meta.agent, meta.level, meta.domain, ...ids.map((i) => lv[i]), ...Object.values(prof.subcharacteristics).map((v) => fmtRng(v.min, v.max)),
      prof.maintainability_min, prof.maintainability_max, prof.complete, acc, ...TOKEN_COLUMNS.map((k) => tok[k]), ...ascmmColumns(prof)]);
  }
  write(path.join(out, "comparison.csv"), csv);
  const L = [`# Comparison (${rows.length} runs)`, "", "| Run | Agent | Level | " + ids.join(" | ") + " | Overall | Acceptance % | Tokens initial | Tokens R2 | R2 / initial |",
    "|" + "---|".repeat(ids.length + 8)];
  const noModel = rows.filter(([meta]) => modelMissing(get(meta, "model"))).map(([meta]) => meta.run_id);
  if (noModel.length) L.splice(2, 0, `> ⚠ **Generator model not recorded** for ${noModel.join(", ")}. ${MODEL_WARNING}`, "");
  const ab = { Meets: "✔", Partial: "◐", Fails: "✘" };
  for (const [meta, pts, prof, [acc, tok]] of rows) {
    const ratio = tok.tokens_r2_vs_initial;
    L.push(`| ${meta.run_id} | ${str(meta.agent)} | ${str(meta.level)} | ` + pts.map((p) => (p.applicable === false ? "⊘" : get(ab, p.level, "?"))).join(" | ") +
      ` | ${fmtRng(prof.maintainability_min, prof.maintainability_max)} | ${acc === null ? "n/a" : str(acc)} | ` +
      `${tu.fmt(tok.tokens_initial_total)} | ${tu.fmt(tok.tokens_r2_total)} | ${ratio === null ? "n/a" : "×" + fixed(ratio, 2)} |`);
  }
  L.push("", ...ascmmComparisonMd(rows.map(([meta, , prof]) => [meta.run_id, prof])));
  const sens = sensitivity(rows.map(([meta, pts]) => [meta, pts]));
  write(path.join(out, "sensitivity.json"), dumps(sens, 1));
  L.push("", ...sensitivityMd(sens));
  write(path.join(out, "comparison.md"), L.join("\n") + "\n");
  console.log(`Comparison written to ${out} (${rows.length} runs)`);
}

/** argparse-like parsing of the three subcommands. */
export function parseArgs(argv) {
  const [cmd, ...rest] = argv;
  const a = { cmd };
  const flags = { run: ["run-tests", "offline", "accept-heuristics", "mutation", "allow-missing-model"], rescore: [], aggregate: [] }[cmd];
  if (!flags) throw new Error("usage: evaluate.mjs {run,rescore,aggregate} …");
  const pos = [];
  for (let i = 0; i < rest.length; i++) {
    const x = rest[i];
    if (!x.startsWith("--")) { pos.push(x); continue; }
    const k = x.slice(2).replaceAll("-", "_");
    if (flags.includes(x.slice(2))) a[k] = true;
    else a[k] = rest[++i];
  }
  if (cmd === "run") { [a.app] = pos; if (!a.app || !a.out) throw new Error("usage: evaluate.mjs run <app> --out <dir> …"); }
  if (cmd === "rescore") a.res = pos;
  if (cmd === "aggregate") [a.dir] = pos;
  if (a.as_of && !/^\d{4}-\d{2}-\d{2}$/.test(a.as_of)) throw new Error(`Invalid isoformat string: '${a.as_of}'`);
  return a;
}

export async function main(argv) {
  const a = parseArgs(argv);
  if (a.cmd === "run") await cmdRun(a);
  else if (a.cmd === "rescore") cmdRescore(a);
  else cmdAggregate(a);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch((e) => { console.error(e.message); process.exit(1); });
}
