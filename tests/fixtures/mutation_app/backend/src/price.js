// Fixture for mutation testing (StrykerJS): volume discount and shipping, tested on purpose only in part.

/** Unit price with a 10% discount from 10 units on. */
function unitPrice(base, qty) {
  if (qty >= 10) return base * 0.9;
  return base;
}

/** Free shipping from 100 on; otherwise 5. Not tested at all: its mutants survive. */
function shipping(total) {
  return total >= 100 ? 0 : 5;
}

module.exports = { unitPrice, shipping };
