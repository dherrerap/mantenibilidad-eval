// Differential test of the JavaScript port of the decision points and the scoring: every call recorded from the Python version
// (tests/golden/record_scoring.py) must give the same JSON, key order included. The files a call read are served from the record.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDict, loadJson, num } from "../../js/lib/py.mjs";
import { appFs } from "../../js/evaluator/common.mjs";
import { levelFrom } from "../../js/evaluator/criteria.mjs";
import { evaluatePoints, evaluateProfile, profile, riskSummary } from "../../js/evaluator/scoring.mjs";
import { supplementaryIndicators } from "../../js/evaluator/supplementary.mjs";
import * as simple from "../../js/evaluator/points/simple.mjs";
import * as structure from "../../js/evaluator/points/structure.mjs";
import * as deps from "../../js/evaluator/points/dependencies.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const FN = {
  "evaluator.scoring.evaluate_points": evaluatePoints, "evaluator.scoring.evaluate_profile": evaluateProfile, "evaluator.scoring.profile": profile,
  "evaluator.scoring.risk_summary": riskSummary, "evaluator.criteria.level_from": levelFrom, "evaluator.supplementary.supplementary_indicators": supplementaryIndicators,
  "points.eval_layers": structure.evalLayers, "points.eval_cohesion": structure.evalCohesion, "points.eval_coupling": structure.evalCoupling,
  "points.eval_cyclomatic": structure.evalCyclomatic, "points.eval_configuration": simple.evalConfiguration, "points.eval_observability": simple.evalObservability,
  "points.eval_tests": simple.evalTests, "points.eval_hierarchies": simple.evalHierarchies, "points.eval_contracts": simple.evalContracts,
  "points.eval_technologies": deps.evalTechnologies, "points.eval_data_model": deps.evalDataModel,
};

function sameJson(a, b, where = "$") {
  if (Array.isArray(a) || Array.isArray(b)) {
    assert.ok(Array.isArray(a) && Array.isArray(b), `${where}: array vs non-array (${JSON.stringify(a)?.slice(0, 80)} / ${JSON.stringify(b)?.slice(0, 80)})`);
    assert.equal(a.length, b.length, `${where}: length ${a.length} vs ${b.length}`);
    a.forEach((x, i) => sameJson(x, b[i], `${where}[${i}]`));
  } else if (isDict(a) && isDict(b)) {
    assert.deepEqual(Object.keys(a), Object.keys(b), `${where}: keys`);
    for (const k of Object.keys(a)) sameJson(a[k], b[k], `${where}.${k}`);
  } else assert.equal(num(a), num(b), `${where}`);
}

const realFs = { ...appFs };
function serveRecorded(c) {
  const files = c.files || {};
  appFs.readText = (app, rel) => {
    const k = String(rel).replaceAll("\\", "/");
    if (!(k in files) || files[k] === null) throw new Error(`not recorded: ${k}`);
    return files[k];
  };
  appFs.designText = () => c.design_text ?? "";
}

function run(file) {
  const text = fs.readFileSync(file, "utf8");
  const g = loadJson(text);
  for (const [i, c0] of g.calls.entries()) {
    test(`${path.basename(file)} #${i} ${c0.fn}`, () => {
      const c = loadJson(text).calls[i];  // a fresh copy: structuredClone would turn every PyFloat into a plain Number
      const fn = FN[c.fn];
      assert.ok(fn, `no port of ${c.fn}`);
      serveRecorded(c);
      try {
        const args = c.args;
        if (c.fn === "evaluator.criteria.level_from" && c.kwargs && "must" in c.kwargs) args.push(c.kwargs.must);
        const got = JSON.parse(JSON.stringify(fn(...args) ?? null));
        sameJson(got, JSON.parse(JSON.stringify(c.result)));
      } finally { Object.assign(appFs, realFs); }
    });
  }
}

run(path.join(ROOT, "tests", "golden", "scoring.json"));
const local = path.join(ROOT, "results", "_golden", "scoring-apps.json");
if (fs.existsSync(local)) run(local);
