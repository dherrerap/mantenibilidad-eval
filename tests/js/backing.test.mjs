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
