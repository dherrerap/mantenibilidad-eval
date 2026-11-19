// acceptance_r2.mjs — Functional gate of phase r2: verifies, against the running API, Requirements 1 to 9 of
// specs/r2-additional-requirements.md through the HTTP interface that document fixes "to verify the delivery automatically", plus the
// original rules that must keep working under r2 (prices now include shipping).
//
// The backend must have been started with ADMIN_EMAIL/ADMIN_PASSWORD and AUDITOR_EMAIL/AUDITOR_PASSWORD (the gate reads the same values
// from its environment), REPLICA_DATABASE_URL pointing at an empty PostgreSQL database and SQLSERVER_URL unset: the replica must
// answer like the primary and SQL Server with 503 SOURCE_UNAVAILABLE. Only the ecommerce domain has an r2 suite.
import { randomBytes } from "node:crypto";
import { authCases, call, eq, isNumber, login, num, runCase, summary, testUsers } from "./acceptance_check.mjs";
import { isDict, str } from "./lib/py.mjs";

/** Credentials for the bootstrap accounts of Requirement 4: the backend and the gate get the same ones. */
export function r2Credentials() {
  const stamp = String(Date.now()), pw = () => `R2pass!${randomBytes(6).toString("hex")}`;
  return { ADMIN_EMAIL: `admin${stamp}@test.com`, ADMIN_PASSWORD: pw(), AUDITOR_EMAIL: `auditor${stamp}@test.com`, AUDITOR_PASSWORD: pw() };
}

const g = (o, k) => (isDict(o) && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : null);
const errOf = (b) => g(b, "error");
const rejected = (s, b, status, code) => s === status && errOf(b) === code;
const sameId = (a, b) => a !== null && a !== undefined && str(a) === str(b);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function runEcommerceR2(base, creds = process.env) {
  const results = [], ctx = {}, [A, B] = testUsers(), stamp = String(Date.now());
  const user = (n) => ({ name: n, email: `${n.toLowerCase()}${stamp}@test.com`, password: "Passw0rd!x" });
  const C = (name, fn) => runCase(results, name, fn);
  const list = async (query = "", token = null) => {
    const [s, b] = await call(base, "GET", "/api/products" + query, null, token);
    return [s, Array.isArray(b) ? b : null, b];
  };
  const byName = async () => Object.fromEntries(((await list())[1] || []).map((p) => [str(g(p, "name")), p]));
  const pid = async (name) => g((await byName())[name] || {}, "id");
  const stock = async (name) => g((await byName())[name] || {}, "stock");
  const items = async (spec) => { const out = []; for (const [n, q] of spec) out.push({ productId: await pid(n), quantity: q }); return out; };
  const quote = async (spec, couponCode = null) => call(base, "POST", "/api/cart/quote", { items: await items(spec), ...(couponCode ? { couponCode } : {}) });
  const checkout = async (spec, token, couponCode = null) => call(base, "POST", "/api/checkout", { items: await items(spec), ...(couponCode ? { couponCode } : {}) }, token);
  const setStatus = (id, status, token) => call(base, "PATCH", `/api/orders/${str(id)}/status`, { status }, token);
  const audit = (entity, id, token) => call(base, "GET", `/api/audit?entity=${entity}&id=${encodeURIComponent(str(id))}`, null, token);
  const coupons = async (token) => { const [s, b] = await call(base, "GET", "/api/coupons", null, token); return [s, Array.isArray(b) ? b : null]; };
  const coupon = async (code) => ((await coupons(ctx.tad))[1] || []).find((c) => str(g(c, "code")).toLowerCase() === code.toLowerCase()) || null;
  const money = (b, ...keys) => Object.fromEntries(keys.map((k) => [k, isNumber(g(b, k)) ? num(g(b, k)) : g(b, k)]));
  const amounts = (b, want) => Object.entries(want).every(([k, v]) => isNumber(g(b, k)) && eq(num(g(b, k)), v));

  // ── the original rules that do not change under r2 ──
  await authCases(base, results, A, ctx);
  ctx.tb = await login(base, B);
  await C("catalog: 3 seed products with fields id, name, price, description, imageUrl, stock", async () => {
    const p = await byName(), need = { "T-shirt": [10, 20], Mug: [5, 2], Book: [20, 50] };
    const want = ["id", "name", "price", "description", "imageUrl", "stock"];
    const ok = Object.entries(need).every(([k, v]) => k in p && want.every((f) => f in p[k]) && eq(num(g(p[k], "price")), v[0]) && eq(g(p[k], "stock"), v[1]));
    return [ok, Object.fromEntries(Object.keys(need).map((k) => [k, p[k] ? { price: g(p[k], "price"), stock: g(p[k], "stock") } : null]))];
  });

  // ── Requirement 4: roles ──
  await C("R4 register always creates a regular user (a requested role is ignored); /me returns id, name, email, role", async () => {
    const E = { ...user("Eve"), role: "admin" };
    const [s] = await call(base, "POST", "/api/auth/register", E);
    const t = await login(base, E);
    const [sm, me] = await call(base, "GET", "/api/auth/me", null, t);
    const ok = s === 201 && sm === 200 && ["id", "name", "email", "role"].every((k) => g(me, k) !== null) && g(me, "role") === "user";
    return [ok, [s, sm, me]];
  });
  await C("R4 bootstrap accounts from ADMIN_* and AUDITOR_*: roles admin and auditor", async () => {
    ctx.tad = await login(base, { email: creds.ADMIN_EMAIL, password: creds.ADMIN_PASSWORD });
    ctx.tau = await login(base, { email: creds.AUDITOR_EMAIL, password: creds.AUDITOR_PASSWORD });
    const [, a] = await call(base, "GET", "/api/auth/me", null, ctx.tad);
    const [, u] = await call(base, "GET", "/api/auth/me", null, ctx.tau);
    return [g(a, "role") === "admin" && g(u, "role") === "auditor", [g(a, "role"), g(u, "role")]];
  });
  const lamp = { name: `R2 Lamp ${stamp}`, price: 12.5, description: "Desk lamp", imageUrl: "https://example.com/lamp.png", stock: 7 };
  await C("R4 creating a product: 403 FORBIDDEN for a user and for the auditor, 201 with the record for the admin", async () => {
    const [su, bu] = await call(base, "POST", "/api/products", lamp, ctx.ta ?? null);
    const [sa, ba] = await call(base, "POST", "/api/products", lamp, ctx.tau ?? null);
    const [s, b] = await call(base, "POST", "/api/products", lamp, ctx.tad ?? null);
    ctx.lamp = g(b, "id");
    return [rejected(su, bu, 403, "FORBIDDEN") && rejected(sa, ba, 403, "FORBIDDEN") && s === 201 && ctx.lamp !== null && g(b, "name") === lamp.name, [su, sa, s, b]];
  });
  await C("R4 editing a product: 403 for a user, 200 with the record for the admin", async () => {
    const [su] = await call(base, "PUT", `/api/products/${str(ctx.lamp)}`, { ...lamp, price: 15 }, ctx.ta ?? null);
    const [s, b] = await call(base, "PUT", `/api/products/${str(ctx.lamp)}`, { ...lamp, price: 15 }, ctx.tad ?? null);
    return [su === 403 && s === 200 && eq(num(g(b, "price")), 15.0), [su, s, b]];
  });

  // ── Requirement 2: audit ──
  const auditFields = ["action", "entity", "entityId", "userId", "at", "before", "after"];
  await C("R2 audit of the product: create then update, oldest first, with who, when, before and after", async () => {
    const [s, b] = await audit("product", ctx.lamp, ctx.tad);
    const ev = Array.isArray(b) ? b : [];
    const [c, u] = ev;
    const ok = s === 200 && ev.length >= 2 && ev.every((e) => auditFields.every((f) => isDict(e) && f in e)) && g(c, "action") === "create" &&
      g(c, "before") === null && isDict(g(c, "after")) && g(u, "action") === "update" && eq(num(g(g(u, "before"), "price")), 12.5) &&
      eq(num(g(g(u, "after"), "price")), 15.0) && g(c, "userId") !== null && Boolean(g(c, "at")) && sameId(g(c, "entityId"), ctx.lamp);
    return [ok, [s, ev.slice(0, 2)]];
  });
  await C("R2 audit history: 403 for a regular user, 200 for the auditor", async () => {
    const [su] = await audit("product", ctx.lamp, ctx.ta);
    const [sa, b] = await audit("product", ctx.lamp, ctx.tau);
    return [su === 403 && sa === 200 && Array.isArray(b), [su, sa]];
  });

  // ── Requirement 3: logical deletion ──
  await C("R3 deleting a product: 403 for a user; 204 for the admin and it leaves the listing", async () => {
    const [su] = await call(base, "DELETE", `/api/products/${str(ctx.lamp)}`, null, ctx.ta ?? null);
    const [s] = await call(base, "DELETE", `/api/products/${str(ctx.lamp)}`, null, ctx.tad ?? null);
    const [, l] = await list();
    const gone = Array.isArray(l) && !l.some((p) => sameId(g(p, "id"), ctx.lamp));
    return [su === 403 && s === 204 && gone, [su, s, gone]];
  });
  await C("R3 includeDeleted=true: admin and auditor see it with deletedAt and deletedBy; 403 for a user", async () => {
    const find = (l) => (l || []).find((p) => sameId(g(p, "id"), ctx.lamp)) || null;
    const [sa, la] = await list("?includeDeleted=true", ctx.tad);
    const [sau, lau] = await list("?includeDeleted=true", ctx.tau);
    const [su] = await list("?includeDeleted=true", ctx.ta);
    const p = find(la);
    return [sa === 200 && sau === 200 && su === 403 && Boolean(g(p, "deletedAt")) && g(p, "deletedBy") !== null && find(lau) !== null, [sa, sau, su, p]];
  });
  await C("R3 a deleted product cannot be edited (404) and its audit ends with a delete that keeps the record", async () => {
    const [s] = await call(base, "PUT", `/api/products/${str(ctx.lamp)}`, { ...lamp, price: 16 }, ctx.tad ?? null);
    const [, b] = await audit("product", ctx.lamp, ctx.tad);
    const last = Array.isArray(b) && b.length ? b.at(-1) : null;
    return [s === 404 && g(last, "action") === "delete" && isDict(g(last, "after")), [s, last]];
  });

  // ── Requirement 1: additional databases ──
  const view = (l) => (l || []).map((p) => [str(g(p, "id")), g(p, "name"), num(g(p, "price")), g(p, "stock")]).sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
  await C("R1 source=primary returns the same listing as no source", async () => {
    const [s, l] = await list("?source=primary"), [, d] = await list();
    return [s === 200 && eq(view(l), view(d)) && (l || []).length > 0, [s, (l || []).length, (d || []).length]];
  });
  await C("R1 source=replica returns the same products as the primary (synchronized on every write)", async () => {
    let s, l, d;
    for (let i = 0; i < 10; i++) {  // the replica is written right after the primary commit: allow a few seconds
      [s, l] = await list("?source=replica");
      [, d] = await list();
      if (s === 200 && eq(view(l), view(d))) break;
      await sleep(1000);
    }
    return [s === 200 && eq(view(l), view(d)), [s, view(l).slice(0, 4), view(d).slice(0, 4)]];
  });
  await C("R1 source=sqlserver without SQLSERVER_URL: 503 SOURCE_UNAVAILABLE; unknown source: 422 SOURCE_INVALID", async () => {
    const [s1, , b1] = await list("?source=sqlserver");
    const [s2, , b2] = await list("?source=nosuchdb");
    return [rejected(s1, b1, 503, "SOURCE_UNAVAILABLE") && rejected(s2, b2, 422, "SOURCE_INVALID"), [s1, errOf(b1), s2, errOf(b2)]];
  });

  // ── Requirement 8: tiered discount and shipping ──
  for (const [label, spec, sub, ship, total] of [["2 T-shirt", [["T-shirt", 2]], 20, 5, 25], ["3 T-shirt", [["T-shirt", 3]], 27, 5, 32],
    ["5 T-shirt", [["T-shirt", 5]], 45, 5, 50], ["10 T-shirt", [["T-shirt", 10]], 80, 0, 80], ["3 T-shirt + 1 Book", [["T-shirt", 3], ["Book", 1]], 47, 5, 52],
    ["3 T-shirt + 2 Book", [["T-shirt", 3], ["Book", 2]], 67, 0, 67]]) {
    await C(`R8 quote ${label}: subtotal ${sub}.00, shipping ${ship}.00, discount 0, total ${total}.00`, async () => {
      const [s, b] = await quote(spec);
      return [s === 200 && amounts(b, { subtotal: sub, shipping: ship, discount: 0, total }), [s, money(b, "subtotal", "shipping", "discount", "total")]];
    });
  }
  await C("R8 quote lines: lineTotal without shipping (3 T-shirt: unitPrice 10, lineTotal 27)", async () => {
    const [s, b] = await quote([["T-shirt", 3]]);
    const ln = Array.isArray(g(b, "lines")) ? g(b, "lines")[0] : null;
    return [s === 200 && amounts(ln, { unitPrice: 10, lineTotal: 27 }), [s, ln]];
  });

  // ── Requirement 6: coupons ──
  const future = new Date(Date.now() + 30 * 86400000).toISOString(), past = new Date(Date.now() - 86400000).toISOString();
  const code = (k) => `${k}${stamp}`;
  const newCoupon = (k, type, value, maxUses = 100, expiresAt = future) => ({ code: code(k), type, value, expiresAt, maxUses });
  await C("R6 coupons: 403 for a user; the admin creates them (201); the same code in another case: 409", async () => {
    const [su] = await call(base, "POST", "/api/coupons", newCoupon("USR", "percent", 10), ctx.ta ?? null);
    const made = [];
    for (const c of [newCoupon("PCT", "percent", 10), newCoupon("FIX", "fixed", 5), newCoupon("BIG", "fixed", 30), newCoupon("OLD", "percent", 10, 100, past),
      newCoupon("ONE", "fixed", 5, 1), newCoupon("OFF", "percent", 10)]) made.push((await call(base, "POST", "/api/coupons", c, ctx.tad ?? null))[0]);
    const [sd] = await call(base, "POST", "/api/coupons", { ...newCoupon("PCT", "percent", 10), code: code("pct") }, ctx.tad ?? null);
    return [su === 403 && made.every((s) => s === 201) && sd === 409, [su, made, sd]];
  });
  await C("R6 the admin and the auditor list the coupons with usedCount", async () => {
    const [sa, la] = await coupons(ctx.tad), [sau, lau] = await coupons(ctx.tau);
    const mine = (la || []).filter((c) => str(g(c, "code")).endsWith(stamp));
    return [sa === 200 && sau === 200 && mine.length >= 6 && mine.every((c) => eq(g(c, "usedCount"), 0)) && (lau || []).length === (la || []).length, [sa, sau, mine.length]];
  });
  for (const [label, k, disc, total] of [["10%", "PCT", 4.7, 47.3], ["fixed 5.00", "FIX", 5, 47], ["fixed 30.00 (capped at 50%)", "BIG", 23.5, 28.5]]) {
    await C(`R6 coupon ${label} on 3 T-shirt + 1 Book: subtotal 47.00, discount ${disc}, shipping 5.00, total ${total}`, async () => {
      const [s, b] = await quote([["T-shirt", 3], ["Book", 1]], code(k));
      return [s === 200 && amounts(b, { subtotal: 47, discount: disc, shipping: 5, total }), [s, money(b, "subtotal", "discount", "shipping", "total")]];
    });
  }
  await C("R6 coupon codes are case-insensitive", async () => {
    const [s, b] = await quote([["T-shirt", 3], ["Book", 1]], code("pct").toLowerCase());
    return [s === 200 && amounts(b, { discount: 4.7 }), [s, g(b, "discount")]];
  });
  await C("R6 unknown coupon: 422 COUPON_INVALID; expired coupon: 422 COUPON_EXPIRED", async () => {
    const [s1, b1] = await quote([["Book", 1]], code("NOPE"));
    const [s2, b2] = await quote([["Book", 1]], code("OLD"));
    return [rejected(s1, b1, 422, "COUPON_INVALID") && rejected(s2, b2, 422, "COUPON_EXPIRED"), [s1, errOf(b1), s2, errOf(b2)]];
  });
  await C("R6 quoting never consumes a use of the coupon", async () => { const c = await coupon(code("PCT")); return [c !== null && eq(g(c, "usedCount"), 0), c]; });
  await C("R6 checkout with a coupon: 201 with subtotal, discount, shipping and total, and one use consumed", async () => {
    const [s, b] = await checkout([["Book", 1]], ctx.ta, code("ONE"));
    ctx.couponOrder = g(b, "id");
    const c = await coupon(code("ONE"));
    return [s === 201 && g(b, "status") === "pending" && amounts(b, { subtotal: 20, discount: 5, shipping: 5, total: 20 }) && eq(g(c, "usedCount"), 1),
      [s, b, g(c, "usedCount")]];
  });
  await C("R6 exhausted coupon: 409 COUPON_EXHAUSTED and the rejected checkout consumes nothing", async () => {
    const before = await stock("Book");
    const [s, b] = await checkout([["Book", 1]], ctx.tb, code("ONE"));
    const after = await stock("Book"), c = await coupon(code("ONE"));
    return [rejected(s, b, 409, "COUPON_EXHAUSTED") && eq(after, before) && eq(g(c, "usedCount"), 1), [s, errOf(b), before, after]];
  });
  await C("R6 cancelling the order returns the use of its coupon", async () => {
    const [s] = await setStatus(ctx.couponOrder, "cancelled", ctx.ta);
    const c = await coupon(code("ONE"));
    return [s === 200 && eq(g(c, "usedCount"), 0), [s, g(c, "usedCount")]];
  });
  await C("R6 a deactivated coupon (DELETE 204) is kept (listed, or with includeDeleted=true) but is COUPON_INVALID", async () => {
    const id = g(await coupon(code("OFF")), "id");
    const [s] = await call(base, "DELETE", `/api/coupons/${str(id)}`, null, ctx.tad ?? null);
    const [sq, b] = await quote([["Book", 1]], code("OFF"));
    // Requirement 3 hides deleted records from the default listings, so the kept coupon may only show with includeDeleted=true
    const [, all] = await call(base, "GET", "/api/coupons?includeDeleted=true", null, ctx.tad ?? null);
    const kept = (await coupon(code("OFF"))) !== null || (Array.isArray(all) && all.some((c) => sameId(g(c, "id"), id)));
    return [s === 204 && kept && rejected(sq, b, 422, "COUPON_INVALID"), [s, kept, sq, errOf(b)]];
  });

  // ── Requirement 7: cancellation ──
  await C("R7 Mug at stock 2: buying 2 leaves 0, cancelling leaves 2, cancelling again is 409 ORDER_ALREADY_CANCELLED", async () => {
    const [s1, b] = await checkout([["Mug", 2]], ctx.ta);
    ctx.mugOrder = g(b, "id");
    const s0 = await stock("Mug");
    const [s2] = await setStatus(ctx.mugOrder, "cancelled", ctx.ta);
    const s2stock = await stock("Mug");
    const [s3, b3] = await setStatus(ctx.mugOrder, "cancelled", ctx.ta);
    return [s1 === 201 && eq(s0, 0) && s2 === 200 && eq(s2stock, 2) && rejected(s3, b3, 409, "ORDER_ALREADY_CANCELLED") && eq(await stock("Mug"), 2),
      [s1, s0, s2, s2stock, s3, errOf(b3)]];
  });
  await C("R7 a cancelled order stays in the list with status cancelled", async () => {
    const [s, b] = await call(base, "GET", "/api/orders", null, ctx.ta ?? null);
    const o = Array.isArray(b) ? b.find((x) => sameId(g(x, "id"), ctx.mugOrder)) : null;
    return [s === 200 && g(o, "status") === "cancelled", [s, o]];
  });
  await C("R7 paid → cancelled is allowed; a shipped order is 409 ORDER_NOT_CANCELLABLE; shipped → paid is 409", async () => {
    const [, b1] = await checkout([["Book", 1]], ctx.ta);
    const [sp] = await setStatus(g(b1, "id"), "paid", ctx.ta);
    const [sc] = await setStatus(g(b1, "id"), "cancelled", ctx.ta);
    const [, b2] = await checkout([["Book", 1]], ctx.ta);
    await setStatus(g(b2, "id"), "paid", ctx.ta);
    const [ss] = await setStatus(g(b2, "id"), "shipped", ctx.ta);
    const [sx, bx] = await setStatus(g(b2, "id"), "cancelled", ctx.ta);
    const [sb] = await setStatus(g(b2, "id"), "paid", ctx.ta);
    return [sp === 200 && sc === 200 && ss === 200 && rejected(sx, bx, 409, "ORDER_NOT_CANCELLABLE") && sb === 409, [sp, sc, ss, sx, errOf(bx), sb]];
  });
  await C("R7 cancelling another user's order: 404", async () => {
    const [, b] = await checkout([["Book", 1]], ctx.ta);
    ctx.pendingOrder = g(b, "id");
    const [s] = await setStatus(ctx.pendingOrder, "cancelled", ctx.tb);
    return [s === 404, s];
  });
  await C("R2 the cancellation of an order is audited", async () => {
    const [s, b] = await audit("order", ctx.mugOrder, ctx.tad);
    return [s === 200 && Array.isArray(b) && b.some((e) => g(g(e, "after"), "status") === "cancelled"), [s, Array.isArray(b) ? b.map((e) => g(e, "action")) : b]];
  });

  // ── Requirement 5: auditor ──
  await C("R5 the auditor sees the orders of every user; a user only their own", async () => {
    const [s, b] = await call(base, "GET", "/api/orders", null, ctx.tau ?? null);
    const [, mine] = await call(base, "GET", "/api/orders", null, ctx.tb ?? null);
    const ids = Array.isArray(b) ? b.map((o) => str(g(o, "id"))) : [];
    return [s === 200 && [ctx.mugOrder, ctx.pendingOrder].every((x) => ids.includes(str(x))) && eq(mine, []), [s, ids.length, mine]];
  });
  await C("R5 the auditor cannot write: 403 on checkout with a coupon, status change, cancellation and coupon creation", async () => {
    const [s1] = await checkout([["Book", 1]], ctx.tau, code("PCT"));
    const [s2] = await setStatus(ctx.pendingOrder, "paid", ctx.tau);
    const [s3] = await setStatus(ctx.pendingOrder, "cancelled", ctx.tau);
    const [s4] = await call(base, "POST", "/api/coupons", newCoupon("AUD", "percent", 5), ctx.tau ?? null);
    return [[s1, s2, s3, s4].every((s) => s === 403), [s1, s2, s3, s4]];
  });
  await C("R5 reading has no side effects (catalog, orders and audit unchanged by reads)", async () => {
    const snap = async () => {
      const [s1, l] = await list("?includeDeleted=true", ctx.tau), [s2, o] = await call(base, "GET", "/api/orders", null, ctx.tau), [s3, h] = await audit("product", ctx.lamp, ctx.tau);
      return { read: [s1, s2, s3].every((s) => s === 200), data: [view(l), o, h] };
    };
    const a = await snap();
    await list(); await list("?source=replica"); await coupons(ctx.tau); await quote([["Book", 2]], code("PCT"));
    const b = await snap();
    return [a.read && b.read && eq(a.data, b.data), { reads_ok: [a.read, b.read], unchanged: eq(a.data, b.data) }];
  });

  // ── Requirement 9: purchase limits ──
  await C("R9 21 units in one order: quote and checkout 422 MAX_UNITS_PER_ORDER, stock untouched", async () => {
    const spec = [["Book", 11], ["T-shirt", 10]], before = await stock("Book");
    const [s1, b1] = await quote(spec);
    const [s2, b2] = await checkout(spec, ctx.tb);
    return [rejected(s1, b1, 422, "MAX_UNITS_PER_ORDER") && rejected(s2, b2, 422, "MAX_UNITS_PER_ORDER") && eq(await stock("Book"), before), [s1, errOf(b1), s2, errOf(b2)]];
  });
  await C("R9 12 units of a product per user in 24 h: after 8, 5 more is 409 PRODUCT_LIMIT_24H and 4 more is 201", async () => {
    const t = await login(base, user("Carl"));
    const [s1] = await checkout([["Book", 8]], t);
    const [s2, b2] = await checkout([["Book", 5]], t);
    const [s3] = await checkout([["Book", 4]], t);
    return [s1 === 201 && rejected(s2, b2, 409, "PRODUCT_LIMIT_24H") && s3 === 201, [s1, s2, errOf(b2), s3]];
  });
  await C("R9 cancelled orders do not count: after 8 and cancelling them, 12 more is 201", async () => {
    const t = await login(base, user("Dana"));
    const [s1, b1] = await checkout([["Book", 8]], t);
    const [s2] = await setStatus(g(b1, "id"), "cancelled", t);
    const [s3, b3] = await checkout([["Book", 12]], t);
    return [s1 === 201 && s2 === 200 && s3 === 201, [s1, s2, s3, errOf(b3)]];
  });
  return { ...summary(base, results, "ecommerce"), suite: "r2" };
}

export const R2_SUITES = { ecommerce: runEcommerceR2 };
