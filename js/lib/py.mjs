import { readFileSync as fsRead } from "node:fs";
// py.mjs — The few Python semantics the port must reproduce exactly, so that the JavaScript evaluator returns the same JSON as the
// Python one: truthiness, str()/repr(), round() (half to even on the exact binary value), ordering of mixed values, re.match
// (anchored at the start), re.findall, and a cache of compiled regular expressions.

/** A Python float. JSON and JavaScript numbers do not tell 1.0 from 1, but Python prints them differently ("1.0" vs "1"), so a value
 *  that is a float in Python and is printed with str()/repr() is wrapped in PyFloat (F(x)). It serializes to JSON as a number. */
export class PyFloat extends Number {}
export const F = (x) => (x === null || x === undefined ? null : x instanceof PyFloat ? x : new PyFloat(Number(x)));
/** The primitive value of a number that may be a PyFloat. */
export const num = (x) => (x instanceof Number ? x.valueOf() : x);

/** json.loads: like JSON.parse, but a number written with a decimal point or an exponent becomes a PyFloat, as Python's json makes it
 *  a float (so 5.0 in rubric.json prints "5.0" and 5 prints "5"). Uses the source text of each value (Node.js ≥ 21). */
export const loadJson = (text) => JSON.parse(text, (k, v, ctx) => (typeof v === "number" && ctx && /[.eE]/.test(ctx.source) ? new PyFloat(v) : v));

/** A plain object (Python dict), not an array, a PyFloat or null. */
export const isDict = (v) => v !== null && typeof v === "object" && !Array.isArray(v) && !(v instanceof Number);

/** Python truthiness: None, False, 0, "", [] and {} are false. */
export function truthy(v) {
  if (v instanceof Number) v = v.valueOf();
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

/** repr() of a Python float: 1.0, 0.5, 1e-05, 1e+16. */
export function floatRepr(n) {
  n = num(n);
  if (Number.isInteger(n) && Math.abs(n) < 1e16) return String(n) + ".0";
  return reprNum(n);
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
  if (v instanceof Number) return floatRepr(v);  // a PyFloat (or a copy of one that lost its class)
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

function roundScaled(x, n) {
  const [D, k] = exactDecimal(x);
  if (k <= n) return D * 10n ** BigInt(n - k);
  const p = 10n ** BigInt(k - n), r = D % p, half = p / 2n;
  let q = D / p;
  if (r > half || (r === half && q % 2n === 1n)) q += 1n;
  return q;
}

/** format(x, ".nf"): fixed notation, half to even on the exact binary value (Python), not toFixed's "larger on a tie". */
export function fixed(x, n) {
  x = num(x);
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  const neg = x < 0 || Object.is(x, -0);
  const q = x === 0 ? 0n : roundScaled(Math.abs(x), n);
  const s = q.toString().padStart(n + 1, "0");
  const out = n ? s.slice(0, s.length - n) + "." + s.slice(s.length - n) : s;
  return (neg ? "-" : "") + out;
}

/** format(x, "g"): 6 significant digits, trailing zeros removed, scientific below 1e-4 and from 1e6. */
export function gfmt(x) {
  x = num(x);
  if (x === 0) return Object.is(x, -0) ? "-0" : "0";
  if (!Number.isFinite(x)) return Number.isNaN(x) ? "nan" : x > 0 ? "inf" : "-inf";
  const [m, e] = x.toExponential(5).split("e");
  const exp = Number(e);
  const strip = (t) => (t.includes(".") ? t.replace(/0+$/, "").replace(/\.$/, "") : t);
  if (exp >= -4 && exp < 6) return strip(fixed(x, 5 - exp));
  return strip(m) + "e" + (exp < 0 ? "-" : "+") + String(Math.abs(exp)).padStart(2, "0");
}

/** str.format for the templates of rubric.json: {name} and {name:.Nf} / {name:g}. */
export function format(tpl, vars) {
  return tpl.replace(/\{(\w+)(?::([^}]*))?\}/g, (_, k, spec) => {
    const v = vars[k];
    if (!spec) return str(v);
    const f = /^\.(\d+)f$/.exec(spec);
    if (f) return fixed(v, Number(f[1]));
    if (spec === "g") return gfmt(v);
    throw new Error(`format spec not supported: ${spec}`);
  });
}

/** Python round(x, n): half to even on the exact binary value of x (round(0.125, 2) == 0.12, round(2.675, 2) == 2.67). */
export function pyRound(x, n = 0) {
  x = num(x);
  if (!Number.isFinite(x) || x === 0) return x;
  const v = Number(`${roundScaled(Math.abs(x), n)}e-${n}`);
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
  a = num(a); b = num(b);
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

/** json.dumps(v, indent=n, ensure_ascii=False): Python's layout (", " / ": " separators, one item per line with `indent`), floats
 *  as Python writes them (50.0, 1e-05, NaN, Infinity). */
export function dumps(v, indent = null, level = 0, ascii = false) {
  const nl = indent === null ? "" : "\n" + " ".repeat(indent * (level + 1));
  const end = indent === null ? "" : "\n" + " ".repeat(indent * level);
  const sep = indent === null ? ", " : ",";
  // ensure_ascii: every UTF-16 unit above ASCII as \uXXXX (an astral character becomes its surrogate pair, as in Python)
  const s = (t) => (ascii ? JSON.stringify(t).replace(/[\u007f-\uffff]/g, (c) => String.raw`\u` + c.charCodeAt(0).toString(16).padStart(4, "0")) : JSON.stringify(t));
  if (v === null || v === undefined) return "null";
  if (v === true) return "true";
  if (v === false) return "false";
  if (v instanceof Number || typeof v === "number") {
    const x = Number(v);
    if (Number.isNaN(x)) return "NaN";
    if (!Number.isFinite(x)) return x > 0 ? "Infinity" : "-Infinity";
    return v instanceof Number ? floatRepr(x) : reprNum(x);
  }
  if (typeof v === "string") return s(v);
  if (Array.isArray(v)) return v.length ? "[" + v.map((x) => nl + dumps(x, indent, level + 1, ascii)).join(sep) + end + "]" : "[]";
  const ks = Object.keys(v).filter((k) => v[k] !== undefined);
  return ks.length ? "{" + ks.map((k) => nl + s(k) + ": " + dumps(v[k], indent, level + 1, ascii)).join(sep) + end + "}" : "{}";
}

/** json.dumps(v, indent=n) with Python's default ensure_ascii=True: every character above ASCII as \uXXXX. */
export const dumpsAscii = (v, indent = null) => dumps(v, indent, 0, true);

/** csv.writer (excel dialect) row: fields with , " \r or \n quoted, quotes doubled, None empty, "\r\n" at the end. */
export function csvRow(fields) {
  const cell = (f) => {
    const s = f === null || f === undefined ? "" : str(f);
    return /[,"\r\n]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s;
  };
  const out = fields.map(cell);
  if (out.length === 1 && out[0] === "") out[0] = '""';  // csv writes a lone empty field as "" so the row is not blank
  return out.join(",") + "\r\n";
}

/** Path.read_text(encoding="utf-8"): text mode, so "\r\n" and "\r" become "\n" (universal newlines), as Python reads every file. */
export const readText = (p) => fsRead(p, "utf8").replace(/\r\n?/g, "\n");
