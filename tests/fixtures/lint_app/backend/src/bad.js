// Fixture for lint_metrics.js: every block triggers one rule of rubric.json `lint.ascmm` or one measurement rule.
const LONG = "a long literal value";

function incorrectOperator(a, b) {
  let x = 0;
  if ((x = a)) x += 1; // allowed: parenthesized
  if (x = b) x += 1; // CWE-480 no-cond-assign
  x =+ b; // CWE-480 sonarjs/non-existent-operator
  if (a === NaN) x = 1; // CWE-480 use-isnan
  return x;
}

function alwaysTrue(a) {
  if (a) {
    if (a) return 1; // CWE-571 sonarjs/no-gratuitous-expressions
  }
  if (a ?? true === false) return 2; // CWE-570/571 no-constant-binary-expression
  return 0;
}

function precedence(a, b, c, list) {
  if (a && b || c) return 1; // CWE-783 no-mixed-operators
  if (!a in list) return 2; // CWE-783 no-unsafe-negation
  return 0;
}

function loopCounter(items) {
  let n = 0;
  for (let i = 0; i < items.length; i++) {
    if (items[i]) i = items.length; // CWE-1095 sonarjs/updated-loop-counter (i++ or i += 2 are not reported by the rule)
    n += 1;
  }
  return n;
}

function commentedOut(a) {
  // const result = compute(a);
  // if (result > 10) { return result; }
  return a;
}

function manyParams(a, b, c, d, e, f, g, h) { // CWE-1064: 8 parameters
  return [a, b, c, d, e, f, g, h];
}

function duplicated() {
  return ["a long literal value", "a long literal value", LONG, "application/json", "application/json", "application/json"];
}

module.exports = { incorrectOperator, alwaysTrue, precedence, loopCounter, commentedOut, manyParams, duplicated };
