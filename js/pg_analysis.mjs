#!/usr/bin/env node
// pg_analysis.mjs — Data model analysis on a real PostgreSQL database. Port of pg_analysis.py (see it for what it writes and for the
// security note): a fresh eval_<run> database, the app's backend started against it, the acceptance gate and pg_seed through the HTTP
// API, the catalog read with pg_schema.js, and the database dropped. PG_ADMIN_URL is never passed to the backend.
//   PG_ADMIN_URL=postgres://evaluator:secret@localhost:5432/postgres node js/pg_analysis.mjs results/<run> [--app dir] [--skip-seed] [--keep] [--wait 90]
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { get, loadJson, readText, str } from "./lib/py.mjs";
import { HERE } from "./evaluator/common.mjs";
import * as rt from "./pg_runtime.mjs";
import { R2_SUITES, r2Credentials } from "./acceptance_r2.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const readJson = (p) => loadJson(fs.readFileSync(p, "utf8"));

/** pg_schema.js; [returncode, masked output]. */
export function nodePg(args, adminUrl, timeout = 300) {
  const p = spawnSync(process.execPath, [path.join(HERE, "js", "tools", "pg_schema.js"), ...args], { env: { ...process.env, PG_ADMIN_URL: adminUrl }, encoding: "utf8", timeout: timeout * 1000 });
  return [p.status ?? 1, rt.mask(((p.stdout || "") + (p.stderr || "")).trim(), adminUrl)];
}

/** npm install + npm start, the acceptance gate (unless `gate` is false) and the seed of `domain`. An error text or null. */
async function exerciseBackend(be, env, port, res, wait, skipSeed, logFd, domain = "ecommerce", gate = true) {
  if (!fs.existsSync(path.join(be, "node_modules"))) {
    const cmd = rt.npmCmd("install", "--no-audit", "--no-fund");
    spawnSync(cmd[0], cmd.slice(1), { cwd: be, stdio: ["ignore", logFd, logFd], timeout: 900000, windowsHide: true });
  }
  const proc = rt.startProcess(rt.npmCmd("start"), be, env, logFd);
  try {
    if (!(await rt.waitForPort(port, wait))) return `the backend did not open the port within ${wait} s (see backend.log)`;
    await sleep(2000);  // margin for the schema creation and the initial data
    const base = `http://127.0.0.1:${port}`;
    const node = (script, args, timeout) => spawnSync(process.execPath, [path.join(HERE, "js", script), ...args], { stdio: ["ignore", logFd, logFd], timeout: timeout * 1000, windowsHide: true });
    if (gate) node("acceptance_check.mjs", ["--base", base, "--domain", domain, "--out", path.join(res, "acceptance.json"), "--app", path.dirname(be)], 900);
    if (!skipSeed) node("pg_seed.mjs", ["--base", base, "--domain", domain, "--output", path.join(res, "seed.json")], 600);
    await sleep(2000);  // let PostgreSQL report index usage before the catalog is read
    return null;
  } finally { rt.killTree(proc); }
}

/** Which acceptance suite applies: "r1" (original requirements), "r2" (an app that implements r2 and a domain with an r2 suite) or
 *  null (an r2 app of a domain without one: the gate is skipped). */
function gateSuite(app, res, domain) {
  if (!rt.hasR2(app)) return "r1";
  if (domain in R2_SUITES) return "r2";
  fs.rmSync(path.join(res, "acceptance.json"), { force: true });
  fs.rmSync(path.join(res, "contract_conformance.json"), { force: true });
  console.log(`Acceptance gate skipped: ${rt.R2_GATE_SKIP}.`);
  return null;
}

/** The r2 gate on its own databases (the suite creates, edits and deletes catalog records and coupons, which must not reach the
 *  database the catalog analysis reads): <db>_acc as DATABASE_URL and <db>_rep as REPLICA_DATABASE_URL, SQLSERVER_URL unset, and the
 *  bootstrap accounts of Requirement 4. Both databases are dropped at the end. An error text or null. */
async function r2Gate({ be, baseEnv, adminUrl, db, res, wait, domain, logFd }) {
  const acc = db.slice(0, 51) + "_acc", rep = db.slice(0, 51) + "_rep", made = [];
  try {
    for (const name of [acc, rep]) {
      const [rc, out] = nodePg(["create", name], adminUrl);
      console.log(out);
      if (rc !== 0) return `could not create ${name} for the r2 gate`;
      made.push(name);
    }
    const creds = r2Credentials(), port = rt.freePort();
    const env = { ...baseEnv, ...creds, PORT: String(port), DATABASE_URL: rt.dbUrl(adminUrl, acc), REPLICA_DATABASE_URL: rt.dbUrl(adminUrl, rep) };
    delete env.SQLSERVER_URL;
    console.log(`r2 acceptance gate: databases ${acc} and ${rep}; backend on port ${port} …`);
    const proc = rt.startProcess(rt.npmCmd("start"), be, env, logFd);
    try {
      if (!(await rt.waitForPort(port, wait))) return `the backend did not open the port within ${wait} s for the r2 gate (see backend.log)`;
      await sleep(2000);
      spawnSync(process.execPath, [path.join(HERE, "js", "acceptance_check.mjs"), "--base", `http://127.0.0.1:${port}`, "--domain", domain, "--suite", "r2",
        "--out", path.join(res, "acceptance.json"), "--app", path.dirname(be)], { env: { ...process.env, ...creds }, stdio: ["ignore", logFd, logFd], timeout: 900000, windowsHide: true });
      return null;
    } finally { rt.killTree(proc); }
  } finally {
    for (const name of made) { const [rc, out] = nodePg(["drop", name], adminUrl); console.log(out); if (rc !== 0) console.log(`COULD NOT DROP ${name}: drop it by hand`); }
  }
}

/** npm install when needed, then the r2 gate; a failure to run it is reported, never fatal for the analysis. */
async function runR2Gate(o) {
  if (!fs.existsSync(path.join(o.be, "node_modules"))) {
    const cmd = rt.npmCmd("install", "--no-audit", "--no-fund");
    spawnSync(cmd[0], cmd.slice(1), { cwd: o.be, stdio: ["ignore", o.logFd, o.logFd], timeout: 900000, windowsHide: true });
  }
  const gateError = await r2Gate(o);
  if (gateError) console.log(`r2 acceptance gate not run: ${gateError}`);
}

/** [error or null, database name]. The database is dropped at the end unless `keep`. */
export async function analyze(res, adminUrl, app = null, skipSeed = false, keep = false, wait = 90) {
  res = path.resolve(res);
  const meta = readJson(path.join(res, "meta.json"));
  app = path.resolve(app || readJson(path.join(res, "metrics.json")).app);
  const be = path.join(app, "backend");
  if (!fs.existsSync(be)) return [`${be} does not exist`, null];
  const db = rt.evalDbName(get(meta, "run_id", path.basename(res)));
  if (!rt.validEvalDb(db)) return [`refusing database name '${db}'`, db];
  const url = rt.dbUrl(adminUrl, db), port = rt.freePort();
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => k !== "PG_ADMIN_URL" && k !== "NODE_TEST_CONTEXT"));
  Object.assign(env, { PORT: String(port), DATABASE_URL: url });
  Object.assign(env, rt.backendSecrets(be, env));  // random JWT_SECRET & co., or a backend that validates them does not start
  console.log(`Database ${db}; backend on port ${port} …`);
  let [rc, out] = nodePg(["create", db], adminUrl);
  console.log(out);
  if (rc !== 0) return ["could not create the database (see above)", db];
  let error = null;
  const domain = get(meta, "domain") || "ecommerce";
  const suite = gateSuite(app, res, domain);
  const logPath = path.join(res, "backend.log");
  try {
    const fd = fs.openSync(logPath, "w");
    try {
      if (suite === "r2") await runR2Gate({ be, baseEnv: env, adminUrl, db, res, wait, domain, logFd: fd });
      error = await exerciseBackend(be, env, port, res, wait, skipSeed, fd, domain, suite === "r1");
    } finally { fs.closeSync(fd); }
    if (error === null) {
      [rc, out] = nodePg(["dump", db, path.join(res, "pg_schema.json")], adminUrl);
      console.log(out);
      if (rc !== 0) error = "pg_schema.js dump failed";
      else if (!Object.keys(get(readJson(path.join(res, "pg_schema.json")), "tables") || {}).length) {
        fs.rmSync(path.join(res, "pg_schema.json"));  // nothing to read: the evaluator falls back to the static analysis
        error = "the database has no tables after exercising the app (does `npm start` create the schema?); static analysis is used";
      }
    }
  } finally {
    if (!keep) {
      [rc, out] = nodePg(["drop", db], adminUrl);
      console.log(out);
      if (rc !== 0) error = (error ? error + "; " : "") + `COULD NOT DROP ${db}: drop it by hand`;
    }
    if (fs.existsSync(logPath)) fs.writeFileSync(logPath, rt.mask(readText(logPath), adminUrl), "utf8");
  }
  if (fs.existsSync(path.join(res, "acceptance.json"))) console.log(`Acceptance: ${str(get(readJson(path.join(res, "acceptance.json")), "acceptance_pct", "n/a"))} %`);
  return [error, db];
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), o = { wait: "90" };
  let res = null;
  for (let i = 0; i < args.length; i++) {
    const x = args[i];
    if (!x.startsWith("--")) { res = x; continue; }
    const k = x.slice(2).replaceAll("-", "_");
    if (k === "skip_seed" || k === "keep") o[k] = true; else o[k] = args[++i];
  }
  const admin = process.env.PG_ADMIN_URL;
  if (!admin) { console.error("Set the PG_ADMIN_URL environment variable (connection string of a role that can create databases). See the header of js/pg_analysis.mjs"); process.exit(1); }
  if (!res) { console.error("usage: node js/pg_analysis.mjs results/<run> [--app dir] [--skip-seed] [--keep] [--wait 90]"); process.exit(2); }
  const [error] = await analyze(res, admin, o.app, Boolean(o.skip_seed), Boolean(o.keep), Number.parseInt(o.wait, 10));
  if (error) { console.log("ERROR:", error); process.exitCode = 1; }
}
