#!/usr/bin/env node
// dv8_metrics.mjs — DL (Decoupling Level), PC (Propagation Cost) and IL with DV8 from the module graph of metrics.json, since DV8's
// parser does not support JS/TS. Port of dv8_metrics.py (see it for the flow).
//   node js/dv8_metrics.mjs results/<run> [--dv8 "C:/Program Files/DV8/bin/dv8-console.exe"]
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { F, dumps, dumpsAscii, fixed, get, loadJson, pyRound, sorted, str } from "./lib/py.mjs";
import { HERE } from "./evaluator/common.mjs";

export const DV8_DEFAULT = String.raw`C:\Program Files\DV8\bin\dv8-console.exe`;
const DSM = "matrix.dv8-dsm";

function which(name) {
  const exts = process.platform === "win32" ? (process.env.PATHEXT || ".EXE").split(";") : [""];
  for (const d of (process.env.PATH || "").split(path.delimiter)) for (const e of exts) { const p = path.join(d, name + e); if (fs.existsSync(p)) return p; }
  return null;
}

/** The DV8 console: --dv8, else DV8_CONSOLE, else dv8-console on the PATH, else the default install folder. */
export const findDv8 = (explicit) => explicit || process.env.DV8_CONSOLE || which("dv8-console") || DV8_DEFAULT;

function run(cmd, cwd) {
  const p = spawnSync(cmd[0], cmd.slice(1), { cwd, encoding: "utf8", timeout: 300000, windowsHide: true });
  const noise = "Picked up JAVA_TOOL_OPTIONS";
  const err = ((p.stdout || "") + (p.stderr || "")).split(/\r?\n/).filter((l) => l.trim() && !l.includes(noise)).join("\n");
  if (p.status !== 0 || err.startsWith("ERROR")) throw new Error(`DV8 failed (${cmd.slice(1, 3).join(" ")}): ${err || "rc=" + p.status}`);
}

/** The template filled in: variables = local modules; cells = local imports (count per pair). */
export function buildMatrix(graph, template, name) {
  const depType = Object.keys(template.cells[0].values)[0];
  const variables = sorted([...new Set([...graph.modules.map((m) => m.source), ...graph.modules.flatMap((m) => m.deps.filter((d) => get(d, "local")).map((d) => d.to))])]);
  const idx = new Map(variables.map((v, i) => [v, i]));
  const pairs = new Map();
  for (const m of graph.modules)
    for (const d of m.deps)
      if (get(d, "local") && idx.has(d.to) && d.to !== m.source) {
        const k = JSON.stringify([idx.get(m.source), idx.get(d.to)]);
        pairs.set(k, (pairs.get(k) ?? 0) + 1);
      }
  const matrix = structuredClone(template);
  matrix.name = name;
  matrix.variables = variables;
  matrix.cells = sorted([...pairs].map(([k, n]) => [JSON.parse(k), n])).map(([[s, t], n]) => ({ src: s, dest: t, values: { [depType]: F(n) } }));
  return [matrix, depType];
}

/** 0 when no class extends another class of the project (no own hierarchy); null otherwise (reviewed by hand). */
function unhealthyInheritance(res) {
  const classes = get(loadJson(fs.readFileSync(path.join(res, "ast.json"), "utf8")), "classes", []);
  const own = new Set(classes.map((c) => c.name));
  return classes.some((c) => own.has(get(c, "extends"))) ? null : 0;
}

const pct = (txt) => F(pyRound(Number.parseFloat(str(txt).replace(/%+$/, "")) / 100.0, 4));

export function dv8Metrics(res, dv8 = null, templatePath = path.join(HERE, "dv8", "matrix-template.json")) {
  res = path.resolve(res);
  dv8 = findDv8(dv8);
  if (!fs.existsSync(dv8)) throw new Error(`dv8-console not found at ${dv8} (use --dv8 or the DV8_CONSOLE variable)`);
  const graph = loadJson(fs.readFileSync(path.join(res, "metrics.json"), "utf8")).graph;
  const template = loadJson(fs.readFileSync(templatePath, "utf8"));
  const out = path.join(res, "dv8");
  fs.mkdirSync(out, { recursive: true });
  const [matrix, depType] = buildMatrix(graph, template, path.basename(res));
  fs.writeFileSync(path.join(out, "matrix.json"), dumpsAscii(matrix, 1), "utf8");
  run([dv8, "core:convert-matrix", "-outputFile", DSM, "matrix.json"], out);
  run([dv8, "metrics:decoupling-level", "-outputFile", "dl.json", DSM], out);
  run([dv8, "metrics:propagation-cost", "-outputFile", "pc.json", DSM], out);
  run([dv8, "metrics:independence-level", "-outputFile", "il.json", DSM], out);
  const rd = (f) => loadJson(fs.readFileSync(path.join(out, f), "utf8"));
  const dl = rd("dl.json"), pc = rd("pc.json"), il = rd("il.json");
  // the "exclude isolated" variants: a file without dependencies (vite.config.js) inflates DL to 100% in DV8
  const result = { DL: pct(dl.decouplingLevelExcludeIsolatedItems), PC: pct(pc.propagationCostExcludeIsolatedItems), IL: pct(il.independenceLevel),
    unhealthy_inheritance: unhealthyInheritance(res),
    _origin: { files: matrix.variables.length, dependencies: matrix.cells.length, dependency_type: depType, isolated: Math.trunc(Number(dl.numberOfIsolatedItems)),
      DL_with_isolated: pct(dl.decouplingLevel), PC_with_isolated: pct(pc.propagationCost),
      note: "matrix derived from dependency-cruiser, not from DV8's native parser; values exclude isolated files" } };
  fs.writeFileSync(path.join(out, "dv8_metrics.json"), dumps(result, 1), "utf8");
  const p100 = (x) => fixed(Number(x) * 100, 2) + "%";
  return `DV8 ${path.basename(res)}: DL=${p100(result.DL)}  PC=${p100(result.PC)}  (${matrix.variables.length} files, ${matrix.cells.length} dependencies, ${result._origin.isolated} isolated)`;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const res = args.find((a) => !a.startsWith("--"));
  const i = args.indexOf("--dv8"), t = args.indexOf("--template");
  if (!res) { console.error("usage: node js/dv8_metrics.mjs results/<run> [--dv8 path] [--template path]"); process.exit(2); }
  try { console.log(dv8Metrics(res, i >= 0 ? args[i + 1] : null, t >= 0 ? args[t + 1] : undefined)); }
  catch (e) { console.error(e.message); process.exit(1); }
}
