#!/usr/bin/env node
// cli.mjs — Single entry point of the evaluation framework. Port of cli.py (see its docstring for the conventions: app folder names,
// experiment.json, judge, manual review, collection once per app).
//   node js/cli.mjs doctor                    checks that the environment has everything it needs
//   node js/cli.mjs evaluate [apps…] [opts]   evaluates each app (tests, DV8, manual templates, database, judge) and aggregates
//   node js/cli.mjs report [--results dir]    generates results/report.md
// Each app is evaluated by its own `node js/evaluate.mjs run` process, so that one failing app does not stop the batch.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dumps, fixed, get, loadJson, num, or, sorted, splitlines, str, truthy } from "./lib/py.mjs";
import { ascmmComparisonMd } from "./evaluator/ascmm.mjs";
import { HERE, MODEL_WARNING, modelMissing, nowIso } from "./evaluator/common.mjs";
import { fmtRng } from "./evaluator/outputs.mjs";
import { sensitivity, sensitivityMd } from "./evaluator/sensitivity.mjs";
import { DV8_DEFAULT } from "./dv8_metrics.mjs";
import { MODEL_ERROR } from "./evaluate.mjs";
import * as pgTemp from "./pg_temp.mjs";
import * as tu from "./token_usage.mjs";
import { sh } from "./evaluator/sys.mjs";

const NODE = process.execPath, JS = path.join(HERE, "js");
const OK = "✔", FAIL = "✘", WARN = "!";
const SYMBOL = { Meets: "✔", Partial: "◐", Fails: "✘" };
const TIMEOUT_RC = 124;
const CHILD_ENV = { ...process.env, PYTHONIOENCODING: "utf-8" };
delete CHILD_ENV.NODE_TEST_CONTEXT;
const readJson = (p) => loadJson(fs.readFileSync(p, "utf8"));
const exists = (p) => fs.existsSync(p);

/** [returncode, stdout+stderr]; a command over `timeout` seconds gives 124 instead of aborting the batch. */
export function execute(cmd, { cwd, timeout = 1800 } = {}) {
  const p = spawnSync(cmd[0], cmd.slice(1), { cwd, encoding: "utf8", env: CHILD_ENV, timeout: timeout * 1000, maxBuffer: 256 * 1024 * 1024, windowsHide: true });
  if (p.error && p.error.code === "ETIMEDOUT") return [TIMEOUT_RC, (p.stdout || "") + `\nTIMEOUT: the command did not finish within ${timeout} s`];
  if (p.error) throw p.error;
  return [p.status ?? 1, (p.stdout || "") + (p.stderr || "")];
}

function which(name) {
  const exts = process.platform === "win32" ? ["", ...(process.env.PATHEXT || ".EXE").split(";")] : [""];
  for (const d of (process.env.PATH || "").split(path.delimiter)) for (const e of exts) {
    const p = path.join(d, name + e);
    try { if (fs.statSync(p).isFile()) return p; } catch { /* next */ }
  }
  return null;
}

function version(cmd) {
  const exe = which(cmd[0]);
  if (!exe) return null;
  try {  // npm through sys.sh (npm-cli.js with this node): a .cmd shim cannot be spawned without a shell on Windows
    const [rc, so, se] = cmd[0] === "npm" ? sh(cmd, { timeout: 30 }) : [...execute([exe, ...cmd.slice(1)], { timeout: 30 }), ""];
    const out = so + se;
    return rc === 0 && out.trim() ? splitlines(out.trim()).at(-1) : null;
  } catch { return null; }
}

export function findDv8() {
  for (const c of [process.env.DV8_CONSOLE, which("dv8-console"), DV8_DEFAULT]) if (c && exists(c)) return c;
  return null;
}

// ───────────────────────── doctor ─────────────────────────
const nodeVersion = (t) => { const m = /^v?(\d+)\.(\d+)\.(\d+)/.exec(t || ""); return m ? m.slice(1).map(Number) : [0, 0, 0]; };
const ge = (v, w) => v[0] !== w[0] ? v[0] > w[0] : v[1] !== w[1] ? v[1] > w[1] : v[2] >= w[2];
const nodeSupported = (v) => (v[0] === 20 && ge(v, [20, 19, 0])) || (v[0] === 22 && ge(v, [22, 13, 0])) || v[0] >= 24;

function dockerStatus() {
  if (!which("docker")) return [null, "Docker is not installed or not on PATH"];
  try {
    if (spawnSync("docker", ["info"], { timeout: 60000, stdio: "ignore" }).status !== 0) return [null, "the Docker daemon is not running (docker info failed)"];
    if (spawnSync("docker", ["compose", "version"], { timeout: 60000, stdio: "ignore" }).status === 0) return [["docker", "compose"], null];
  } catch (e) { return [null, `Docker did not respond (${e.message})`]; }
  if (which("docker-compose")) return [["docker-compose"], null];
  return [null, "Docker Compose is not available (neither `docker compose` nor `docker-compose`)"];
}

function canConnect(host, port, ms) {
  const p = spawnSync(NODE, ["-e", `const s=require('net').connect(${port},'${host}',()=>{s.end();process.exit(0)});s.setTimeout(${ms},()=>process.exit(1));s.on('error',()=>process.exit(1))`], { timeout: ms + 2000 });
  return p.status === 0;
}

export function cmdDoctor() {
  const rows = [];
  const add = (ok, name, detail, help = "", required = true) => rows.push([ok ? OK : required ? FAIL : WARN, name, detail, ok ? "" : help, required]);
  const nodeV = process.version, nv = nodeVersion(nodeV);
  add(nodeSupported(nv), "Node.js 20.19+, 22.13+ or 24+", nodeV,
    "Install Node.js 22 LTS (nodejs.org): ESLint 10 needs ^20.19 || ^22.13 || >=24 and Knip 6 ^20.19 || >=22.12.");
  add(ge(nv, [22, 0, 0]), "Node.js ≥ 22 for --mutation (optional)", nodeV, "StrykerJS 10 needs Node.js 22 or later; without it --mutation cannot run.", false);
  add(Boolean(which("npm")), "npm", version(["npm", "--version"]) || "not found", "npm comes with Node.js.");
  const nm = (d) => exists(path.join(HERE, "node_modules", d, "package.json"));
  const missing = ["ts-morph", "dependency-cruiser", "knip", "eslint", "eslint-plugin-sonarjs", "typescript-eslint"].filter((d) => !nm(d));
  add(!missing.length, "Evaluator dependencies", missing.length ? "missing: " + missing.join(", ") : "installed",
    `Run 'npm install' in ${HERE}. Without ESLint, Configuration C2 (S1192) stays pending and the cognitive complexity and the ASCMM indicators are not measured.`);
  const extra = [["Prism", "@stoplight/prism-cli"], ["StrykerJS", "@stryker-mutator/core"]].filter(([, p]) => !nm(p)).map(([n]) => n);
  add(!extra.length, "Prism and StrykerJS (optional)", extra.length ? "missing: " + extra.join(", ") : "installed",
    "Without Prism the runtime conformance to the OpenAPI contract is not measured during the acceptance gate; without StrykerJS " +
    `--mutation is not available. Run 'npm install' in ${HERE}.`, false);
  const pg = nm("pg"), pgBin = pgTemp.findBin();
  const serverTxt = process.env.PG_ADMIN_URL ? "; PG_ADMIN_URL set" : pgBin ? `; temporary server from ${pgBin}` : "; no PG_ADMIN_URL and no PostgreSQL binaries";
  add(pg && Boolean(process.env.PG_ADMIN_URL || pgBin), "PostgreSQL analysis and acceptance gate (optional: --postgres)", (pg ? "pg installed" : "pg missing") + serverTxt,
    "Without it the data model is evaluated from the code only and the acceptance gate does not run. Run 'npm install' and either install " +
    "PostgreSQL (a temporary server is started from its initdb/pg_ctl; PG_BIN if they are not found) or set PG_ADMIN_URL (a role with CREATEDB).", false);
  let rub = true;
  try { JSON.parse(fs.readFileSync(path.join(HERE, "rubric.json"), "utf8")); } catch { rub = false; }
  add(rub, "rubric.json", rub ? "valid" : "missing or invalid", "Restore rubric.json from the repository.");
  const dv8 = findDv8();
  let status = "not found";
  if (dv8) {
    try { const [, out] = execute([dv8, "license:status"], { timeout: 90 }); status = out.includes('"valid"') ? "valid license" : "invalid license"; }
    catch { status = "did not respond"; }
  }
  add(status === "valid license", "DV8 (optional: DL and PC)", `${dv8 || "—"} · ${status}`,
    "Without DV8, DL and PC stay pending; use --skip-dv8 or install DV8 and set DV8_CONSOLE.", false);
  const [compose, why] = dockerStatus();
  add(compose !== null, "Docker + Compose (optional: acceptance gate)", compose ? compose.join(" ") : why,
    "Without Docker, run_experiment.py skips the acceptance gate (the apps are not checked against PostgreSQL).", false);
  const online = canConnect("registry.npmjs.org", 443, 5000);
  add(online, "Network access to the npm registry (optional)", online ? "reachable" : "no access", "Without a network, use --offline: versions and vulnerabilities stay pending.", false);
  const apps = path.join(HERE, "apps");
  const n = exists(apps) ? fs.readdirSync(apps, { withFileTypes: true }).filter((d) => d.isDirectory()).length : 0;
  add(n > 0, "apps/ folder", `${n} application(s)`, "Create apps/<agent>-<level>/ with each generated application.", false);
  for (const [st, name, detail, help] of rows) {
    console.log(` ${st}  ${name.padEnd(44)} ${detail}`);
    if (help) console.log(`      → ${help}`);
  }
  const blocking = rows.filter((r) => r[0] === FAIL);
  console.log("\n" + (blocking.length ? `${blocking.length} required item(s) missing.` : "Environment ready."));
  return blocking.length ? 1 : 0;
}

// ───────────────────────── evaluate ─────────────────────────
const loadConfig = (p) => (exists(p) ? readJson(p) : {});

export function options(a) {
  const cfg = loadConfig(a.config || "experiment.json");
  const pick = (name, dflt) => { const v = a[name]; return v !== undefined && v !== null && v !== false ? v : get(cfg, name, dflt); };
  return { apps: (a.apps && a.apps.length ? a.apps : null) || get(cfg, "apps") || null, apps_dir: pick("apps_dir", "apps"), results: pick("results", "results"),
    domain: pick("domain", "ecommerce"), model: pick("model", null), allow_missing_model: pick("allow_missing_model", false), rep: pick("rep", 1),
    skip_tests: pick("skip_tests", false), skip_dv8: pick("skip_dv8", false), offline: pick("offline", false), as_of: pick("as_of", null),
    accept_heuristics: pick("accept_heuristics", false), mutation: pick("mutation", false), judge: pick("judge", null), judge_votes: pick("judge_votes", 3),
    judge_cmd: pick("judge_cmd", null), allow_same_model: pick("allow_same_model", false), postgres: pick("postgres", false), usage_dir: pick("usage_dir", tu.DEFAULT_DIR),
    rescore_only: Boolean(a.rescore) };
}

const knownDomains = () => sorted(fs.readdirSync(path.join(HERE, "specs")).filter((f) => /^requirements-.*\.md$/.test(f)).map((f) => f.slice("requirements-".length, -3)));

/** [agent, level, domain] from an app folder named <agent>-<level> or <agent>-<domain>-<level>. */
export function identity(name, domains = null) {
  domains = domains ?? knownDomains();
  const m = /^(?<ag>[A-Za-z0-9]+)(?:-(?<dom>[A-Za-z0-9]+))?-(?<lv>[Nn]\d+)$/.exec(name);
  if (!m || (m.groups.dom && !domains.includes(m.groups.dom.toLowerCase()))) return [name, "n/a", null];
  return [m.groups.ag.toLowerCase(), m.groups.lv.toUpperCase(), (m.groups.dom || "").toLowerCase() || null];
}

const lastLine = (out, re) => splitlines(out).reverse().find((l) => re.test(l))?.trim() ?? null;
const rescoreCmd = (out) => [NODE, path.join(JS, "evaluate.mjs"), "rescore", out];

function finalSummary(out) {
  const f = path.join(out, "profile.json");
  if (!exists(f)) return "";
  const p = readJson(f);
  return `Maintainability: ${fmtRng(p.maintainability_min, p.maintainability_max)}/100 · complete=${p.complete ? "True" : "False"}`;
}

function copyTokenUsage(app, out, usageDir) {
  const src = tu.usagePath(app, usageDir), dst = path.join(out, tu.RESULT_FILE);
  fs.mkdirSync(out, { recursive: true });
  if (!exists(src)) { fs.rmSync(dst, { force: true }); return "tokens not recorded (see token_usage.py)"; }
  fs.copyFileSync(src, dst);
  const ph = get(tu.load(src) || {}, "phases", {});
  const missing = ["initial", "r2"].filter((p) => !(p in ph));
  return missing.length ? `tokens of phase ${missing.join(", ")} not recorded` : null;
}

function postCollectionSteps(out, o, dv8) {
  const warnings = [];
  const rescore = (after) => {
    const [rc, s] = execute(rescoreCmd(out));
    if (rc !== 0) warnings.push(`re-scoring after ${after} failed: ` + (lastLine(s, /\S/) || ""));
  };
  if (dv8) {
    const [rc2, s2] = execute([NODE, path.join(JS, "dv8_metrics.mjs"), out, ...(dv8 === DV8_DEFAULT ? [] : ["--dv8", dv8])]);
    if (rc2 === 0) rescore("DV8");
    else warnings.push("DV8 failed: " + (lastLine(s2, /\S/) || ""));
  }
  execute([NODE, path.join(JS, "manual_template.mjs"), out]);
  if (o.postgres) {
    if (!CHILD_ENV.PG_ADMIN_URL) warnings.push("--postgres requested but there is no PG_ADMIN_URL and no PostgreSQL binaries for a temporary server: database analysis skipped");
    else {
      const [rcp, sp] = execute([NODE, path.join(JS, "pg_analysis.mjs"), out]);
      warnings.push(rcp === 0 ? "postgres: " + (lastLine(sp, /Acceptance|ERROR/) || "no output") : "postgres failed: " + (lastLine(sp, /\S/) || ""));
      rescore("the live database");
    }
  }
  if (o.judge) {
    const jcmd = [NODE, path.join(JS, "judge.mjs"), out, "--model", o.judge, "--votes", str(o.judge_votes)];
    if (o.judge_cmd) jcmd.push("--cmd", o.judge_cmd);
    if (o.allow_same_model) jcmd.push("--allow-same-model");
    const [rcj, sj] = execute(jcmd);
    if (rcj === 0) { rescore("the judge"); warnings.push("judge: " + (lastLine(sj, /Judge|No judgeable/) || "no output")); }
    else warnings.push("the judge failed: " + (lastLine(sj, /\S/) || ""));
  }
  return warnings;
}

function evaluateApp(app, o, dv8) {
  const [agent, level, namedDomain] = identity(path.basename(app));
  const domain = namedDomain || o.domain;
  const runId = namedDomain ? `${path.basename(app)}-r${o.rep}` : `${path.basename(app)}-${domain}-r${o.rep}`;
  const out = path.join(path.resolve(o.results), runId);
  const cmd = [NODE, path.join(JS, "evaluate.mjs"), "run", app, "--out", out, "--agent", agent, "--model", o.model || "n/a", "--level", level, "--domain", domain, "--run-id", runId];
  if (modelMissing(o.model)) cmd.push("--allow-missing-model");
  if (!o.skip_tests) cmd.push("--run-tests");
  if (!o.skip_tests && o.mutation) cmd.push("--mutation");
  if (o.offline) cmd.push("--offline");
  if (o.as_of) cmd.push("--as-of", o.as_of);
  if (o.accept_heuristics) cmd.push("--accept-heuristics");
  const warnings = [copyTokenUsage(app, out, o.usage_dir)];
  if (o.rescore_only) {
    if (!exists(path.join(out, "metrics.json"))) return [runId, `ERROR\nno metrics.json in ${out}: evaluate it once without --rescore`];
    const [rc, output] = execute(rescoreCmd(out));
    if (rc !== 0) return [runId, `ERROR\n${output.slice(-800)}`];
    return [runId, [finalSummary(out), ...warnings.filter(Boolean)].join("; ")];
  }
  const [rc, output] = execute(cmd);
  if (rc !== 0) return [runId, `ERROR\n${output.slice(-800)}`];
  warnings.push(...postCollectionSteps(out, o, dv8));
  return [runId, [finalSummary(out), ...warnings.filter(Boolean)].join("; ")];
}

function recordEnvironment(o, dv8, apps) {
  const res = path.resolve(o.results);
  fs.mkdirSync(res, { recursive: true });
  const rub = readJson(path.join(HERE, "rubric.json"));
  const info = { date: nowIso(), runtime: "node", node: process.version, npm: version(["npm", "--version"]), os: `${os.type()}-${os.release()}-${os.arch()}`,
    generator_model: modelMissing(o.model) ? null : o.model, generator_model_missing: modelMissing(o.model), dv8, apps: apps.map((a) => path.basename(a)),
    options: Object.fromEntries(Object.entries(o).filter(([k]) => k !== "apps")), supported_runtimes: get(get(rub, "supported_runtimes", {}), "date"),
    as_of: o.as_of || nowIso().slice(0, 10) };
  fs.writeFileSync(path.join(res, "environment.json"), dumps(info, 1), "utf8");
}

export function cmdEvaluate(a) {
  const o = options(a);
  if (modelMissing(o.model) && !o.allow_missing_model) { console.log("ERROR: " + MODEL_ERROR); return 2; }
  let apps;
  if (o.apps) apps = o.apps.map((p) => path.resolve(p));
  else {
    const base = o.apps_dir;
    apps = exists(base) ? sorted(fs.readdirSync(base, { withFileTypes: true }).filter((d) => d.isDirectory() && !d.name.startsWith(".")).map((d) => path.resolve(base, d.name))) : [];
  }
  const missing = apps.filter((p) => !exists(p) || !fs.statSync(p).isDirectory());
  if (!apps.length || missing.length) {
    console.log(!apps.length ? "No applications to evaluate." : "Does not exist: " + missing.join(", "));
    console.log("Create apps/<agent>-<level>/ or pass the folders: node js/cli.mjs evaluate path/app1 path/app2");
    return 1;
  }
  const dv8 = o.skip_dv8 || o.rescore_only ? null : findDv8();
  if (!o.skip_dv8 && !o.rescore_only && !dv8) console.log("Warning: DV8 not found; DL and PC will stay pending (use --skip-dv8 to silence this warning).");
  if (!o.rescore_only) recordEnvironment(o, dv8, apps);
  let errors = 0, srv = null;
  try {
    if (o.postgres && !o.rescore_only && !CHILD_ENV.PG_ADMIN_URL) {  // no server given: a disposable one for the whole batch
      try { srv = pgTemp.startServer(); } catch (e) { console.log(`Warning: the temporary PostgreSQL server could not start (${e.message}).`); }
      if (srv) { CHILD_ENV.PG_ADMIN_URL = srv.url; console.log(`PostgreSQL: temporary server on 127.0.0.1:${srv.port} (no PG_ADMIN_URL set).`); }
    }
    apps.forEach((app, i) => {
      console.log(`[${i + 1}/${apps.length}] ${path.basename(app)} …`);
      const [, summary] = evaluateApp(app, o, dv8);
      if (summary.startsWith("ERROR")) errors += 1;
      console.log(`      ${summary}`);
    });
  } finally {
    if (srv) { srv.stop(); if (!process.env.PG_ADMIN_URL) delete CHILD_ENV.PG_ADMIN_URL; }
  }
  const [rc, output] = execute([NODE, path.join(JS, "evaluate.mjs"), "aggregate", path.resolve(o.results)]);
  if (rc !== 0) { console.log("Error while aggregating:\n" + output.slice(-600)); return 1; }
  const p = writeReport(path.resolve(o.results));
  console.log(`\nReport: ${p}`);
  return errors ? 1 : 0;
}

// ───────────────────────── report ─────────────────────────
const LIGHT = { green: "🟢", yellow: "🟡", red: "🔴", undecided: "⚪", not_evaluable: "▨" };

function levelTxt(p) {
  if (get(p, "evaluable") === false) return "▨";
  if (p.level) return SYMBOL[p.level];
  const lo = get(p, "level_min"), hi = get(p, "level_max");
  return lo && hi ? `${get(SYMBOL, lo, "?")}…${get(SYMBOL, hi, "?")}` : "?";
}

const fmtRange = (lo, hi) => (lo === null || lo === undefined ? "n/a" : num(lo) === num(hi) ? fixed(lo, 1) : `${fixed(lo, 1)}–${fixed(hi, 1)}`);

function nativeCoverageRuns(runs) {
  const out = [];
  for (const [d, pf] of runs) {
    let m;
    try { m = readJson(path.join(d, "metrics.json")); } catch { continue; }
    if (get(or(get(m, "tests_run"), {}), "packages", []).some((p) => get(p, "runner") === "node:test")) out.push(pf.meta.run_id);
  }
  return out;
}

function tokenSection(runs) {
  const data = Object.fromEntries(runs.map(([d, pf]) => [pf.meta.run_id, tu.load(path.join(d, tu.RESULT_FILE))]));
  if (!Object.values(data).some(Boolean)) return ["", "## AI token consumption", "", "Not recorded. Record the tokens of each phase with `python token_usage.py scan` and `record` " +
    "(see docs/generating-apps.md) and run evaluate again."];
  const L = ["", "## AI token consumption", "",
    "Tokens the generator agent used to create the application (**initial**) and to implement the additional requirements (**R2**). " +
    "Input includes the prompt-cache reads and writes; output includes reasoning. They are not part of the maintainability score. " +
    "Details per session in `<run>/token_usage.json`.", "",
    "| Application | Initial input | Initial output | **Initial total** | R2 input | R2 output | **R2 total** | R2 / initial | Initial + R2 |",
    "|---|---|---|---|---|---|---|---|---|"];
  for (const [rid, u] of Object.entries(data)) {
    const sm = tu.summary(u) || { phases: {} };
    const i = get(sm.phases, "initial"), r = get(sm.phases, "r2");
    const g = (t, k) => (t ? tu.fmt(t[k]) : "—");
    const ratio = get(get(sm, "r2_vs_initial") || {}, "total_tokens");
    const both = i && r ? tu.fmt(i.total_tokens + r.total_tokens) : "—";
    L.push(`| ${rid} | ${g(i, "input_tokens")} | ${g(i, "output_tokens")} | **${g(i, "total_tokens")}** | ${g(r, "input_tokens")} | ` +
      `${g(r, "output_tokens")} | **${g(r, "total_tokens")}** | ${ratio === null ? "—" : "×" + fixed(ratio, 2)} | ${both} |`);
  }
  return L;
}

export function writeReport(res) {
  const runs = [];
  for (const name of fs.readdirSync(res).sort()) {
    const d = path.join(res, name);
    if (exists(path.join(d, "profile.json")) && exists(path.join(d, "scorecard.json"))) runs.push([d, readJson(path.join(d, "profile.json")), readJson(path.join(d, "scorecard.json")).points]);
  }
  if (!runs.length) throw new Error(`No results in ${res}. Run first: node js/cli.mjs evaluate`);
  const env = exists(path.join(res, "environment.json")) ? readJson(path.join(res, "environment.json")) : {};
  const ids = runs[0][2].map((p) => p.id), names = Object.fromEntries(runs[0][2].map((p) => [p.id, p.name]));
  const subs = Object.keys(runs[0][1].subcharacteristics);
  const noModel = runs.filter((r) => modelMissing(get(r[1].meta, "model"))).map((r) => r[1].meta.run_id);
  const modelTxt = get(env, "generator_model") || (noModel.length ? "NOT RECORDED" : "");
  const now = nowIso().slice(0, 16).replace("T", " ");
  const L = ["# Maintainability report", "", `Generated: ${now} · ${runs.length} application(s)` + (modelTxt ? ` · Generator model: ${modelTxt}` : ""), "",
    ...(noModel.length ? [`> ⚠ **Generator model not recorded** for ${noModel.join(", ")}. ${MODEL_WARNING}`, ""] : []),
    "## Overall result (0–100)", "", "| Application | Level | Overall | " + subs.join(" | ") + " | Complete |", "|---|---|---|" + "---|".repeat(subs.length) + "---|"];
  for (const [, pf] of runs) {
    const m = pf.meta;
    L.push(`| ${m.run_id} | ${str(m.level)} | **${fmtRange(pf.maintainability_min, pf.maintainability_max)}** | ` +
      subs.map((s) => fmtRange(pf.subcharacteristics[s].min, pf.subcharacteristics[s].max)).join(" | ") + ` | ${pf.complete ? "yes" : "no"} |`);
  }
  L.push("", "A range (a–b) indicates pending criteria: the real value lies between both ends until the manual review is completed.", "");
  L.push(...sensitivityMd(sensitivity(runs.map(([, pf, pts]) => [pf.meta, pts]))));
  L.push("## Risk dashboard", "",
    "Semaphore per subcharacteristic (weighted score, worst case of the range; cut-offs in `rubric.json`). A high-severity finding forces red (↑). " +
    "▨ = not evaluable for lack of evidence. Each application folder has `risk_dashboard.html` / `.md` with the full points × subcharacteristics heat map and the module hotspots.", "",
    "| Application | " + subs.join(" | ") + " |", "|---|" + "---|".repeat(subs.length));
  for (const [, pf] of runs) {
    const sem = get(get(pf, "dashboard", {}), "semaphore", {});
    L.push(`| ${pf.meta.run_id} | ` + subs.map((x) => (x in sem ? LIGHT[sem[x].state] + (sem[x].escalated ? " ↑" : "") + " " + fmtRange(sem[x].min, sem[x].max) : "?")).join(" | ") + " |");
  }
  const ne = runs.flatMap(([, pf]) => get(get(pf, "dashboard", {}), "not_evaluable", []).map((x) => [pf.meta.run_id, x.name, x.missing]));
  L.push("", "**Not evaluable (no evidence):** " + (ne.length ? ne.map(([r, n, m]) => `${r}: ${n} (missing ${m.join(", ")})`).join("; ") : "none"), "");
  L.push("### Hotspots (worst files per automatable indicator)", "");
  for (const [, pf] of runs) {
    const hs = get(get(pf, "dashboard", {}), "hotspots", {});
    const parts = [["complexity", "complexity"], ["layer_violations", "layers"], ["cyclic_dependencies", "cycles"]].filter(([k]) => truthy(get(hs, k)))
      .map(([k, t]) => `${t}: ` + hs[k].slice(0, 2).map((x) => `\`${x.file}\` (${x.detail})`).join(", "));
    L.push(`- **${pf.meta.run_id}** — ` + (parts.join("; ") || "none"));
  }
  const arts = Object.fromEntries(runs.filter(([d]) => exists(path.join(d, "artifacts.json"))).map(([d]) => [path.basename(d), readJson(path.join(d, "artifacts.json"))]));
  if (Object.keys(arts).length) {
    const first = Object.values(arts)[0];
    L.push("", "## Input artifacts (Table 27)", "",
      "✔ present · ✘ missing. Core artifacts missing make their points not evaluable; complementary ones are recorded as findings and lower confidence " +
      "(a missing test suite is a High finding); optional ones only enrich the analysis. Details per application in `artifacts.json`.", "",
      "| Artifact | Level | Feeds | " + Object.keys(arts).join(" | ") + " |", "|---|---|---|" + "---|".repeat(Object.keys(arts).length));
    first.forEach((a, i) => L.push(`| ${a.name} | ${a.level} | ${a.feeds.join(", ") || "—"} | ` + Object.values(arts).map((v) => (v[i].present ? "✔" : "✘")).join(" | ") + " |"));
  }
  L.push("", ...ascmmComparisonMd(runs.map(([, pf]) => [pf.meta.run_id, pf])));
  L.push(...tokenSection(runs));
  L.push("", "## Risk heat map", "",
    "🔴 Fails · 🟡 Partial · 🟢 Meets · ⚪ undecided (pending criteria). Rows are ordered by how much of the overall score each point " +
    "puts at stake, so the riskiest points come first.", "", "| Point | " + runs.map((r) => r[1].meta.run_id).join(" | ") + " |", "|---|" + "---|".repeat(runs.length));
  const risks = runs.map(([, pf]) => get(pf, "risk", []));
  const worst = risks.reduce((best, x) => (best === null || x.reduce((a, y) => a + num(y.at_stake_max), 0) > best.reduce((a, y) => a + num(y.at_stake_max), 0) ? x : best), null) || [];
  const order = Object.fromEntries(worst.map((r, i) => [r.id, i]));
  for (const pid of sorted(ids, (i) => order[i] ?? 99))
    L.push(`| ${names[pid]} | ` + runs.map(([, pf]) => { const x = get(pf, "risk", []).find((y) => y.id === pid); return x ? `${x.light} ${fixed(x.at_stake_max, 1)}` : "▨ not evaluable"; }).join(" | ") + " |");
  L.push("", "Each cell: traffic light and overall points at stake in the worst case.", "", "### Top risks per application", "");
  for (const [, pf] of runs) {
    const top = get(pf, "risk", []).filter((x) => num(x.at_stake_max) > 0).slice(0, 3);
    L.push(`- **${pf.meta.run_id}** — ` + (top.map((x) => `${x.light} ${x.name} (${fixed(x.at_stake_max, 1)} pts)`).join("; ") || "no points at risk"));
  }
  L.push("", "## Decision points", "", "✔ Meets · ◐ Partial · ✘ Fails · a…b range due to pending criteria · ? not evaluated", "",
    "| Point | " + runs.map((r) => r[1].meta.run_id).join(" | ") + " |", "|---|" + "---|".repeat(runs.length));
  for (const pid of ids) L.push(`| ${names[pid]} | ` + runs.map(([, , pts]) => levelTxt(pts.find((p) => p.id === pid))).join(" | ") + " |");
  L.push("", "## Pending manual review", "");
  let anyPending = false;
  for (const [d, pf, pts] of runs) {
    const pend = pts.filter((p) => p.pending_criteria.length).map((p) => [p.id, p.pending_criteria]);
    if (pend.length) { anyPending = true; L.push(`- **${pf.meta.run_id}** — ` + pend.map(([i, c]) => `${i}: ${c.join(", ")}`).join("; ") + ` → \`${path.basename(d)}/manual_review.md\``); }
  }
  L.push(...(anyPending ? [] : ["None."]), "", "## Findings per application", "");
  for (const [, pf, pts] of runs) {
    L.push(`### ${pf.meta.run_id}`);
    for (const p of pts) if (["Partial", "Fails"].includes(p.level) || (!p.level && p.level_min !== p.level_max)) L.push(`- **${p.name}** (${levelTxt(p)}): ${p.finding}`);
    L.push("");
  }
  for (const [, pf] of runs) {
    const fs_ = get(pf, "artifact_findings", []);
    if (fs_.length) L.push(`### ${pf.meta.run_id} — findings from missing artifacts`, ...fs_.map((f) => `- **${f.severity}** — ${f.name}: ${f.note}`), "");
  }
  const warn = ["Each level has a single run: differences between levels are not statistically conclusive.",
    "Unless acceptance.json is present, the applications were not run against PostgreSQL (no acceptance gate): it is not known whether they work.",
    "Layer classification is a directory-name heuristic; review `detected_layers.json`."];
  const native = nativeCoverageRuns(runs);
  if (native.length) warn.push(`Test coverage of ${native.join(", ")} was measured with Node's native coverage because c8 was not installed: files that no ` +
    "test loads count as 0% of lines, but their branches do not enter the denominator (branches overestimated).");
  if (runs.some(([d]) => exists(path.join(d, tu.RESULT_FILE)))) warn.push("Tokens come from the agents' own usage records (Claude Code transcripts or results, Codex rollouts) normalized so that input " +
    "includes the cache; a cache read is much cheaper than a fresh input token, so compare totals between agents with care.");
  if (runs.some(([d]) => exists(path.join(d, "dv8", "dv8_metrics.json")))) warn.push("DV8's DL and PC are computed on a matrix derived from dependency-cruiser (DV8 does not analyze JS/TS) and without isolated files.");
  if (noModel.length) warn.push(MODEL_WARNING);
  L.push("## Methodological warnings", "", ...warn.map((x) => `- ${x}`));
  if (Object.keys(env).length) {
    const runtime = get(env, "python") ? `Python ${str(env.python)} · ` : "";
    L.push("", "## Environment", "", `${runtime}Node ${str(get(env, "node"))} · npm ${str(get(env, "npm"))} · DV8: ${get(env, "dv8") || "not used"}`,
      `System: ${str(get(env, "os"))} · evaluated on ${str(get(env, "date"))} · versions and advisories as of ${get(env, "as_of") || String(get(env, "date", "")).slice(0, 10)}` +
      `${get(get(env, "options") || {}, "as_of") ? "" : " (the evaluation date: fix it with --as-of to reproduce the result)"}` +
      ` · supported-runtimes table dated ${str(get(env, "supported_runtimes"))}`);
  }
  const p = path.join(res, "report.md");
  fs.writeFileSync(p, L.join("\n") + "\n", "utf8");
  return p;
}

function cmdReport(a) {
  const p = writeReport(path.resolve(a.results || "results"));
  console.log(fs.readFileSync(p, "utf8"));
  console.log(`(saved to ${p})`);
  return 0;
}

export function parseArgs(argv) {
  const [cmd, ...rest] = argv;
  const a = { cmd, apps: [] };
  const bool = new Set(["allow_missing_model", "allow_same_model", "postgres", "mutation", "rescore", "skip_tests", "skip_dv8", "offline", "accept_heuristics"]);
  for (let i = 0; i < rest.length; i++) {
    const x = rest[i];
    if (!x.startsWith("--")) { a.apps.push(x); continue; }
    const k = x.slice(2).replaceAll("-", "_");
    if (bool.has(k)) a[k] = true;
    else a[k] = ["rep", "judge_votes"].includes(k) ? Number.parseInt(rest[++i], 10) : rest[++i];
  }
  return a;
}

export function main(argv) {
  const a = parseArgs(argv);
  if (a.cmd === "doctor") return cmdDoctor();
  if (a.cmd === "evaluate") return cmdEvaluate(a);
  if (a.cmd === "report") return cmdReport(a);
  console.error("usage: cli.mjs {doctor,evaluate,report} …");
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(e.message); process.exitCode = 1; }
}

