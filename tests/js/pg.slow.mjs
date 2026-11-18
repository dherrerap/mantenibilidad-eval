// Differential test of the acceptance gate and the real-database analysis: pg_analysis.py and js/pg_analysis.mjs on every generated
// app (a copy without the r2 markers, so that the gate runs), each on a fresh database of a temporary PostgreSQL server. The
// acceptance result, the conformance to the contract through Prism, the seed and the catalog of the database must be the same.
// Also the cinema suite, which no generated app exercises yet, against a stand-in server (tests/js/mock_cinema.mjs).
//   npm run test:js:pg
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { findBin } from "../../js/pg_temp.mjs";
import { freePort } from "../../js/pg_runtime.mjs";
import { compare, normalized, OUT_FILES } from "./pg_compare.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const RESULTS = path.join(ROOT, "results");
const runs = fs.existsSync(RESULTS) ? fs.readdirSync(RESULTS).filter((d) => fs.existsSync(path.join(RESULTS, d, "metrics.json"))).sort() : [];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "eval-pg-test-"));
test.after(() => fs.rmSync(tmp, { recursive: true, force: true }));

for (const r of runs) {
  const app = JSON.parse(fs.readFileSync(path.join(RESULTS, r, "metrics.json"), "utf8")).app;
  test(`pg_analysis ${r}: the same gate, conformance, seed and catalog as Python`, { skip: (!findBin() || !fs.existsSync(app)) && "no PostgreSQL or no app", timeout: 3600000 }, () => {
    const { diffs, out } = compare(path.join(RESULTS, r), app, path.join(tmp, r));
    assert.equal(out.py.rc, 0, out.py.log); assert.equal(out.js.rc, 0, out.js.log);
    const present = OUT_FILES.filter((f) => normalized(path.join(tmp, r, "py"), f) !== null);
    assert.ok(present.includes("acceptance.json") && present.includes("pg_schema.json"), `the analysis wrote ${present.join(", ")}`);
    assert.deepEqual(diffs, [], `files that differ: ${diffs.join(", ")}`);
  });
}

async function withMock(fn) {
  const port = freePort();
  const p = spawn(process.execPath, [path.join(ROOT, "tests", "js", "mock_cinema.mjs"), String(port)], { stdio: "ignore" });
  await new Promise((r) => setTimeout(r, 800));
  try { return await fn(`http://127.0.0.1:${port}`); } finally { p.kill(); }
}

test("acceptance_check cinema: the same result as Python against a stand-in cinema API", { timeout: 600000 }, async () => {
  const out = {};
  for (const [side, cmd] of [["py", ["python", path.join(ROOT, "python", "acceptance_check.py")]], ["js", [process.execPath, path.join(ROOT, "js", "acceptance_check.mjs")]]]) {
    const f = path.join(tmp, `cinema-${side}.json`);
    await withMock(async (base) => {
      const p = spawnSync(cmd[0], [...cmd.slice(1), "--base", base, "--domain", "cinema", "--out", f], { encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
      assert.equal(p.status, 0, (p.stdout || "") + (p.stderr || ""));
    });
    const d = JSON.parse(fs.readFileSync(f, "utf8"));
    d.base = "<base>";
    out[side] = JSON.stringify(d, null, 1).replace(/\d{4}-\d{2}-\d{2}T[\d:.]+Z?/g, "<time>");
  }
  assert.equal(out.js, out.py);
  assert.ok(JSON.parse(out.py).cases.length >= 20, "the whole cinema suite ran");
});
