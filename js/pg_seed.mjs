#!/usr/bin/env node
// pg_seed.mjs — Common data for the real-database analysis: through the HTTP API of the requirements, 25 users with 1 to 3 purchases
// each, the same for every app of a domain. Port of pg_seed.py.
//   node js/pg_seed.mjs --base http://127.0.0.1:4000 [--domain cinema] [--users 25] [--output seed.json]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dumps, dumpsAscii, get, isDict, or, str } from "./lib/py.mjs";
import { call, login } from "./acceptance_check.mjs";

const newUser = (i, stamp) => ({ name: `User ${i}`, email: `seed${i}_${stamp}@test.com`, password: "Passw0rd!x" });

async function seedEcommerce(base, users, stamp) {
  const [s, prods] = await call(base, "GET", "/api/products");
  if (s !== 200 || !Array.isArray(prods)) return { error: `GET /api/products returned ${s}` };
  const ids = prods.filter((p) => Number(or(get(p, "stock"), 0)) > 1).map((p) => get(p, "id"));  // no sold-out items: a 409 voids the order
  if (!ids.length) return { error: "no products in stock" };
  const res = { users: 0, orders: 0, order_queries: 0, errors: 0 };
  for (let i = 0; i < users; i++) {
    const tok = await login(base, newUser(i, stamp));
    if (!tok) { res.errors += 1; continue; }
    res.users += 1;
    for (let k = 0; k < 1 + (i % 3); k++) {  // 1 to 3 orders with 1 to 3 lines, cycling through the catalog
      const byId = new Map();
      for (let j = 0; j < 1 + ((i + k) % 3); j++) { const id = ids[(i + k + j) % ids.length]; byId.set(JSON.stringify(id), { productId: id, quantity: 1 }); }
      const [st] = await call(base, "POST", "/api/checkout", { items: [...byId.values()] }, tok);
      res.orders += st === 201 ? 1 : 0;  // a 409 for sold-out stock is expected; it is not an error
    }
    const [so] = await call(base, "GET", "/api/orders", null, tok);
    res.order_queries += so === 200 ? 1 : 0;
  }
  return res;
}

async function seedCinema(base, users, stamp) {
  const [s, sts] = await call(base, "GET", "/api/showtimes");
  if (s !== 200 || !Array.isArray(sts) || !sts.length) return { error: `GET /api/showtimes returned ${s}` };
  const free = new Map();  // showtime id -> seat ids still available, in seat-map order
  for (const st of sts) {
    const [ss, seats] = await call(base, "GET", `/api/showtimes/${str(get(st, "id"))}/seats`);
    free.set(get(st, "id"), ss === 200 && Array.isArray(seats) ? seats.filter((x) => get(x, "status") === "available").map((x) => get(x, "id")) : []);
  }
  const order = [...free.keys()];
  const res = { users: 0, orders: 0, order_queries: 0, errors: 0 };
  for (let i = 0; i < users; i++) {
    const tok = await login(base, newUser(i, stamp));
    if (!tok) { res.errors += 1; continue; }
    res.users += 1;
    for (let k = 0; k < 1 + (i % 3); k++) {
      const st = order[(i + k) % order.length], n = 1 + ((i + k) % 2);
      if (free.get(st).length < n) continue;  // the screening is sold out: fewer purchases, not an error
      const seatIds = free.get(st).slice(0, n);
      free.set(st, free.get(st).slice(n));
      await call(base, "POST", `/api/showtimes/${str(st)}/lock`, { seatIds }, tok);  // some apps only sell locked seats
      const [sc] = await call(base, "POST", "/api/checkout", { showtimeId: st, seatIds }, tok);
      res.orders += sc === 201 ? 1 : 0;
    }
    const [so] = await call(base, "GET", "/api/orders", null, tok);
    res.order_queries += so === 200 ? 1 : 0;
  }
  return res;
}

export const SEEDS = { ecommerce: seedEcommerce, cinema: seedCinema };

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), o = { domain: "ecommerce", users: "25" };
  for (let i = 0; i < args.length; i++) if (args[i].startsWith("--")) o[args[i].slice(2)] = args[++i];
  if (!o.base || !(o.domain in SEEDS)) { console.error("usage: node js/pg_seed.mjs --base URL [--domain ecommerce|cinema] [--users 25] [--output seed.json]"); process.exit(2); }
  const res = await SEEDS[o.domain](o.base, Number.parseInt(o.users, 10), String(Date.now()));
  console.log(dumps(res));
  if (o.output) fs.writeFileSync(o.output, dumpsAscii(res, 1), "utf8");
  process.exitCode = isDict(res) && "error" in res ? 1 : 0;
}
