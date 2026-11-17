const test = require("node:test");
const assert = require("node:assert");
const { unitPrice } = require("../src/price");

test("discount from 10 units", () => {
  assert.strictEqual(unitPrice(100, 10), 90);
  assert.strictEqual(unitPrice(100, 9), 100);
});
