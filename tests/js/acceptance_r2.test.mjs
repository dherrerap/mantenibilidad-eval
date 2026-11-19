// The r2 acceptance suite: it is chosen with suite "r2", only for ecommerce, and an API that does not answer gives failed cases
// (never an exception), so that the gate always writes its result. Its behavior against real apps is checked by
// `node js/cli.mjs evaluate --postgres` on the generated apps (see docs/js-migration.md).
import assert from "node:assert/strict";
import { test } from "node:test";
import { run } from "../../js/acceptance_check.mjs";
import { R2_SUITES, r2Credentials } from "../../js/acceptance_r2.mjs";

test("r2 suite: only ecommerce has one; asking for another domain is an error", () => {
  assert.deepEqual(Object.keys(R2_SUITES), ["ecommerce"]);
  assert.throws(() => run("http://127.0.0.1:9", "cinema", "r2"), /no r2 acceptance suite for domain 'cinema'/);
});

test("r2 suite against an API that does not answer: every case fails, none throws", { timeout: 120000 }, async () => {
  const res = await run("http://127.0.0.1:9", "ecommerce", "r2");
  assert.equal(res.suite, "r2");
  assert.equal(res.domain, "ecommerce");
  assert.equal(res.passed, 0);
  assert.ok(res.total >= 40, `${res.total} cases`);
  assert.ok(res.cases.every((c) => c.ok === false && !String(c.detail).startsWith("exception")), res.cases.find((c) => String(c.detail).startsWith("exception"))?.case);
  for (const req of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]) assert.ok(res.cases.some((c) => c.case.startsWith(req + " ")), `no case for ${req}`);
});

test("r2 credentials: distinct admin and auditor accounts with strong passwords", () => {
  const c = r2Credentials();
  assert.notEqual(c.ADMIN_EMAIL, c.AUDITOR_EMAIL);
  for (const p of [c.ADMIN_PASSWORD, c.AUDITOR_PASSWORD]) assert.match(p, /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*\W).{12,}$/);
});
