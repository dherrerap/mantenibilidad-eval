#!/usr/bin/env node
// acceptance_check.mjs — Functional gate: verifies, against the running API, the behaviors of the domain requirements (ecommerce,
// cinema) and the contract of their minimum HTTP interface. Port of acceptance_check.py (see it for what the suites cover).
//   node js/acceptance_check.mjs --base http://localhost:4000 [--domain cinema] --out acceptance.json [--app <app folder>] [--suite r2]
// --suite r2 checks r2-additional-requirements.md instead (acceptance_r2.mjs); it reads ADMIN_EMAIL, ADMIN_PASSWORD, AUDITOR_EMAIL and
// AUDITOR_PASSWORD from the environment, the same values the backend was started with.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { F, dumps, isDict, loadJson, pyRound, repr, sorted, str } from "./lib/py.mjs";
import * as cc from "./contract_conformance.mjs";
import { findContracts } from "./evaluator/collectors/tools.mjs";
import { R2_SUITES } from "./acceptance_r2.mjs";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let CALLS = null;  // calls made through the Prism proxy, with the violations of its sl-violations header

// ───────────────────────── Python's failures, so that a case that breaks records the same detail ─────────────────────────
class PyError extends Error {
  constructor(type, msg) { super(msg); this.pyRepr = `${type}(${repr(msg)})`; }
}
const typeName = (x) => (x === null || x === undefined ? "NoneType" : typeof x === "boolean" ? "bool" : typeof x === "string" ? "str"
  : x instanceof Number ? "float" : typeof x === "number" ? (Number.isInteger(x) ? "int" : "float") : Array.isArray(x) ? "list" : "dict");
/** obj.get(key, default) of Python: AttributeError on something that is not a dict. */
function pget(obj, key, dflt = null) {
  if (!isDict(obj)) throw new PyError("AttributeError", `'${typeName(obj)}' object has no attribute 'get'`);
  return Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : dflt;
}
/** obj[key] of Python with a str key. */
function pidx(obj, key) {
  if (isDict(obj)) { if (Object.prototype.hasOwnProperty.call(obj, key)) return obj[key]; throw new PyError("KeyError", key); }
  if (Array.isArray(obj)) throw new PyError("TypeError", "list indices must be integers or slices, not str");
  if (typeof obj === "string") throw new PyError("TypeError", "string indices must be integers, not 'str'");
  throw new PyError("TypeError", `'${typeName(obj)}' object is not subscriptable`);
}
/** set(x) of Python for the dicts the cases compare: their keys. */
const keySet = (x) => new Set(isDict(x) ? Object.keys(x) : Array.isArray(x) ? x : typeof x === "string" ? [...x] : []);
const subset = (a, b) => [...a].every((x) => b.has(x));
const eqSet = (a, b) => a.size === b.size && subset(a, b);
/** Python ==, for the values the cases compare (numbers by value, lists and dicts deeply). */
export function eq(a, b) {
  if ((typeof a === "number" || a instanceof Number) && (typeof b === "number" || b instanceof Number)) return Number(a) === Number(b);
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => eq(x, b[i]));
  if (isDict(a) && isDict(b)) return eqSet(new Set(Object.keys(a)), new Set(Object.keys(b))) && Object.keys(a).every((k) => eq(a[k], b[k]));
  return a === b;
}

function record(method, p, status, headers) {
  if (CALLS === null) return;
  let v;
  try { v = loadJson(headers?.get?.("sl-violations") || "[]"); } catch { v = []; }
  CALLS.push({ method, path: p.split("?")[0], status, violations: Array.isArray(v) ? v : [] });
}

/** [status, body]: the JSON body (or its text when it is not JSON); [0, message] when there is no answer. */
export async function call(base, method, p, body = null, token = null) {
  let r;
  try {
    r = await fetch(base + p, { method, body: body === null ? undefined : dumps(body), signal: AbortSignal.timeout(15000),
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  } catch (e) { return [0, String(e.cause?.message || e.message)]; }
  const raw = await r.text();
  record(method, p, r.status, r.headers);
  if (!r.ok) {  // urllib raises HTTPError for 4xx/5xx: the body is parsed as JSON or dropped
    try { return [r.status, loadJson(raw || "null")]; } catch { return [r.status, null]; }
  }
  try { return [r.status, raw.trim() ? loadJson(raw) : null]; } catch { return [r.status, raw]; }
}

/** round(float(x), 2), or null when float(x) would fail. */
export function num(x) {
  let v;
  if (typeof x === "boolean") v = Number(x);
  else if (typeof x === "number" || x instanceof Number) v = Number(x);
  else if (typeof x === "string" && /^\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*$/.test(x)) v = Number(x);
  else return null;
  return pyRound(v, 2);
}

/** A JSON number (int or float); a string such as "10.00" is not, and neither is a boolean. */
export const isNumber = (x) => typeof x === "number" || x instanceof Number;
/** An integer or a UUID string (a float such as 1.0 is not an int in Python). */
export const isOpaqueId = (x) => (typeof x === "number" && Number.isInteger(x)) || (typeof x === "string" && UUID_RE.test(x));

/** `case(name, fn)`: runs fn at once and records [ok, detail]; an exception is a failed case. */
export async function runCase(results, name, fn) {
  let ok, detail;
  try { [ok, detail] = await fn(); } catch (e) { ok = false; detail = `exception: ${e.pyRepr || `${e.name}(${repr(e.message)})`}`; }
  results.push({ case: name, ok: Boolean(ok), detail });
}

export function testUsers() {
  const stamp = String(Date.now());
  return [{ name: "Ann", email: `ann${stamp}@test.com`, password: "Passw0rd!x" }, { name: "Bob", email: `bob${stamp}@test.com`, password: "Passw0rd!x" }];
}

export async function authCases(base, results, user, ctx) {
  await runCase(results, "register: 201", async () => { const [s] = await call(base, "POST", "/api/auth/register", user); return [s === 201, s]; });
  await runCase(results, "duplicate register: 409", async () => { const [s] = await call(base, "POST", "/api/auth/register", user); return [s === 409, s]; });
  await runCase(results, "login: 200 with token", async () => {
    const [s, b] = await call(base, "POST", "/api/auth/login", { email: user.email, password: user.password });
    ctx.ta = isDict(b) ? pget(b, "token") : null;
    return [s === 200 && Boolean(ctx.ta), s];
  });
  await runCase(results, "login with wrong password: 401", async () => { const [s] = await call(base, "POST", "/api/auth/login", { email: user.email, password: "x" }); return [s === 401, s]; });
}

/** Registers (if needed) and logs in `user`; the token or null. */
export async function login(base, user) {
  await call(base, "POST", "/api/auth/register", user);
  const [, b] = await call(base, "POST", "/api/auth/login", { email: user.email, password: user.password });
  return isDict(b) ? pget(b, "token") : null;
}

export function summary(base, results, domain) {
  const passed = results.filter((r) => r.ok).length;
  return { base, domain, total: results.length, passed, acceptance_pct: F(results.length ? pyRound((100.0 * passed) / results.length, 1) : 0.0), cases: results };
}

// ───────────────────────── ecommerce (requirements-ecommerce.md) ─────────────────────────
async function runEcommerce(base) {
  const results = [], ctx = {}, [A, B] = testUsers();
  const products = async () => {
    const [s, b] = await call(base, "GET", "/api/products");
    if (!(s === 200 && Array.isArray(b))) return {};
    const out = {};
    for (const p of b) out[str(pidx(p, "name"))] = p;
    return out;
  };
  const pid = async (name) => pget((await products())[name] || {}, "id");
  const stock = async (name) => pget((await products())[name] || {}, "stock");
  const C = (name, fn) => runCase(results, name, fn);

  await authCases(base, results, A, ctx);
  await C("catalog: fields id, name, price, description, imageUrl, stock", async () => {
    const b = Object.values(await products());
    const want = new Set(["id", "name", "price", "description", "imageUrl", "stock"]);
    return [b.length > 0 && b.every((p) => subset(want, keySet(p))), b.length ? sorted([...want].filter((x) => !keySet(b[0]).has(x))) : "empty catalog"];
  });
  await C("catalog: ids are integers or UUIDs and prices are JSON numbers", async () => {
    const b = Object.values(await products());
    const badIds = b.map((p) => pget(p, "id")).filter((x) => !isOpaqueId(x)), badPrices = b.map((p) => pget(p, "price")).filter((x) => !isNumber(x));
    return [b.length > 0 && !badIds.length && !badPrices.length, { ids_not_integer_or_uuid: badIds.slice(0, 3), prices_not_numbers: badPrices.slice(0, 3) }];
  });
  await C("catalog with 3 seed products and fields", async () => {
    const p = await products(), need = { "T-shirt": [10, 20], Mug: [5, 2], Book: [20, 50] };
    const ok = Object.entries(need).every(([k, v]) => k in p && eq(num(pget(p[k], "price")), v[0]) && eq(pget(p[k], "stock"), v[1]));
    return [ok, Object.fromEntries(Object.keys(need).map((k) => [k, pget(p[k] || {}, "stock")]))];
  });
  const quote = async (items) => {  // one pid() after the other, as Python's list comprehension: the calls keep their order
    const body = [];
    for (const [n, q] of items) body.push({ productId: await pid(n), quantity: q });
    return call(base, "POST", "/api/cart/quote", { items: body });
  };
  for (const [label, items, expTotal] of [["2 T-shirt = 20.00", [["T-shirt", 2]], 20.0], ["3 T-shirt = 27.00 (discount)", [["T-shirt", 3]], 27.0],
    ["5 T-shirt = 45.00 (discount)", [["T-shirt", 5]], 45.0], ["3 T-shirt + 1 Book = 47.00", [["T-shirt", 3], ["Book", 1]], 47.0]]) {
    await C("cart/quote: " + label, async () => {
      const [s, b] = await quote(items);
      return [s === 200 && isDict(b) && eq(num(pget(b, "total")), expTotal), [s, isDict(b) ? pget(b, "total") : b]];
    });
  }
  await C("cart/quote: lines carry numeric unitPrice and lineTotal (3 T-shirt = 10 x 3 -10% = 27)", async () => {
    const [s, b] = await quote([["T-shirt", 3]]);
    const lines = isDict(b) ? pget(b, "lines") : null;
    const ln = Array.isArray(lines) && lines.length ? lines[0] : {};
    const ok = s === 200 && isNumber(pget(b, "total")) && isNumber(pget(ln, "unitPrice")) && isNumber(pget(ln, "lineTotal")) &&
      eq(num(pget(ln, "unitPrice")), 10.0) && eq(num(pget(ln, "lineTotal")), 27.0) && eq(pget(ln, "quantity"), 3) && eq(pget(ln, "productId"), await pid("T-shirt"));
    return [ok, [s, ln, isDict(b) ? pget(b, "total") : b]];
  });
  await C("checkout without session: 401", async () => { const [s] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Book"), quantity: 1 }] }); return [s === 401, s]; });
  await C("checkout 3 T-shirt: 201, pending, total 27.00", async () => {
    const [s, b] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("T-shirt"), quantity: 3 }] }, ctx.ta ?? null);
    ctx.order1 = isDict(b) ? pget(b || {}, "id") : null;
    return [s === 201 && pget(b, "status") === "pending" && eq(num(pget(b, "total")), 27.0), [s, b]];
  });
  await C("checkout: id is an integer or UUID and total is a JSON number", async () => {
    const [s, b] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Book"), quantity: 1 }] }, ctx.ta ?? null);
    ctx.order_book = isDict(b) ? pget(b, "id") : null;
    return [s === 201 && isDict(b) && isOpaqueId(pget(b, "id")) && isNumber(pget(b, "total")) && eq(num(pget(b, "total")), 20.0), [s, b]];
  });
  await C("checkout deducts stock (T-shirt 20 → 17)", async () => { const v = await stock("T-shirt"); return [eq(v, 17), await stock("T-shirt")]; });
  await C("checkout with insufficient stock: 409 and stock untouched", async () => {
    const [s] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Mug"), quantity: 3 }] }, ctx.ta ?? null);
    return [s === 409 && eq(await stock("Mug"), 2), [s, await stock("Mug")]];
  });
  await C("atomic checkout: if one product falls short none is deducted", async () => {
    const before = await stock("Book");
    const [s] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Book"), quantity: 1 }, { productId: await pid("Mug"), quantity: 3 }] }, ctx.ta ?? null);
    return [s === 409 && eq(await stock("Book"), before), [s, before, await stock("Book")]];
  });
  await C("checkout 2 Mug: 201 and stock 0; then 1 Mug: 409", async () => {
    const [s1] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Mug"), quantity: 2 }] }, ctx.ta ?? null);
    const [s2] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Mug"), quantity: 1 }] }, ctx.ta ?? null);
    return [s1 === 201 && eq(await stock("Mug"), 0) && s2 === 409, [s1, await stock("Mug"), s2]];
  });
  await C("orders: the user sees their order with its status", async () => {
    const [s, b] = await call(base, "GET", "/api/orders", null, ctx.ta ?? null);
    const ids = Array.isArray(b) ? b.map((o) => pget(o, "id")) : [];
    return [s === 200 && ids.some((x) => eq(x, ctx.order1 ?? null)), [s, ids.length]];
  });
  await C("orders: each order has id, status and a numeric total", async () => {
    const [s, b] = await call(base, "GET", "/api/orders", null, ctx.ta ?? null);
    const bad = Array.isArray(b) ? b.filter((o) => !(isOpaqueId(pget(o, "id")) && ["pending", "paid", "shipped"].includes(pget(o, "status")) && isNumber(pget(o, "total")))) : null;
    return [s === 200 && Array.isArray(bad) && bad.length === 0 && b.length > 0, [s, bad && bad.length ? bad.slice(0, 2) : bad]];
  });
  await C("protected routes without a session: 401", async () => {
    const [s1] = await call(base, "GET", "/api/orders");
    const [s2] = await call(base, "PATCH", `/api/orders/${str(ctx.order1 ?? null)}/status`, { status: "paid" });
    return [s1 === 401 && s2 === 401, [s1, s2]];
  });
  await C("statuses: pending→paid→shipped in order", async () => {
    const o = str(ctx.order1 ?? null);
    const [s1] = await call(base, "PATCH", `/api/orders/${o}/status`, { status: "paid" }, ctx.ta ?? null);
    const [s2] = await call(base, "PATCH", `/api/orders/${o}/status`, { status: "shipped" }, ctx.ta ?? null);
    return [s1 === 200 && s2 === 200, [s1, s2]];
  });
  await C("statuses: cannot go back or skip", async () => {
    const o = str(ctx.order1 ?? null);
    const [back] = await call(base, "PATCH", `/api/orders/${o}/status`, { status: "pending" }, ctx.ta ?? null);
    const [, b] = await call(base, "POST", "/api/checkout", { items: [{ productId: await pid("Book"), quantity: 1 }] }, ctx.ta ?? null);
    const o2 = isDict(b) ? pget(b, "id") : null;
    const [skip] = await call(base, "PATCH", `/api/orders/${str(o2)}/status`, { status: "shipped" }, ctx.ta ?? null);
    return [back === 409 && skip === 409, [back, skip]];
  });
  await C("isolation: another user does not see other people's orders", async () => {
    await call(base, "POST", "/api/auth/register", B);
    const [, b] = await call(base, "POST", "/api/auth/login", { email: B.email, password: B.password });
    const tb = isDict(b) ? pget(b, "token") : null;
    const [s, orders] = await call(base, "GET", "/api/orders", null, tb);
    return [s === 200 && eq(orders, []), [s, orders]];
  });
  return summary(base, results, "ecommerce");
}

// ───────────────────────── cinema (requirements-cinema.md) ─────────────────────────
const CINEMA_TIMES = { "14:00": 6.0, "16:30": 6.0, "20:00": 9.0, "21:00": 9.0 };
const CINEMA_SEATS = [..."ABCD"].flatMap((r) => [1, 2, 3, 4, 5].map((n) => `${r}${n}`));

/** 'HH:MM' of an ISO 8601 date in this machine's time zone (a date without offset is taken as local). */
export function localHm(startsAt) {
  const s = str(startsAt);
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:?\d{2})?$/.exec(s);
  if (!m) throw new PyError("ValueError", `Invalid isoformat string: ${repr(s)}`);
  const d = m[8] ? new Date(s.replace(" ", "T")) : new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
  if (Number.isNaN(d.getTime())) throw new PyError("ValueError", `Invalid isoformat string: ${repr(s)}`);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function runCinema(base) {
  const results = [], ctx = {}, [A, B] = testUsers();
  const C = (name, fn) => runCase(results, name, fn);
  const showtimes = async () => { const [s, b] = await call(base, "GET", "/api/showtimes"); return s === 200 && Array.isArray(b) ? b : []; };
  const byTime = async () => {
    const out = {};
    for (const st of await showtimes()) {
      let hm;
      try { hm = localHm(pget(st, "startsAt")); } catch (e) { if (e.pyRepr && /^(TypeError|ValueError)/.test(e.pyRepr)) continue; throw e; }
      if (!(hm in out)) out[hm] = st;
    }
    return out;
  };
  const seatMap = async (tod) => {
    const st = (await byTime())[tod] || {};
    const [s, b] = await call(base, "GET", `/api/showtimes/${str(pget(st, "id"))}/seats`);
    if (!(s === 200 && Array.isArray(b))) return {};
    const out = {};
    for (const x of b) out[str(pget(x, "label"))] = x;
    return out;
  };
  const sid = async (tod) => pget((await byTime())[tod] || {}, "id");
  const seatIds = async (tod, labels) => { const seats = await seatMap(tod); return labels.map((lb) => pget(seats[lb] || {}, "id")); };
  const strSet = (xs) => new Set((xs || []).map((x) => str(x)));

  await authCases(base, results, A, ctx);
  ctx.tb = await login(base, B);
  await C("movies: fields id, title, description, imageUrl and the 2 seed movies", async () => {
    const [s, b] = await call(base, "GET", "/api/movies");
    const want = new Set(["id", "title", "description", "imageUrl"]);
    const ok = s === 200 && Array.isArray(b) && b.every((m) => subset(want, keySet(m))) && subset(new Set(["Movie One", "Movie Two"]), new Set(b.map((m) => pget(m, "title"))));
    return [ok, [s, Array.isArray(b) ? b.map((m) => pget(m, "title")) : b]];
  });
  await C("movies: ids are integers or UUIDs", async () => {
    const [s, b] = await call(base, "GET", "/api/movies");
    const bad = Array.isArray(b) ? b.map((m) => pget(m, "id")).filter((x) => !isOpaqueId(x)) : null;
    return [s === 200 && Array.isArray(bad) && !bad.length && b.length > 0, bad];
  });
  await C("showtimes: fields id, movieId, startsAt, room, price and the 4 seed screenings (14:00, 16:30, 20:00, 21:00)", async () => {
    const sts = await showtimes(), want = new Set(["id", "movieId", "startsAt", "room", "price"]);
    const ok = sts.every((x) => subset(want, keySet(x))) && subset(new Set(Object.keys(CINEMA_TIMES)), new Set(Object.keys(await byTime())));
    return [ok, sorted(Object.keys(await byTime()))];
  });
  await C("showtimes: price 6.00 before 17:00 and 9.00 from 17:00, as JSON numbers", async () => {
    const bt = await byTime();
    const got = Object.fromEntries(Object.keys(CINEMA_TIMES).map((t) => [t, pget(bt[t] || {}, "price")]));
    return [Object.entries(got).every(([t, v]) => isNumber(v) && eq(num(v), CINEMA_TIMES[t])), got];
  });
  await C("seat map: 20 seats A1…D5, all available, with integer or UUID ids", async () => {
    const seats = await seatMap("14:00");
    const ok = eq(sorted(Object.keys(seats)), sorted(CINEMA_SEATS)) && Object.values(seats).every((x) => pget(x, "status") === "available") && Object.values(seats).every((x) => isOpaqueId(pget(x, "id")));
    return [ok, { labels: Object.keys(seats).length, statuses: sorted([...new Set(Object.values(seats).map((x) => str(pget(x, "status"))))]) }];
  });
  for (const [label, tod, n, expUnit, expTotal] of [["2 seats at 14:00 = 12.00", "14:00", 2, 6.0, 12.0], ["2 seats at 20:00 = 18.00", "20:00", 2, 9.0, 18.0], ["3 seats at 16:30 = 18.00", "16:30", 3, 6.0, 18.0]]) {
    await C("quote: " + label + " (numeric unitPrice and total)", async () => {
      const [s, b] = await call(base, "POST", `/api/showtimes/${str(await sid(tod))}/quote`, { seatIds: await seatIds(tod, CINEMA_SEATS.slice(-n)) });
      const ok = s === 200 && isDict(b) && isNumber(pget(b, "unitPrice")) && isNumber(pget(b, "total")) && eq(num(pget(b, "unitPrice")), expUnit) && eq(num(pget(b, "total")), expTotal) && eq(pget(b, "seats"), n);
      return [ok, [s, b]];
    });
  }
  await C("lock without session: 401", async () => { const [s] = await call(base, "POST", `/api/showtimes/${str(await sid("20:00"))}/lock`, { seatIds: await seatIds("20:00", ["A1"]) }); return [s === 401, s]; });
  await C("lock A1 and A2 (20:00): 200 with seatIds and expiresAt", async () => {
    const ids = await seatIds("20:00", ["A1", "A2"]);
    const [s, b] = await call(base, "POST", `/api/showtimes/${str(await sid("20:00"))}/lock`, { seatIds: ids }, ctx.ta ?? null);
    return [s === 200 && isDict(b) && Boolean(pget(b, "expiresAt")) && eqSet(strSet(pget(b, "seatIds") || []), strSet(ids)), [s, b]];
  });
  await C("lock: another user cannot lock a seat that is locked (409)", async () => {
    const [s] = await call(base, "POST", `/api/showtimes/${str(await sid("20:00"))}/lock`, { seatIds: await seatIds("20:00", ["A1"]) }, ctx.tb ?? null); return [s === 409, s];
  });
  await C("seat map: a locked seat is shown as locked", async () => { const st = pget((await seatMap("20:00")).A1 || {}, "status"); return [st === "locked", st]; });
  await C("checkout without session: 401", async () => { const [s] = await call(base, "POST", "/api/checkout", { showtimeId: await sid("20:00"), seatIds: await seatIds("20:00", ["A1"]) }); return [s === 401, s]; });
  await C("checkout A1 + A2 (20:00): 201 with id, showtimeId, seatIds and total 18.00", async () => {
    const ids = await seatIds("20:00", ["A1", "A2"]);
    const [s, b] = await call(base, "POST", "/api/checkout", { showtimeId: await sid("20:00"), seatIds: ids }, ctx.ta ?? null);
    ctx.order1 = isDict(b) ? pget(b, "id") : null;
    const ok = s === 201 && isDict(b) && str(pget(b, "showtimeId")) === str(await sid("20:00")) && eq(num(pget(b, "total")), 18.0) && eqSet(strSet(pget(b, "seatIds") || []), strSet(ids));
    return [ok, [s, b]];
  });
  await C("checkout: id is an integer or UUID and total is a JSON number", async () => {
    const [s, b] = await call(base, "GET", "/api/orders", null, ctx.ta ?? null);
    const o = Array.isArray(b) ? b.find((x) => eq(pget(x, "id"), ctx.order1 ?? null)) ?? null : null;
    return [Boolean(o) && isOpaqueId(ctx.order1 ?? null) && isNumber(pget(o, "total")), [s, o]];
  });
  await C("seat map: the purchased seats are sold", async () => {
    const seats = await seatMap("20:00");
    const got = Object.fromEntries(["A1", "A2"].map((lb) => [lb, pget(seats[lb] || {}, "status")]));
    return [Object.values(got).every((v) => v === "sold"), got];
  });
  await C("checkout with a sold seat: 409 and the other seat stays available", async () => {
    const [s] = await call(base, "POST", "/api/checkout", { showtimeId: await sid("20:00"), seatIds: await seatIds("20:00", ["A2", "A3"]) }, ctx.tb ?? null);
    const a3 = pget((await seatMap("20:00")).A3 || {}, "status");
    return [s === 409 && a3 === "available", [s, a3]];
  });
  await C("seats sold in one screening do not affect another (A1 at 21:00 is available)", async () => { const st = pget((await seatMap("21:00")).A1 || {}, "status"); return [st === "available", st]; });
  await C("orders: the user sees their purchase with showtimeId, seatIds and a numeric total", async () => {
    const [s, b] = await call(base, "GET", "/api/orders", null, ctx.ta ?? null);
    const o = Array.isArray(b) ? b.find((x) => eq(pget(x, "id"), ctx.order1 ?? null)) ?? null : null;
    return [s === 200 && Boolean(o) && subset(new Set(["id", "showtimeId", "seatIds", "total"]), keySet(o)) && isNumber(pget(o, "total")), [s, o]];
  });
  await C("protected routes without a session: 401", async () => { const [s] = await call(base, "GET", "/api/orders"); return [s === 401, s]; });
  await C("isolation: another user does not see other people's purchases", async () => {
    const [s, orders] = await call(base, "GET", "/api/orders", null, ctx.tb ?? null);
    return [s === 200 && eq(orders, []), [s, orders]];
  });
  return summary(base, results, "cinema");
}

export const SUITES = { ecommerce: runEcommerce, cinema: runCinema };

/** `suite` "r1" is the original requirements; "r2" the additional ones (acceptance_r2.mjs), for a project that implements them. */
export function run(base, domain = "ecommerce", suite = "r1") {
  const suites = suite === "r2" ? R2_SUITES : SUITES;
  if (!(domain in suites)) throw new Error(`no ${suite} acceptance suite for domain '${domain}' (available: ${sorted(Object.keys(suites)).join(", ")})`);
  return suites[domain](base);
}

/** The suite through a Prism proxy that validates every response against the app's OpenAPI contract; `_conformance` carries the
 *  conformance or why it was not measured. A proxy failure never fails the gate: the suite then runs direct. */
export async function runWithContract(base, domain, app, suite = "r1") {
  const found = findContracts(app);
  if (!found.length) return { ...(await run(base, domain, suite)), _conformance: cc.withoutPrism("the app has no OpenAPI contract") };
  const contract = path.join(app, found[0]);
  if (!cc.available()) return { ...(await run(base, domain, suite)), _conformance: cc.withoutPrism("Prism is not installed (npm install)", found[0]) };
  const proxy = new cc.Proxy(contract, base);
  let proxied;
  try { proxied = await proxy.open(); } catch (e) {
    proxy.close();
    return { ...(await run(base, domain, suite)), _conformance: cc.withoutPrism(String(e.message).slice(0, 300), found[0]) };
  }
  CALLS = [];
  try {
    const res = await run(proxied, domain, suite);
    res.base = base;
    return { ...res, _conformance: cc.summarize(CALLS, found[0], proxy.base_path) };
  } finally { CALLS = null; proxy.close(); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), o = { base: "http://localhost:4000", out: "acceptance.json", domain: "ecommerce", app: null, suite: "r1" };
  for (let i = 0; i < args.length; i++) if (args[i].startsWith("--")) o[args[i].slice(2)] = args[++i];
  const base = o.base.replace(/\/+$/, "");
  let conformance = null, res;
  if (o.app) { res = await runWithContract(base, o.domain, o.app, o.suite); conformance = res._conformance; delete res._conformance; }
  else res = await run(base, o.domain, o.suite);
  fs.writeFileSync(o.out, dumps(res, 1), "utf8");
  if (conformance !== null) {
    fs.writeFileSync(path.join(path.dirname(path.resolve(o.out)), cc.RESULT_FILE), dumps(conformance, 1), "utf8");
    console.log(conformance.ok ? `Contract conformance: ${str(conformance.conformance_pct ?? "n/a")}%` : `Contract conformance not measured: ${str(conformance.error)}`);
  }
  for (const r of res.cases) console.log(r.ok ? "✔" : "✘", r.case, r.ok ? "" : `→ ${repr(r.detail)}`);
  console.log(`\nAcceptance: ${res.passed}/${res.total} = ${str(res.acceptance_pct)}%`);
}
