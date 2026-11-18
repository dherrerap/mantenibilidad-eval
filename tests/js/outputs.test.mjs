// Differential test of the JavaScript port of the outputs: the files write_outputs writes must be identical to the Python ones,
// text for text (Python on Windows writes CRLF through Path.write_text; the recorder stores them with LF, and so does the port).
// For the evaluated runs it also replays the whole chain metrics.json → evaluateProfile → writeOutputs.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDict, loadJson, num } from "../../js/lib/py.mjs";
import { ascmmColumns, ascmmComparisonMd } from "../../js/evaluator/ascmm.mjs";
import { appFs } from "../../js/evaluator/common.mjs";
import { writeOutputs } from "../../js/evaluator/outputs.mjs";
import { evaluateProfile } from "../../js/evaluator/scoring.mjs";
import { sensitivity, sensitivityMd } from "../../js/evaluator/sensitivity.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const FN = { "evaluator.sensitivity.sensitivity": sensitivity, "evaluator.sensitivity.sensitivity_md": sensitivityMd,
  "evaluator.ascmm.ascmm_comparison_md": ascmmComparisonMd, "evaluator.ascmm.ascmm_columns": ascmmColumns };

function sameJson(a, b, where = "$") {
  if (Array.isArray(a) || Array.isArray(b)) {
    assert.ok(Array.isArray(a) && Array.isArray(b), `${where}: array vs non-array`);
    assert.equal(a.length, b.length, `${where}: length`);
    a.forEach((x, i) => sameJson(x, b[i], `${where}[${i}]`));
  } else if (isDict(a) && isDict(b)) {
    assert.deepEqual(Object.keys(a), Object.keys(b), `${where}: keys`);
    for (const k of Object.keys(a)) sameJson(a[k], b[k], `${where}.${k}`);
  } else assert.equal(num(a), num(b), where);
}

/** First differing line of two texts, for a readable failure. */
function sameText(got, want, name) {
  if (got === want) return;
  const g = got.split("\n"), w = want.split("\n");
  const i = g.findIndex((l, k) => l !== w[k]);
  assert.fail(`${name}: line ${i + 1} differs\n  js:     ${JSON.stringify(g[i])?.slice(0, 400)}\n  python: ${JSON.stringify(w[i])?.slice(0, 400)}`);
}

function checkWrite(c, run) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "eval-js-out-"));
  try {
    if (c.token_usage !== null && c.token_usage !== undefined) fs.writeFileSync(path.join(dir, "token_usage.json"), c.token_usage, "utf8");
    run(dir);
    for (const [name, want] of Object.entries(c.files)) {
      const got = fs.readFileSync(path.join(dir, name), "utf8");
      sameText(name.endsWith(".csv") ? got : got.replaceAll("\r\n", "\n"), want, name);
    }
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
}

function run(file, apps) {
  const text = fs.readFileSync(file, "utf8");
  const g = loadJson(text);
  for (const [i, c0] of g.calls.entries()) {
    test(`${path.basename(file)} #${i} ${c0.fn}`, () => {
      const c = loadJson(text).calls[i];
      if (c.fn === "evaluator.outputs.write_outputs") {
        const [, meta, points, prof, m] = c.args;
        checkWrite(c, (dir) => writeOutputs(dir, meta, points, prof, m));
        return;
      }
      const got = JSON.parse(JSON.stringify(FN[c.fn](...c.args) ?? null));
      sameJson(got, JSON.parse(JSON.stringify(c.result)));
    });
    if (apps && c0.pipeline_inputs) {
      test(`${path.basename(file)} #${i} metrics.json → evaluateProfile → writeOutputs`, () => {
        const c = loadJson(text).calls[i];
        const [m, manual, opts] = c.pipeline_inputs;
        const real = { ...appFs };
        try {
          const [pts, prof] = evaluateProfile(m, manual, opts);
          checkWrite(c, (dir) => writeOutputs(dir, c.args[1], pts, prof, m));
        } finally { Object.assign(appFs, real); }
      });
    }
  }
}

run(path.join(ROOT, "tests", "golden", "outputs.json"), false);
const local = path.join(ROOT, "results", "_golden", "outputs-apps.json");
if (fs.existsSync(local)) run(local, true);
