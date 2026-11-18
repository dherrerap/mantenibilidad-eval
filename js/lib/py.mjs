// py.mjs — The few Python semantics the port must reproduce exactly, so that the JavaScript evaluator returns the same JSON as the
// Python one: truthiness, str()/repr(), round() (half to even on the exact binary value), ordering of mixed values, re.match
// (anchored at the start), re.findall, and a cache of compiled regular expressions.

/** A plain object (Python dict), not an array or null. */
export const isDict = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

/** Python truthiness: None, False, 0, "", [] and {} are false. */
export function truthy(v) {
  if (v === null || v === undefined || v === false || v === 0 || v === "" || Number.isNaN(v)) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (isDict(v)) return Object.keys(v).length > 0;
  return true;
}

/** Python `a or b` (returns the first truthy value, else the last). */
export const or = (...vals) => {
  for (const v of vals.slice(0, -1)) if (truthy(v)) return v;
  return vals[vals.length - 1];
};

/** dict.get(key, default): the default only when the key is missing. */
export const get = (o, k, d = null) => (isDict(o) && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : d);

function reprStr(s) {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = "";
  for (const ch of s) {
    if (ch === "\\") out += "\\\\";
    else if (ch === q) out += "\\" + q;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else out += ch;
  }
  return q + out + q;
}

function reprNum(n) {
  if (Number.isInteger(n) && Math.abs(n) < 1e16) return String(n);
  if (n === Infinity) return "inf";
  if (n === -Infinity) return "-inf";
  if (Number.isNaN(n)) return "nan";
  // Python's float repr: the shortest round-trip digits (what toExponential() gives), fixed notation for exponents -4..15,
  // scientific otherwise with at least two exponent digits (1e-05, 1e+16)
  const [mant, e] = Math.abs(n).toExponential().split("e");
  const exp = Number(e), digits = mant.replace(".", "");
  let s;
  if (exp >= -4 && exp < 16) {
    if (exp >= 0) s = digits.slice(0, exp + 1).padEnd(exp + 1, "0") + "." + (digits.slice(exp + 1) || "0");
    else s = "0." + "0".repeat(-exp - 1) + digits;
  } else s = digits[0] + (digits.length > 1 ? "." + digits.slice(1) : "") + "e" + (exp < 0 ? "-" : "+") + String(Math.abs(exp)).padStart(2, "0");
  return (n < 0 ? "-" : "") + s;
}

/** Python repr(). */
export function repr(v) {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number") return reprNum(v);
  if (typeof v === "string") return reprStr(v);
  if (Array.isArray(v)) return "[" + v.map(repr).join(", ") + "]";
  return "{" + Object.entries(v).map(([k, x]) => `${reprStr(k)}: ${repr(x)}`).join(", ") + "}";
}

/** Python str(): repr() except that a string is itself. */
export const str = (v) => (typeof v === "string" ? v : repr(v));

/** Exact decimal digits of a finite double: [BigInt digits D, scale k] with |x| = D / 10^k. */
function exactDecimal(x) {
  const dv = new DataView(new ArrayBuffer(8));
  dv.setFloat64(0, Math.abs(x));
  const hi = dv.getUint32(0), lo = dv.getUint32(4);
  const expo = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let e;
  if (expo === 0) e = -1074;
  else { mant |= 1n << 52n; e = expo - 1075; }
  if (e >= 0) return [mant << BigInt(e), 0];
  return [mant * 5n ** BigInt(-e), -e];
}

/** Python round(x, n): half to even on the exact binary value of x (round(0.125, 2) == 0.12, round(2.675, 2) == 2.67). */
export function pyRound(x, n = 0) {
  if (!Number.isFinite(x) || x === 0) return x;
  const [D, k] = exactDecimal(x);
  let q = D;
  if (k > n) {
    const p = 10n ** BigInt(k - n), r = D % p, half = p / 2n;
    q = D / p;
    if (r > half || (r === half && q % 2n === 1n)) q += 1n;
  } else q = D * 10n ** BigInt(n - k);
  const v = Number(`${q}e-${n}`);
  return x < 0 ? -v : v;
}

/** Python ordering of the values the evaluator sorts: numbers, strings (by code point), None first, lists element by element. */
export function cmp(a, b) {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;
  if (Array.isArray(a) && Array.isArray(b)) {
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const c = cmp(a[i], b[i]);
      if (c) return c;
    }
    return a.length - b.length;
  }
  if (typeof a === "number" && typeof b === "number") return a < b ? -1 : a > b ? 1 : 0;
  if (typeof a === "boolean" || typeof b === "boolean") return cmp(Number(a), Number(b));
  const sa = String(a), sb = String(b);
  return codePointCmp(sa, sb);
}

function codePointCmp(a, b) {
  const ia = a[Symbol.iterator](), ib = b[Symbol.iterator]();
  for (;;) {
    const x = ia.next(), y = ib.next();
    if (x.done || y.done) return x.done && y.done ? 0 : x.done ? -1 : 1;
    if (x.value !== y.value) return x.value.codePointAt(0) - y.value.codePointAt(0);
  }
}

/** sorted(xs, key=…) — stable, Python ordering. */
export const sorted = (xs, key = (x) => x) => [...xs].map((x, i) => [key(x), i, x]).sort((p, q) => cmp(p[0], q[0]) || p[1] - q[1]).map((p) => p[2]);

const CACHE = new Map();
/** Compiled RegExp, cached by source and flags. */
export function re(src, flags = "") {
  const k = flags + "\u0000" + src;
  let r = CACHE.get(k);
  if (!r) { r = new RegExp(src, flags); CACHE.set(k, r); }
  r.lastIndex = 0;
  return r;
}

/** re.match: anchored at the start of `s` (sticky). */
export const match = (src, s, flags = "") => re(src, flags.replace("g", "") + "y").exec(s);
/** re.search. */
export const search = (src, s, flags = "") => re(src, flags.replace("g", "")).exec(s);
/** re.fullmatch. */
export const fullmatch = (src, s, flags = "") => re(`(?:${src})$`, flags.replace("g", "") + "y").exec(s);
/** re.finditer. */
export const finditer = (src, s, flags = "") => [...String(s).matchAll(re(src, flags.includes("g") ? flags : flags + "g"))];
/** re.sub (the replacement uses JavaScript's $1, not \1). */
export const sub = (src, rep, s, flags = "") => String(s).replace(re(src, flags.includes("g") ? flags : flags + "g"), rep);

/** re.findall: the whole match without groups, group 1 with one, the tuple of groups with several (missing groups are ""). */
export function findall(src, s, flags = "") {
  return finditer(src, s, flags).map((m) => (m.length === 1 ? m[0] : m.length === 2 ? m[1] ?? "" : m.slice(1).map((g) => g ?? "")));
}

/** str.strip() / rstrip() with Python's whitespace set (close enough: JavaScript's trim covers the same ASCII and Unicode spaces). */
export const strip = (s, chars) => (chars === undefined ? String(s).trim() : String(s).replace(new RegExp(`^[${escapeClass(chars)}]+|[${escapeClass(chars)}]+$`, "g"), ""));
const escapeClass = (c) => c.replace(/[\\\]^-]/g, "\\$&");

const LINE_BREAKS = new RegExp("\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]");

/** str.splitlines(): Python's line boundaries, no trailing empty line. */
export function splitlines(s) {
  const parts = String(s).split(LINE_BREAKS);
  if (parts.length && parts[parts.length - 1] === "") parts.pop();
  return parts;
}

/** Python set equality of two iterables. */
export function setEq(a, b) {
  const A = new Set(a), B = new Set(b);
  if (A.size !== B.size) return false;
  for (const x of A) if (!B.has(x)) return false;
  return true;
}
