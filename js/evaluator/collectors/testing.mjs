// testing.mjs — Tests: static count of test cases, execution of the suites with coverage (c8, node --test, Jest), and mutation
// testing with StrykerJS. Port of evaluator/collectors/{testing,mutation}.py.
import fs from "node:fs";
import path from "node:path";
import { readText, F, get, loadJson, or, pyRound, sorted, splitlines, str, truthy } from "../../lib/py.mjs";
import { HERE, RUBRIC } from "../common.mjs";
import { WIN, rel, sh, walk } from "../sys.mjs";

export function staticTests(ast, app) {
  const files = ast.files.filter((f) => f.test).map((f) => f.path);
  let n = 0;
  for (const f of files) {
    try { n += [...readText(path.join(app, f)).matchAll(/\b(?:it|test)(?:\.each)?\s*\(/g)].length; } catch { /* unreadable */ }
  }
  return { test_files: files, test_cases: n };
}

const normcase = (p) => (WIN ? path.normalize(p).toLowerCase() : path.normalize(p));

/** LF/LH/BRF/BRH of an lcov.info, plus the .js/.ts sources no test loaded (their non-blank lines, uncovered). */
export function parseLcov(lcov, d) {
  const tot = { lines_total: 0, lines_cov: 0, br_total: 0, br_cov: 0, unloaded: 0 };
  const seen = new Set();
  for (const ln of splitlines(readText(lcov))) {
    if (ln.startsWith("SF:")) seen.add(normcase(path.isAbsolute(ln.slice(3)) ? ln.slice(3) : path.join(d, ln.slice(3))));
    else if (ln.startsWith("LF:")) tot.lines_total += Number.parseInt(ln.slice(3), 10);
    else if (ln.startsWith("LH:")) tot.lines_cov += Number.parseInt(ln.slice(3), 10);
    else if (ln.startsWith("BRF:")) tot.br_total += Number.parseInt(ln.slice(4), 10);
    else if (ln.startsWith("BRH:")) tot.br_cov += Number.parseInt(ln.slice(4), 10);
  }
  for (const f of walk(d)) {
    if (![".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"].includes(path.extname(f))) continue;
    const parts = path.resolve(f).split(path.sep);
    if (/\.(test|spec)\./.test(path.basename(f)) || parts.some((x) => ["tests", "__tests__", "coverage"].includes(x))) continue;
    if (seen.has(normcase(f))) continue;
    let n;
    try { n = splitlines(readText(f)).filter((x) => x.trim()).length; } catch { continue; }
    tot.lines_total += n; tot.unloaded += 1;
  }
  return tot;
}

export function runTests(app, pkgs, testCmd, out) {
  const res = { executed: true, packages: [], lines_total: 0, lines_cov: 0, br_total: 0, br_cov: 0, all_passed: true, ran_any: false };
  for (const p of pkgs) {
    const script = get(p.scripts, "test", "");
    if (!script || script.includes("no test specified")) continue;
    const d = path.join(app, p.dir);
    if (!fs.existsSync(path.join(d, "node_modules"))) sh(["npm", "install", "--no-audit", "--no-fund"], { cwd: d, timeout: 900 });
    const native = !testCmd && /\bnode\b.*--test\b|node:test/.test(script);
    const lcov = path.join(d, "coverage", "lcov.info");
    const c8 = path.join(HERE, "node_modules", "c8", "bin", "c8.js");
    let runner = "node:test", cmd;
    if (native && fs.existsSync(c8)) {  // c8 --all also instruments the sources no test loads
      runner = "c8";
      cmd = ["node", c8, "--all", "--src=.", "--reporter=lcovonly", "--reports-dir=coverage", "--exclude=**/{tests,test,__tests__,coverage,dist,build}/**",
        "--exclude=**/*.{test,spec}.*", "--exclude=**/*.config.*", process.execPath, "--test"];
    } else if (native) {
      fs.mkdirSync(path.dirname(lcov), { recursive: true });
      cmd = ["node", "--test", "--experimental-test-coverage", "--test-coverage-exclude=**/*.test.*", "--test-coverage-exclude=**/{tests,__tests__,coverage}/**",
        "--test-reporter=spec", "--test-reporter-destination=stdout", "--test-reporter=lcov", `--test-reporter-destination=${lcov}`];
    } else {
      cmd = testCmd ? testCmd.split(/\s+/) : ["npm", "test", "--silent", "--", "--coverage", "--coverageReporters=json-summary", "--watchAll=false",
        "--collectCoverageFrom=**/*.{js,jsx,ts,tsx}", "--collectCoverageFrom=!**/node_modules/**", "--collectCoverageFrom=!**/{tests,__tests__,coverage,dist,build}/**",
        "--collectCoverageFrom=!**/*.{test,spec}.*"];
    }
    const cs = path.join(d, "coverage", "coverage-summary.json");
    for (const stale of [lcov, cs]) fs.rmSync(stale, { force: true });  // a report of an earlier run is not this run's result
    const [rc, so, se] = sh(cmd, { cwd: d, timeout: 900, env: { ...process.env, CI: "true" } });
    const entry = { dir: p.dir, rc, tail: (so + se).slice(-400) };
    res.ran_any = true;
    if (rc !== 0) res.all_passed = false;
    if (native && fs.existsSync(lcov)) {
      const t = parseLcov(lcov, d);
      res.lines_total += t.lines_total; res.lines_cov += t.lines_cov; res.br_total += t.br_total; res.br_cov += t.br_cov;
      entry.coverage = { lines: t.lines_total ? F(pyRound((100.0 * t.lines_cov) / t.lines_total, 1)) : F(0.0),
        branches: t.br_total ? F(pyRound((100.0 * t.br_cov) / t.br_total, 1)) : null, runner, unloaded_files: t.unloaded };
    } else if (fs.existsSync(cs)) {
      const t = loadJson(fs.readFileSync(cs, "utf8")).total;
      res.lines_total += t.lines.total; res.lines_cov += t.lines.covered; res.br_total += t.branches.total; res.br_cov += t.branches.covered;
      entry.coverage = { lines: t.lines.pct, branches: t.branches.pct };
    }
    res.packages.push(entry);
  }
  return res;
}

// ───────────────────────── mutation (StrykerJS) ─────────────────────────
const STRYKER = path.join(HERE, "node_modules", "@stryker-mutator", "core", "bin", "stryker.js");
const DETECTED = ["Killed", "Timeout"], UNDETECTED = ["Survived", "NoCoverage"];
const within = (p, d) => path.resolve(p).startsWith(path.resolve(d));

function mutateFiles(app, d, ast, nested) {
  const out = [];
  for (const f of ast.files) {
    const p = path.resolve(app, f.path);
    if (f.test || !within(p, d) || nested.some((n) => within(p, n))) continue;
    const r = rel(p, d);
    if (/\.config\.|\.d\.ts$|(^|\/)(migrations|seeders|seeds)\//.test(r)) continue;
    out.push(r);
  }
  return sorted(out);
}

export function mutationScore(counts) {
  const det = DETECTED.reduce((a, s) => a + (counts[s] ?? 0), 0), und = UNDETECTED.reduce((a, s) => a + (counts[s] ?? 0), 0);
  return det + und ? F(pyRound((100.0 * det) / (det + und), 1)) : null;
}

function runPackage(d, files, work, testCmd = null) {
  const T = RUBRIC.mutation;
  const tag = path.basename(d).replace(/[^\w.-]/g, "_");
  const report = path.join(work, `${tag}.mutation.json`), tmp = path.join(work, `${tag}-sandbox`);
  fs.rmSync(report, { force: true });
  const posix = (p) => p.split(path.sep).join("/");
  const cfg = { testRunner: "command", commandRunner: { command: testCmd || "npm test" }, mutate: files, reporters: ["json"], jsonReporter: { fileName: posix(report) },
    tempDirName: posix(tmp), cleanTempDir: true, concurrency: T.concurrency, timeoutMS: T.timeout_ms, logLevel: "warn", plugins: [],
    ignorePatterns: ["coverage", "dist", "build", ".stryker-tmp", "reports"] };
  const cfgf = path.join(work, `${tag}.stryker.json`);
  fs.writeFileSync(cfgf, JSON.stringify(cfg, null, 1), "utf8");
  const [rc, so, se] = sh(["node", STRYKER, "run", cfgf], { cwd: d, timeout: 60 * T.max_minutes_per_package });
  fs.rmSync(tmp, { recursive: true, force: true });
  if (!fs.existsSync(report)) return { ok: false, error: rc === 124 ? "time limit reached" : ((se || so).trim().slice(-400) || `exit ${rc}`) };
  const r = loadJson(fs.readFileSync(report, "utf8"));
  const counts = {}, undetected = [];
  for (const [fname, f] of Object.entries(or(get(r, "files"), {}))) {
    for (const mu of get(f, "mutants", [])) {
      counts[mu.status] = (counts[mu.status] ?? 0) + 1;
      if (UNDETECTED.includes(mu.status)) {
        const line = get(or(get(or(get(mu, "location"), {}), "start"), {}), "line");
        undetected.push([fname, or(line, 0), str(get(mu, "mutatorName")), mu.status, line]);
      }
    }
  }
  // the report lists the mutants in the order the workers finished them, which changes between runs: sorted, so the 20 kept are stable
  const survivors = sorted(undetected).slice(0, 20).map(([fn, , mut, st, line]) => `${fn}:${str(line)} ${mut} (${st})`);
  return { ok: true, mutants: Object.values(counts).reduce((a, x) => a + x, 0), statuses: counts, score: mutationScore(counts), survivors };
}

export function runMutation(app, pkgs, ast, out, testCmd = null) {
  if (!fs.existsSync(STRYKER)) return { ok: false, error: "StrykerJS is not installed: run `npm install` in the framework folder" };
  app = path.resolve(app);
  const work = path.resolve(out, "mutation");
  fs.mkdirSync(work, { recursive: true });
  const dirs = pkgs.map((p) => path.resolve(app, p.dir));
  const version = JSON.parse(fs.readFileSync(path.join(path.dirname(path.dirname(STRYKER)), "package.json"), "utf8")).version;
  const res = { ok: false, tool: `StrykerJS ${version} (command runner)`, packages: [], statuses: {}, score: null };
  const total = {};
  pkgs.forEach((p, k) => {
    const d = dirs[k];
    const script = get(or(get(p, "scripts"), {}), "test", "");
    if (!script || script.includes("no test specified")) return;
    const nested = dirs.filter((o) => o !== d && o.startsWith(d + path.sep));
    const files = mutateFiles(app, d, ast, nested);
    if (!files.length) { res.packages.push({ dir: p.dir, ok: false, error: "no production source files to mutate" }); return; }
    const r = runPackage(d, files, work, testCmd);
    res.packages.push({ dir: p.dir, files: files.length, ...r });
    if (r.ok) { for (const [s, n] of Object.entries(r.statuses)) total[s] = (total[s] ?? 0) + n; res.ok = true; }
  });
  res.statuses = total; res.score = mutationScore(total);
  if (!res.packages.length) res.error = "no package with a test script";
  else if (!res.ok) res.error = res.packages.map((x) => `${x.dir}: ${str(get(x, "error"))}`).join("; ").slice(0, 600);
  return res;
}
