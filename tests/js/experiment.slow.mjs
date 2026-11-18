// Differential test of run_experiment: what can run on a machine without the agents' CLIs and without Docker. The phase inputs
// (PROMPT.md, PROMPT-R2.md and the copied specs) and the agent command must be the same as Python's, and --existing-app with
// --phase none and --skip-acceptance must give the same results and experiment meta.json.
//   npm run test:js:experiment
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { agentCommand, preparePhase } from "../../js/run_experiment.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "eval-exp-"));
test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));
const py = (code) => spawnSync("python", ["-c", code], { cwd: ROOT, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
const listFiles = (d, base = d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? listFiles(path.join(d, e.name), base) : [path.relative(base, path.join(d, e.name)).split(path.sep).join("/")]);

test("phase inputs and agent command: the same as Python", () => {
  for (const [level, domain] of [["N1", "ecommerce"], ["N3", "cinema"]]) {
    const pj = path.join(tmp, `prep-js-${level}`), pp = path.join(tmp, `prep-py-${level}`);
    preparePhase("initial", level, domain, pj);
    const r = py(`import run_experiment as r; from pathlib import Path; r.prepare_phase("initial", "${level}", "${domain}", Path(r"${pp}"))`);
    assert.equal(r.status, 0, r.stderr);
    for (const d of [pj, pp]) fs.mkdirSync(path.join(d, "backend"), { recursive: true });
    preparePhase("r2", level, domain, pj);
    assert.equal(py(`import run_experiment as r; from pathlib import Path; r.prepare_phase("r2", "${level}", "${domain}", Path(r"${pp}"))`).status, 0);
    assert.deepEqual(listFiles(pj).sort(), listFiles(pp).sort());
    const lf = (t) => t.replaceAll("\r\n", "\n");  // Python's write_text turns \n into \r\n on Windows; the specs are copied as they are
    for (const f of listFiles(pp)) assert.equal(lf(fs.readFileSync(path.join(pj, f), "utf8")), lf(fs.readFileSync(path.join(pp, f), "utf8")), f);
  }
  for (const [agent, agentCmd, model] of [["claude", null, "claude-sonnet-5-5"], ["codex", null, null], ["claude", 'my-agent --run "{prompt}" --x', "m"]]) {
    const js = agentCommand(agent, { agent_cmd: agentCmd, model }, "PROMPT TEXT");
    const r = py(`import json, run_experiment as r; from types import SimpleNamespace as N; print(json.dumps(r.agent_command(${JSON.stringify(agent)}, N(agent_cmd=${agentCmd ? JSON.stringify(agentCmd) : "None"}, model=${model ? JSON.stringify(model) : "None"}), "PROMPT TEXT")))`);
    assert.deepEqual(js, JSON.parse(r.stdout), `${agent} ${agentCmd}`);
  }
});

test("run_experiment --existing-app --phase none --skip-acceptance: the same results as Python", { timeout: 3600000 }, () => {
  const out = {};
  for (const s of ["py", "js"]) {
    const app = path.join(tmp, `app-${s}`, "my_app");
    fs.cpSync(path.join(ROOT, "tests", "fixtures", "sequelize_app"), app, { recursive: true });
    const args = ["--agent", "codex", "--level", "N1", "--existing-app", app, "--skip-acceptance", "--skip-tests", "--offline", "--as-of", "2026-11-16",
      "--model", "gpt-x", "--exp", path.join(tmp, `exp-${s}`), "--results", path.join(tmp, `res-${s}`), "--usage-dir", path.join(tmp, "no-usage")];
    const p = s === "py" ? spawnSync("python", ["run_experiment.py", ...args], { cwd: ROOT, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" }, timeout: 3600000 })
      : spawnSync(process.execPath, [path.join(ROOT, "js", "run_experiment.mjs"), ...args], { cwd: ROOT, encoding: "utf8", env: { ...process.env, NODE_TEST_CONTEXT: "" }, timeout: 3600000 });
    assert.equal(p.status, 0, (p.stdout || "") + (p.stderr || ""));
    out[s] = { res: path.join(tmp, `res-${s}`), exp: path.join(tmp, `exp-${s}`), app };
  }
  const run = "codex-n1-ecommerce-r1";
  const meta = (s) => { const m = JSON.parse(fs.readFileSync(path.join(out[s].exp, run, "meta.json"), "utf8")); delete m.date; return m; };
  assert.deepEqual(meta("js"), meta("py"));
  const date = (s) => JSON.parse(fs.readFileSync(path.join(out[s].res, run, "meta.json"), "utf8")).date;
  const align = (t) => t.replaceAll(date("js"), date("py")).replaceAll(out.js.app, out.py.app).replaceAll(out.js.app.replaceAll("\\", "\\\\"), out.py.app.replaceAll("\\", "\\\\"));
  const skip = (f) => /(^|\/)(environment\.json|jscpd\/|knip\/|lint_request\.json|lint_raw\.json|depcruise\.config\.json|\.spectral\.yaml)/.test(f);
  const files = listFiles(out.py.res).filter((f) => !skip(f)).sort();
  assert.deepEqual(listFiles(out.js.res).filter((f) => !skip(f)).sort(), files);
  for (const f of files) {
    const n = (t) => (f.endsWith(".csv") ? t : t.replaceAll("\r\n", "\n"));
    assert.equal(align(n(fs.readFileSync(path.join(out.js.res, f), "utf8"))), n(fs.readFileSync(path.join(out.py.res, f), "utf8")), f);
  }
});
