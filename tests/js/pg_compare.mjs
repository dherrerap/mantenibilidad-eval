// Runs pg_analysis.py and pg_analysis.mjs on the same app (a copy without the r2 markers, so that the acceptance gate runs), each on its
// own copy of the run and its own fresh database of one temporary PostgreSQL server, and prints the files that differ.
// Used by tests/js/pg.slow.mjs; also runnable by hand:  node tests/js/pg_compare.mjs <run folder> <app folder> <work folder>
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { startServer } from "../../js/pg_temp.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
export const OUT_FILES = ["acceptance.json", "contract_conformance.json", "seed.json", "pg_schema.json"];

/** The files of one analysis with what depends on the moment or the port removed: the backend's port (the base URL) and the
 *  index-usage counters PostgreSQL updates in the background. */
export function normalized(dir, f) {
  const p = path.join(dir, f);
  if (!fs.existsSync(p)) return null;
  const d = JSON.parse(fs.readFileSync(p, "utf8"));
  if (f === "acceptance.json") d.base = "<base>";
  if (f === "pg_schema.json") for (const t of Object.values(d.tables || {})) for (const i of t.indexes || []) delete i.scans;
  // the timestamps the app itself writes (createdAt of an order…) change from one run to the other
  return JSON.stringify(d, null, 1).replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?/g, "<time>");
}

export function compare(run, app, work) {
  const appCopy = path.join(work, "app", path.basename(app));
  fs.cpSync(app, appCopy, { recursive: true, filter: (s) => !s.split(path.sep).includes("node_modules") });
  for (const m of ["r2-additional-requirements.md", "PROMPT-R2.md"]) fs.rmSync(path.join(appCopy, m), { force: true });
  const srv = startServer();
  if (!srv) throw new Error("no PostgreSQL binaries");
  const out = {};
  try {
    for (const [side, cmd] of [["py", ["python", path.join(ROOT, "python", "pg_analysis.py")]], ["js", [process.execPath, path.join(ROOT, "js", "pg_analysis.mjs")]]]) {
      const res = path.join(work, side);
      fs.mkdirSync(res, { recursive: true });
      for (const f of ["metrics.json", "meta.json"]) fs.copyFileSync(path.join(run, f), path.join(res, f));
      const p = spawnSync(cmd[0], [...cmd.slice(1), res, "--app", appCopy], { cwd: ROOT, encoding: "utf8", timeout: 1800000,
        env: { ...process.env, PG_ADMIN_URL: srv.url, PYTHONIOENCODING: "utf-8", NODE_TEST_CONTEXT: "" } });
      out[side] = { rc: p.status, log: (p.stdout || "") + (p.stderr || "") };
    }
  } finally { srv.stop(); }
  const diffs = OUT_FILES.filter((f) => normalized(path.join(work, "js"), f) !== normalized(path.join(work, "py"), f));
  return { diffs, out };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [run, app, work] = process.argv.slice(2);
  const r = compare(run, app, work);
  console.log(JSON.stringify({ diffs: r.diffs, rc: { py: r.out.py.rc, js: r.out.js.rc } }));
  for (const s of ["py", "js"]) console.log(`--- ${s}\n` + r.out[s].log.slice(-1500));
}
