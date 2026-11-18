// tools.mjs — The collectors that run a tool on the app: ast_metrics.js, jscpd, dependency-cruiser, the contract (yaml + Spectral),
// Knip and ESLint. Port of evaluator/collectors/{source,duplication,dependencies,contract,knip,lint}.py.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";
import { get, loadJson, or, sorted, str } from "../../lib/py.mjs";
import { HERE, RUBRIC } from "../common.mjs";
import { rel, sh, walk } from "../sys.mjs";
import { findPackages } from "./packages.mjs";

const require = createRequire(import.meta.url);
const NM = path.join(HERE, "node_modules");
const exists = (p) => fs.existsSync(p);
const readJson = (p) => loadJson(fs.readFileSync(p, "utf8"));

// ───────────────────────── AST (ast_metrics.js) ─────────────────────────
export function runAst(app, out) {
  const f = path.join(out, "ast.json");
  const [rc, so, se] = sh(["node", path.join(HERE, "ast_metrics.js"), app, f], { timeout: 600 });
  if (rc !== 0) throw new Error(`ast_metrics.js failed:\n${se || so}`);
  return readJson(f);
}

// ───────────────────────── duplication (jscpd, CWE-1041) ─────────────────────────
export function runDuplication(app, out) {
  const T = RUBRIC.thresholds.duplication;
  const jscpd = path.join(NM, "jscpd", "bin", "jscpd");
  if (!exists(jscpd)) return { ok: false, reason: "jscpd not installed (npm install)" };
  app = path.resolve(app);
  const d = path.resolve(out, "jscpd");
  fs.rmSync(d, { recursive: true, force: true });
  const ign = [...["node_modules", "tests", "test", "__tests__", "coverage", "dist", "build"].map((x) => `**/${x}/**`), "**/*.test.*", "**/*.spec.*", "**/*.min.js"].join(",");
  const [rc, so, se] = sh(["node", jscpd, ".", "--silent", "--reporters", "json", "--output", d.split(path.sep).join("/"), "--min-lines", str(T.min_lines),
    "--min-tokens", str(T.min_tokens), "--format", "javascript,typescript,jsx,tsx", "--ignore", ign], { cwd: app, timeout: 300 });
  const rep = path.join(d, "jscpd-report.json");
  if (!exists(rep)) return { ok: false, reason: (se || so).slice(-200) || `rc=${rc}` };
  const r = readJson(rep), t = r.statistics.total;
  const top = sorted(get(r, "duplicates", []), (c) => -c.lines).slice(0, 5);
  const name = (f) => path.relative(app, path.resolve(app, f)).replaceAll("\\", "/");
  return { ok: true, pct: t.percentage, clones: t.clones, duplicated_lines: t.duplicatedLines, lines: t.lines,
    top: top.map((c) => `${name(c.firstFile.name)}:${c.firstFile.start} ≈ ${name(c.secondFile.name)}:${c.secondFile.start} (${c.lines} lines)`) };
}

// ───────────────────────── dependency graph (dependency-cruiser) ─────────────────────────
export function runDepcruise(app, out) {
  const cfg = { forbidden: [{ name: "no-circular", severity: "warn", from: {}, to: { circular: true } }],
    options: { doNotFollow: { path: "node_modules" },
      exclude: { path: String.raw`(^|/)(node_modules|dist|build|coverage|\.git)/|(__tests__|__mocks__)|\.(test|spec)\.[cm]?[jt]sx?$|(^|/)(tests?|e2e|cypress)/` },
      moduleSystems: ["es6", "cjs"], tsPreCompilationDeps: true } };
  const cfgf = path.join(out, "depcruise.config.json");
  fs.writeFileSync(cfgf, JSON.stringify(cfg), "utf8");
  const bin = path.join(NM, "dependency-cruiser", "bin", "dependency-cruise.mjs");
  const [, so, se] = sh(["node", bin, "--config", cfgf, "--output-type", "json", "."], { cwd: app, timeout: 600 });
  let data;
  try { data = JSON.parse(so); } catch { return { error: (se || so).slice(0, 500), modules: [], cycles: [] }; }
  const mods = [], cycles = new Map();
  for (const m of get(data, "modules", [])) {
    const deps = get(m, "dependencies", []).map((d) => ({ to: get(d, "resolved"), local: !d.coreModule && !d.couldNotResolve && !String(get(d, "resolved", "")).includes("node_modules"), module: get(d, "module") }));
    mods.push({ source: m.source, deps });
  }
  for (const v of get(get(data, "summary", {}), "violations", [])) {
    const c = get(v, "cycle");
    if (c && c.length) {
      const names = sorted([...new Set(c.map((x) => (x && typeof x === "object" ? x.name : x)))]);
      cycles.set(JSON.stringify(names), names);
    }
  }
  return { modules: mods, cycles: sorted([...cycles.values()]) };
}

// ───────────────────────── contract (OpenAPI / Swagger) ─────────────────────────
function contractRank(p) {
  const labels = [...get(get(RUBRIC, "relational", {}), "doc_versions", [])];
  let version = labels.findIndex((lb) => p.toLowerCase().includes(`docs/${lb}/`.toLowerCase()));
  if (version < 0) version = labels.length;
  return [version, p.toLowerCase().startsWith("docs/") ? 0 : 1, p.split("/").length - 1, p];
}

export const findContracts = (app) => sorted([...walk(app)].filter((p) => /^(openapi|swagger)[\w.-]*\.(json|ya?ml)$/i.test(path.basename(p))).map((p) => rel(p, app)), contractRank);

function parseContract(file) {
  const t = fs.readFileSync(file, "utf8");
  return file.endsWith(".json") ? JSON.parse(t) : require(path.join(NM, "yaml")).parse(t);
}

export function runContract(app, out, contracts) {
  const info = { files: contracts, spectral_errors: null, paths: [], properties: [] };
  if (!contracts.length) return info;
  const file = path.join(app, contracts[0]);
  try {  // operations, plus the base paths the contract declares (servers[].url, basePath)
    const d = parseContract(file);
    const ops = [];
    for (const [p, v] of Object.entries(d.paths || {})) for (const m of Object.keys(v || {})) if (["get", "post", "put", "patch", "delete"].includes(m)) ops.push([m.toUpperCase(), p]);
    const bases = (d.servers || []).map((s) => { try { return new URL(String(s.url || ""), "http://h").pathname; } catch { return ""; } });
    if (d.basePath) bases.push(String(d.basePath));
    info.paths = ops; info.bases = bases.map((b) => b.replace(/\/+$/, ""));
  } catch { /* as in Python: no operations */ }
  try {
    const d = parseContract(file), s = new Set();
    const w = (o) => { if (o && typeof o === "object") for (const [k, v] of Object.entries(o)) { if (k === "properties" && v && typeof v === "object") Object.keys(v).forEach((x) => s.add(x)); w(v); } };
    w(d);
    info.properties = [...s];
  } catch { /* no properties */ }
  const ruleset = path.join(out, ".spectral.yaml");
  fs.writeFileSync(ruleset, 'extends: ["spectral:oas"]\n', "utf8");
  const [, so] = sh(["node", path.join(NM, "@stoplight", "spectral-cli", "dist", "index.js"), "lint", file, "--ruleset", ruleset, "-f", "json", "-q"], { timeout: 120 });
  try { info.spectral_errors = JSON.parse(so || "[]").filter((x) => get(x, "severity") === 0).length; } catch { /* not measured */ }
  return info;
}

// ───────────────────────── Knip (knip_metrics.js) ─────────────────────────
const EXTS = "js,mjs,cjs,jsx,ts,tsx,mts,cts";
const entryGlobs = () => {
  const T = RUBRIC.thresholds.dead_code;
  return [`**/{${T.entry_points.join(",")}}.{${EXTS}}`, ...get(T, "entry_globs", [])];
};
const joinRd = (rd, p) => (rd === "." ? p : `${rd}/${p}`);

export function runKnip(app, out) {
  if (!exists(path.join(NM, "knip", "package.json"))) return { ok: false, error: "Knip is not installed: run `npm install` in the framework folder" };
  const pkgs = findPackages(app), work = path.join(out, "knip");
  fs.mkdirSync(work, { recursive: true });
  const res = { ok: true, version: null, packages: [], files: [], dependencies: [], devDependencies: [], binaries: [], unlisted: [], unresolved: [], exports: [],
    config_load_errors: [], overridden_plugins: {} };
  const env = { ...process.env, NO_EXEC_ROOT: String(app) };
  for (const d of pkgs) {
    const rd = rel(d, app) || ".";
    const dr = path.resolve(d) + path.sep;
    const nested = pkgs.filter((o) => o !== d && path.resolve(o).startsWith(dr)).map((o) => rel(o, d));
    const tag = rd.replace(/[^\w.-]/g, "_");
    const req = path.join(work, `${tag}.request.json`), raw = path.join(work, `${tag}.json`);
    fs.writeFileSync(req, JSON.stringify({ dir: String(d), root: String(app), nested, entry: entryGlobs(), config_file: path.join(work, `${tag}.knip.json`) }), "utf8");
    const [rc, so, se] = sh(["node", "--import", pathToFileURL(path.join(HERE, "no_exec_guard.mjs")).href, path.join(HERE, "knip_metrics.js"), req, raw], { timeout: 900, env });
    let r;
    try { r = readJson(raw); } catch { r = { ok: false, error: (se || so || `exit ${rc}`).slice(-2000) }; }
    res.packages.push({ dir: rd, ok: get(r, "ok", false), error: get(r, "error") });
    if (!get(r, "ok")) { res.ok = false; continue; }
    res.version = r.version;
    res.files.push(...r.files.map((f) => joinRd(rd, f)));
    for (const k of ["dependencies", "devDependencies", "binaries"]) res[k].push(...r[k].map((x) => `${rd}:${x}`));
    for (const k of ["unlisted", "unresolved"]) res[k].push(...r[k].map((x) => ({ file: joinRd(rd, x.file), name: x.name })));
    res.exports.push(...r.exports.map((x) => ({ ...x, file: joinRd(rd, x.file) })));
    res.config_load_errors.push(...r.config_load_errors.map((x) => `${rd}: ${x}`));
    if (Object.keys(r.overridden_plugins || {}).length) res.overridden_plugins[rd] = r.overridden_plugins;
  }
  if (!pkgs.length) Object.assign(res, { ok: false, error: "no package.json in the app" });
  else if (!res.ok) res.error = res.packages.filter((p) => !p.ok).map((p) => `${p.dir}: ${or(p.error, "").slice(0, 300)}`).join("; ");
  return res;
}

// ───────────────────────── ESLint + SonarJS (lint_metrics.js) ─────────────────────────
const S1192 = "sonarjs/no-duplicate-string", S3776 = "sonarjs/cognitive-complexity", MCCABE = "complexity";

export function lintRules() {
  const T = RUBRIC.thresholds.configuration;
  const rules = { [S1192]: ["error", { threshold: T.dup_literal_threshold, ignoreStrings: T.dup_literal_ignore.join(",") }], [S3776]: ["error", 0], [MCCABE]: ["error", { max: 0 }] };
  const cwe = {};
  for (const [c, d] of Object.entries(get(get(RUBRIC, "lint", {}), "ascmm", {}))) for (const [r, setting] of Object.entries(d.rules)) { rules[r] = setting; cwe[r] = c; }
  return [rules, cwe];
}

const lintAvailable = () => ["eslint", "eslint-plugin-sonarjs", "typescript-eslint"].every((p) => exists(path.join(NM, p, "package.json")));

export function runLint(app, out, files) {
  if (!lintAvailable()) return { ok: false, error: "ESLint is not installed: run `npm install` in the framework folder" };
  const [rules, cwe] = lintRules();
  const req = path.join(out, "lint_request.json"), raw = path.join(out, "lint_raw.json");
  fs.writeFileSync(req, JSON.stringify({ files, rules }), "utf8");
  const [rc, so, se] = sh(["node", path.join(HERE, "lint_metrics.js"), app, req, raw], { timeout: 900 });
  let r;
  try { r = readJson(raw); } catch { r = { ok: false, error: (se || so || `exit ${rc}`).slice(-2000) }; }
  if (!get(r, "ok")) return { ok: false, error: or(get(r, "error"), "").slice(-2000) };
  return summarize(r, cwe);
}

/** Reports of lint_metrics.js grouped by use: per-function McCabe and cognitive values, S1192 literals, occurrences per CWE. */
export function summarize(r, cwe) {
  const res = { ok: true, versions: r.versions, files: r.files, parse_errors: r.parse_errors, mccabe: [], cognitive: [], dup_strings: [],
    ascmm: Object.fromEntries(Object.keys(get(get(RUBRIC, "lint", {}), "ascmm", {})).map((c) => [c, []])) };
  const seen = new Set();
  for (const x of r.messages) {
    const loc = { file: x.file, line: x.line };
    if (x.rule === MCCABE || x.rule === S3776) {
      const n = /(?:complexity of|Complexity from) (\d+)/.exec(x.message);
      if (n) res[x.rule === MCCABE ? "mccabe" : "cognitive"].push({ ...loc, value: Number.parseInt(n[1], 10) });
    } else if (x.rule === S1192) {
      const n = /\b(\d+) times\b/.exec(x.message);
      res.dup_strings.push({ ...loc, literal: get(x, "text"), times: n ? Number.parseInt(n[1], 10) : null });
    } else if (Object.prototype.hasOwnProperty.call(cwe, x.rule) && !seen.has(JSON.stringify([x.rule, x.file, x.line]))) {
      // one occurrence per rule and line: no-mixed-operators reports each operator of `a && b || c`
      seen.add(JSON.stringify([x.rule, x.file, x.line]));
      res.ascmm[cwe[x.rule]].push({ ...loc, end_line: x.endLine, rule: x.rule, message: x.message.slice(0, 160) });
    }
  }
  return res;
}
