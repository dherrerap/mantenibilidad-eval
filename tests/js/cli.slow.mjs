// End-to-end differential test of cli, judge and token_usage: the Python command on one copy, the JavaScript one on another, and the
// files compared as text. Only what depends on the moment or the runtime is aligned first: report.md's "Generated:" line and
// Environment section, and the dates of the runs and of the judge.
//   npm run test:js:cli
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const RESULTS = path.join(ROOT, "results");
const runs = fs.existsSync(RESULTS) ? fs.readdirSync(RESULTS).filter((d) => fs.existsSync(path.join(RESULTS, d, "metrics.json"))).sort() : [];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "eval-cli-"));
test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function run(cmd, args, env = {}) {
  const p = spawnSync(cmd, args, { cwd: ROOT, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8", ...env, NODE_TEST_CONTEXT: "" }, timeout: 3600000, maxBuffer: 256 * 1024 * 1024 });
  return [p.status, (p.stdout || "") + (p.stderr || "")];
}
const py = (args, env) => run("python", args, env);
const js = (script, args, env) => run(process.execPath, [path.join(ROOT, "js", script), ...args], env);

const listFiles = (d, base = d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? listFiles(path.join(d, e.name), base) : [path.relative(base, path.join(d, e.name)).split(path.sep).join("/")]);

/** report.md without what depends on the moment and the runtime; every other file as is (CRLF normalized outside CSV). */
function normalize(f, t) {
  if (!f.endsWith(".csv")) t = t.replaceAll("\r\n", "\n");
  if (f.endsWith("report.md")) t = t.replace(/^Generated: .*$/m, "Generated: <now>").replace(/\n## Environment\n[\s\S]*$/, "\n");
  return t;
}

function sameTree(a, b, skip = () => false, align = (t) => t) {
  const fa = listFiles(a).filter((f) => !skip(f)).sort(), fb = listFiles(b).filter((f) => !skip(f)).sort();
  assert.deepEqual(fa, fb, "the same files");
  for (const f of fa) {
    const ta = align(normalize(f, fs.readFileSync(path.join(a, f), "utf8"))), tb = normalize(f, fs.readFileSync(path.join(b, f), "utf8"));
    if (ta === tb) continue;
    const la = ta.split("\n"), lb = tb.split("\n"), i = la.findIndex((l, k) => l !== lb[k]);
    assert.fail(`${f}: line ${i + 1} differs\n  js:     ${JSON.stringify(la[i])?.slice(0, 300)}\n  python: ${JSON.stringify(lb[i])?.slice(0, 300)}`);
  }
}

// runtime-specific records of the run, not results: environment.json describes the interpreter; the tools' scratch files
const SCRATCH = (f) => /(^|\/)(environment\.json|jscpd\/|knip\/|lint_request\.json|lint_raw\.json|depcruise\.config\.json|\.spectral\.yaml)/.test(f) ||
  (/\/dv8\//.test(f) && !/dv8_metrics\.json$|matrix\.json$/.test(f));

test("cli report: the same report as Python", { skip: !runs.length && "no evaluated runs" }, () => {
  for (const s of ["py", "js"]) fs.cpSync(RESULTS, path.join(tmp, `report-${s}`), { recursive: true, filter: (p) => !p.includes(`${path.sep}_golden`) });
  assert.equal(py(["python/cli.py", "report", "--results", path.join(tmp, "report-py")])[0], 0);
  assert.equal(js("cli.mjs", ["report", "--results", path.join(tmp, "report-js")])[0], 0);
  const n = (s) => normalize("report.md", fs.readFileSync(path.join(tmp, `report-${s}`, "report.md"), "utf8"));
  assert.equal(n("js"), n("py"));
});

test("cli evaluate --rescore: the same results as Python (rescore, aggregate, report)", { skip: !runs.length && "no evaluated runs" }, () => {
  for (const s of ["py", "js"]) fs.cpSync(RESULTS, path.join(tmp, `rescore-${s}`), { recursive: true, filter: (p) => !p.includes(`${path.sep}_golden`) });
  const args = (s) => ["evaluate", "--rescore", "--results", path.join(tmp, `rescore-${s}`), "--model", "gpt-6.1-sol", "--as-of", "2026-11-16"];
  const [rp, op] = py(["python/cli.py", ...args("py")]);
  const [rj, oj] = js("cli.mjs", args("js"));
  assert.equal(rp, 0, op); assert.equal(rj, 0, oj);
  sameTree(path.join(tmp, "rescore-js"), path.join(tmp, "rescore-py"), SCRATCH);
});

test("cli evaluate: a fixture app evaluated from scratch (offline, no tests, no DV8) gives the same results", { timeout: 3600000 }, () => {
  for (const s of ["py", "js"]) fs.cpSync(path.join(ROOT, "tests", "fixtures", "sequelize_app"), path.join(tmp, `apps-${s}`, "codex-n1"), { recursive: true });
  const args = (s) => ["evaluate", "--apps-dir", path.join(tmp, `apps-${s}`), "--results", path.join(tmp, `full-${s}`), "--model", "gpt-x", "--as-of", "2026-11-16",
    "--offline", "--skip-tests", "--skip-dv8", "--usage-dir", path.join(tmp, "no-usage")];
  const [rp, op] = py(["python/cli.py", ...args("py")]);
  const [rj, oj] = js("cli.mjs", args("js"));
  assert.equal(rp, 0, op); assert.equal(rj, 0, oj);
  const date = (s) => JSON.parse(fs.readFileSync(path.join(tmp, `full-${s}`, "codex-n1-ecommerce-r1", "meta.json"), "utf8")).date;
  const [dj, dp] = [date("js"), date("py")];
  const fix = (t) => t.replaceAll(dj, dp).replaceAll(path.join(tmp, "apps-js"), path.join(tmp, "apps-py")).replaceAll(path.join(tmp, "apps-js").replaceAll("\\", "\\\\"), path.join(tmp, "apps-py").replaceAll("\\", "\\\\"));
  sameTree(path.join(tmp, "full-js"), path.join(tmp, "full-py"), SCRATCH, fix);
});

test("judge: the same prompts, decisions and audit sample as Python (with a deterministic stand-in model)", { skip: !runs.length && "no evaluated runs" }, () => {
  const fake = `"${process.execPath}" "${path.join(ROOT, "tests", "js", "fake_judge.mjs")}"`;
  for (const r of runs) {
    for (const s of ["py", "js"]) {
      const d = path.join(tmp, `judge-${s}`, r);
      fs.mkdirSync(d, { recursive: true });
      for (const f of ["metrics.json", "meta.json", "scorecard.json", "detected_layers.json", "judge.json", "manual_review.json"])
        if (fs.existsSync(path.join(RESULTS, r, f))) fs.copyFileSync(path.join(RESULTS, r, f), path.join(d, f));
    }
    const a = (s) => [path.join(tmp, `judge-${s}`, r), "--model", "claude-opus-5-5", "--cmd", fake];
    const [rp, op] = py(["python/judge.py", ...a("py")], { FAKE_JUDGE_STATE: path.join(tmp, "state-py") });
    const [rj, oj] = js("judge.mjs", a("js"), { FAKE_JUDGE_STATE: path.join(tmp, "state-js") });
    assert.equal(rp, 0, op); assert.equal(rj, 0, oj);
    const load = (s) => { const j = JSON.parse(fs.readFileSync(path.join(tmp, `judge-${s}`, r, "judge.json"), "utf8")); delete j.meta.date; return j; };
    assert.deepEqual(load("js"), load("py"), r);
    const crlf = (t) => t.replaceAll("\r\n", "\n");  // Python on Windows prints CRLF
    assert.equal(oj.replaceAll(path.join(tmp, "judge-js"), "<res>").trim(), crlf(op).replaceAll(path.join(tmp, "judge-py"), "<res>").trim(), `${r}: console output`);
  }
});

test("token_usage: scan, show and record give what Python gives", () => {
  const [rs1, s1] = py(["python/token_usage.py", "scan"]), [rs2, s2] = js("token_usage.mjs", ["scan"]);
  assert.equal(rs2, rs1); assert.equal(s2, s1.replaceAll("\r\n", "\n"));
  const [, w1] = py(["python/token_usage.py", "show"]), [, w2] = js("token_usage.mjs", ["show"]);
  assert.equal(w2, w1.replaceAll("\r\n", "\n"));
  const tr = path.join(ROOT, "token-usage", "transcripts");
  const files = fs.existsSync(tr) ? fs.readdirSync(tr).filter((f) => f.endsWith(".jsonl")).sort().map((f) => path.join(tr, f)) : [];
  if (!files.length) return;
  for (const s of ["py", "js"]) {
    const dir = path.join(tmp, `usage-${s}`), cmd = ["record", "apps/codex-ecommerce-n1", "--phase", "r2", "--from", ...files, "--usage-dir", dir];
    const [rc, out] = s === "py" ? py(["python/token_usage.py", ...cmd]) : js("token_usage.mjs", cmd);
    assert.equal(rc, 0, out);
    run(s === "py" ? "python" : process.execPath, s === "py" ? ["python/token_usage.py", "record", "apps/codex-ecommerce-n1", "--phase", "initial", "--input", "1000", "--output", "250", "--cost", "1.5", "--note", "manual", "--usage-dir", dir]
      : [path.join(ROOT, "js", "token_usage.mjs"), "record", "apps/codex-ecommerce-n1", "--phase", "initial", "--input", "1000", "--output", "250", "--cost", "1.5", "--note", "manual", "--usage-dir", dir]);
  }
  const load = (s) => {
    const j = JSON.parse(fs.readFileSync(path.join(tmp, `usage-${s}`, "codex-ecommerce-n1.json"), "utf8"));
    for (const p of Object.values(j.phases)) delete p.recorded;
    return fs.readFileSync(path.join(tmp, `usage-${s}`, "codex-ecommerce-n1.json"), "utf8").replace(/"recorded": "[^"]*"/g, "").replaceAll("\r\n", "\n");
  };
  assert.equal(load("js"), load("py"));
});
