// backing.test.mjs — Every link of Table 24 between a decision point and a subcharacteristic declares its basis in rubric.json.
import { test } from "node:test";
import assert from "node:assert/strict";
import { RUBRIC } from "../../js/evaluator/common.mjs";

test("every point-subcharacteristic link declares its basis", () => {
  const links = RUBRIC.backing["points.subcharacteristics"].links;
  const expected = Object.entries(RUBRIC.points).flatMap(([pid, d]) => d.subcharacteristics.map((s) => `${pid}.${s}`)).sort();
  assert.deepEqual(Object.keys(links).sort(), expected);
  for (const [key, b] of Object.entries(links)) {
    assert.ok(["iso25023", "own"].includes(b.basis), key);
    assert.ok(b.rationale, key);
    if (b.basis === "iso25023") assert.ok(b.measure && b.locator, `${key} claims ISO/IEC 25023 without a measure and locator`);
  }
  assert.deepEqual(Object.keys(links).filter((k) => links[k].basis === "iso25023").sort(),
    ["coupling.Modularity", "cyclomatic.Modularity", "observability.Analyzability"]);
});

test("the vetoes live in the rubric and decide the level", async () => {
  const { mustCriteria } = await import("../../js/evaluator/scoring.mjs");
  const { levelFrom } = await import("../../js/evaluator/criteria.mjs");
  assert.deepEqual(mustCriteria("contracts"), ["C1"]);
  assert.deepEqual(mustCriteria("tests"), ["C2"]);
  assert.deepEqual(mustCriteria("_comment"), []);
  const testsFail = { C1: { ok: true }, C2: { ok: false }, C3: { ok: true }, C4: { ok: true } };  // tests exist but fail; the rest is met
  assert.equal(levelFrom(testsFail, mustCriteria("tests"))[0], "Fails");
  assert.equal(levelFrom(testsFail)[0], "Partial");
});

test("a must_criteria map that would drop a veto is rejected", async () => {
  const { mustCriteria } = await import("../../js/evaluator/scoring.mjs");
  const before = RUBRIC.must_criteria;
  try {
    for (const bad of [{ test: ["C2"] }, { tests: "C2" }, { tests: ["2"] }, { tests: [2] }]) {  // typo in the point, not a list, not criterion ids
      RUBRIC.must_criteria = bad;
      assert.throws(() => mustCriteria("tests"), /must_criteria/);
    }
    delete RUBRIC.must_criteria;
    assert.throws(() => mustCriteria("tests"), /missing/);
  } finally { RUBRIC.must_criteria = before; }
});

test("a not-applicable Hierarchies point counts zero inheritance weaknesses in ASCMM", async () => {
  const { ascmmProfile } = await import("../../js/evaluator/ascmm.mjs");
  const m = { ast: { files: [{ path: "a.js", loc: 1500, test: false }], functions: [] } };
  const pts = [{ id: "hierarchies", evaluable: true, applicable: false, metrics: { classes: 0, applicable: false }, criteria: {} }];
  const a = ascmmProfile(m, pts);
  const count = (cwe) => a.weaknesses.find((w) => w.cwe === cwe).count;
  assert.deepEqual(["CWE-1062", "CWE-1074", "CWE-1086"].map(count), [0, 0, 0]);
  assert.ok(!a.scored.not_measured.some((c) => ["CWE-1062", "CWE-1074", "CWE-1086"].includes(c)));
});
