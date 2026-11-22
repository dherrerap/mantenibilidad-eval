// point_weights.test.mjs — Weights of the decision points inside each subcharacteristic (`point_weights` in rubric.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import { RUBRIC, pointWeight } from "../../js/evaluator/common.mjs";
import { profile, riskSummary } from "../../js/evaluator/scoring.mjs";
import { overall, scenarios } from "../../js/evaluator/sensitivity.mjs";

const LEVEL = { 0: "Fails", 0.5: "Partial", 1: "Meets" };

/** Every point of the rubric with the given score (default 0), as scoring.evaluatePoints() returns them. */
function points(scores = {}) {
  return Object.entries(RUBRIC.points).map(([id, d]) => {
    const v = scores[id] ?? 0;
    return { id, name: d.name, subcharacteristics: d.subcharacteristics, complete: true, level: LEVEL[v], level_min: LEVEL[v], level_max: LEVEL[v],
      pending_criteria: [], score_min: v, score_max: v };
  });
}

function withWeights(weights, fn) {
  const had = Object.prototype.hasOwnProperty.call(RUBRIC, "point_weights"), before = RUBRIC.point_weights;
  RUBRIC.point_weights = weights;
  try { fn(); } finally { if (had) RUBRIC.point_weights = before; else delete RUBRIC.point_weights; }
}

const sub = (prof, s) => Number(prof.subcharacteristics[s].min);

test("without point weights every subcharacteristic is the plain mean of its points", () => {
  withWeights({}, () => {
    const prof = profile(points({ tests: 1 }));  // Testability = mean(tests 1, contracts 0)
    assert.equal(sub(prof, "Testability"), 50);
    assert.equal(Number(prof.maintainability_min), 15);
  });
});

test("a point weight changes its subcharacteristic as a weighted mean", () => {
  withWeights({ tests: 3 }, () => {
    const prof = profile(points({ tests: 1 }));  // (3·1 + 1·0) / 4
    assert.equal(sub(prof, "Testability"), 75);
    assert.equal(Number(prof.maintainability_min), 22.5);
  });
});

test("the impact of the risk list follows the point weights", () => {
  withWeights({}, () => {
    const r = Object.fromEntries(riskSummary(points()).map((x) => [x.id, Number(x.impact)]));
    assert.equal(r.tests, 15);  // 30 / 2
    assert.equal(r.layers, 3.4);  // 24 / 7
  });
  withWeights({ tests: 3 }, () => {
    const r = Object.fromEntries(riskSummary(points()).map((x) => [x.id, Number(x.impact)]));
    assert.equal(r.tests, 22.5);  // 30 · 3 / 4
    assert.equal(r.contracts, 10.9);  // 24 / 7 + 30 · 1 / 4
  });
});

test("the panel scenario of the sensitivity analysis reproduces the weighted profile", () => {
  withWeights({ tests: 3, layers: 2 }, () => {
    const pts = points({ tests: 1, layers: 0.5, observability: 1 });
    const prof = profile(pts);
    const panel = scenarios().find(([name]) => name === "panel")[2];
    assert.deepEqual(overall(pts, panel).map(Number), [Number(prof.maintainability_min), Number(prof.maintainability_max)]);
  });
});

test("a point weight that is not a positive number is rejected", () => {
  for (const bad of [0, -1]) withWeights({ tests: bad }, () => assert.throws(() => pointWeight("tests"), /positive number/));
  withWeights({ _comment: "only a comment" }, () => assert.equal(pointWeight("tests"), 1));
});
