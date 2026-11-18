// End-to-end differential test of the entry points: every run of results/ is copied twice; the Python command runs on one copy and the
// JavaScript one on the other, and every file they write must be the same text (CRLF from Python's write_text on Windows normalized).
// Covers evaluate rescore, manual_template, dv8_metrics (when DV8 is installed), evaluate aggregate and evaluate run (offline).
//   npm run test:js:entry            (slow: it scores every run twice and evaluates one app twice)
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cmdAggregate, cmdRescore, cmdRun } from "../../js/evaluate.mjs";
import { writeTemplates } from "../../js/manual_template.mjs";
import { dv8Metrics, findDv8 } from "../../js/dv8_metrics.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const RESULTS = path.join(ROOT, "results");
const INPUTS = ["metrics.json", "meta.json", "ast.json", "judge.json", "manual_review.json", "pg_schema.json", "token_usage.json", "contract_conformance.json", "acceptance.json", "dv8"];
const runs = fs.existsSync(RESULTS) ? fs.readdirSync(RESULTS).filter((d) => fs.existsSync(path.join(RESULTS, d, "metrics.json"))).sort() : [];

function py(args) {
  const p = spawnSync("python", args, { cwd: ROOT, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" }, timeout: 1800000 });
  assert.equal(p.status, 0, `python ${args.join(" ")}\n${p.stdout}\n${p.stderr}`);
  return p.stdout;
}

function copyRun(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const f of INPUTS) if (fs.existsSync(path.join(src, f))) fs.cpSync(path.join(src, f), path.join(dst, f), { recursive: true });
}

const listFiles = (d, base = d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? listFiles(path.join(d, e.name), base) : [path.relative(base, path.join(d, e.name)).split(path.sep).join("/")]);

/** Every file of `a` and `b` the same text, except the listed ones; CRLF normalized outside CSV files. */
function sameTree(a, b, skip = () => false) {
  const fa = listFiles(a).filter((f) => !skip(f)).sort(), fb = listFiles(b).filter((f) => !skip(f)).sort();
  assert.deepEqual(fa, fb, "the same files");
  for (const f of fa) {
    const norm = (t) => (f.endsWith(".csv") ? t : t.replaceAll("\r\n", "\n"));
    const ta = norm(fs.readFileSync(path.join(a, f), "utf8")), tb = norm(fs.readFileSync(path.join(b, f), "utf8"));
    if (ta === tb) continue;
    const la = ta.split("\n"), lb = tb.split("\n");
    const i = la.findIndex((l, k) => l !== lb[k]);
    assert.fail(`${f}: line ${i + 1} differs\n  js:     ${JSON.stringify(la[i])?.slice(0, 300)}\n  python: ${JSON.stringify(lb[i])?.slice(0, 300)}`);
  }
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "eval-entry-"));
const PY = path.join(tmp, "py"), JS = path.join(tmp, "js");
for (const r of runs) { copyRun(path.join(RESULTS, r), path.join(PY, r)); copyRun(path.join(RESULTS, r), path.join(JS, r)); }

test("evaluate rescore + manual_template: the same files as Python", { skip: !runs.length && "no evaluated runs in results/" }, () => {
  for (const r of runs) {
    py(["python/evaluate.py", "rescore", path.join(PY, r)]);
    py(["python/manual_template.py", path.join(PY, r)]);
    cmdRescore({ res: [path.join(JS, r)] });
    writeTemplates(path.join(JS, r));
    sameTree(path.join(JS, r), path.join(PY, r));
  }
});

test("dv8_metrics: the same matrix and values as Python", { skip: (!runs.length || !fs.existsSync(findDv8())) && "DV8 not installed" }, () => {
  for (const r of runs) {
    py(["python/dv8_metrics.py", path.join(PY, r)]);
    dv8Metrics(path.join(JS, r));
    for (const f of ["matrix.json", "dv8_metrics.json"]) {
      const n = (d) => fs.readFileSync(path.join(d, r, "dv8", f), "utf8").replaceAll("\r\n", "\n");
      assert.equal(n(JS), n(PY), `${r}/dv8/${f}`);
    }
  }
});

test("evaluate aggregate: the same comparison as Python", { skip: !runs.length && "no evaluated runs in results/" }, () => {
  py(["python/evaluate.py", "aggregate", PY]);
  cmdAggregate({ dir: JS });
  sameTree(JS, PY, (f) => f.includes("/dv8/") && !/dv8_metrics\.json$|matrix\.json$/.test(f));  // DV8's own scratch files
});

test("evaluate run (offline): the same evaluation of an app as Python", { timeout: 1800000 }, async () => {
  const app = path.join(ROOT, "tests", "fixtures", "sequelize_app");
  const a = { app, agent: "codex", model: "gpt-x", level: "N1", domain: "ecommerce", offline: true, as_of: "2026-11-16", run_id: "sequelize-app-r1" };
  py(["python/evaluate.py", "run", app, "--out", path.join(tmp, "run-py"), "--agent", a.agent, "--model", a.model, "--level", a.level, "--domain", a.domain, "--offline", "--as-of", a.as_of, "--run-id", a.run_id]);
  await cmdRun({ ...a, out: path.join(tmp, "run-js") });
  const date = (d) => JSON.parse(fs.readFileSync(path.join(tmp, d, "meta.json"), "utf8")).date;
  // the time of the run is the only expected difference: put the Python one in the JavaScript files before comparing
  const dj = date("run-js"), dp = date("run-py");
  for (const f of listFiles(path.join(tmp, "run-js"))) {
    const p = path.join(tmp, "run-js", f);
    fs.writeFileSync(p, fs.readFileSync(p, "utf8").replaceAll(dj, dp), "utf8");
  }
  sameTree(path.join(tmp, "run-js"), path.join(tmp, "run-py"), (f) => /^(jscpd|knip)\/|lint_request\.json|lint_raw\.json|depcruise\.config\.json|\.spectral\.yaml/.test(f));
});

test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
