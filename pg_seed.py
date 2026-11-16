#!/usr/bin/env python3
"""
pg_seed.py — Common data for analyzing the data model on a real PostgreSQL database.

After the acceptance gate (which leaves a few rows per table) it creates, using only the HTTP API from the requirements,
25 users with 1 to 3 purchases each, so the tables and indexes of the real database hold comparable data. It is the SAME script
for all the apps of a domain, so the results are comparable. Identifiers are opaque (integers or UUIDs).
  ecommerce  1 to 3 orders per user with 1 to 3 lines each (cycling through the catalog)
  cinema     1 to 3 purchases per user with 1 or 2 seats each (cycling through the screenings; seats are locked, then bought)

Usage: python pg_seed.py --base http://127.0.0.1:4000 [--domain cinema] [--users 25] [--output seed.json]
Standard library only. Reuses `call` and `login` from acceptance_check.py.
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_check import call, login  # noqa: E402


def new_user(i, stamp):
    return {"name": f"User {i}", "email": f"seed{i}_{stamp}@test.com", "password": "Passw0rd!x"}


def seed_ecommerce(base, users, stamp):
    s, prods = call(base, "GET", "/api/products")
    if s != 200 or not isinstance(prods, list):
        return {"error": f"GET /api/products returned {s}"}
    ids = [p.get("id") for p in prods if (p.get("stock") or 0) > 1]  # no sold-out items: a 409 would void the whole order
    if not ids:
        return {"error": "no products in stock"}
    res = {"users": 0, "orders": 0, "order_queries": 0, "errors": 0}
    for i in range(users):
        tok = login(base, new_user(i, stamp))
        if not tok:
            res["errors"] += 1; continue
        res["users"] += 1
        # 1 to 3 orders with 1 to 3 lines (cycling through the catalog): variety of array sizes
        for k in range(1 + i % 3):
            items = [{"productId": ids[(i + k + j) % len(ids)], "quantity": 1} for j in range(1 + (i + k) % 3)]
            items = list({x["productId"]: x for x in items}.values())
            s, _ = call(base, "POST", "/api/checkout", {"items": items}, tok)
            res["orders"] += s == 201  # a 409 for sold-out stock is expected; it is not an error
        s, _ = call(base, "GET", "/api/orders", token=tok)
        res["order_queries"] += s == 200
    return res


def seed_cinema(base, users, stamp):
    s, sts = call(base, "GET", "/api/showtimes")
    if s != 200 or not isinstance(sts, list) or not sts:
        return {"error": f"GET /api/showtimes returned {s}"}
    free = {}  # showtime id -> seat ids still available, in seat-map order
    for st in sts:
        s, seats = call(base, "GET", f"/api/showtimes/{st.get('id')}/seats")
        free[st.get("id")] = [x.get("id") for x in seats if x.get("status") == "available"] if s == 200 and isinstance(seats, list) else []
    order = list(free)
    res = {"users": 0, "orders": 0, "order_queries": 0, "errors": 0}
    for i in range(users):
        tok = login(base, new_user(i, stamp))
        if not tok:
            res["errors"] += 1; continue
        res["users"] += 1
        for k in range(1 + i % 3):
            st = order[(i + k) % len(order)]
            n = 1 + (i + k) % 2
            if len(free[st]) < n:
                continue  # the screening is sold out: fewer purchases, not an error
            seat_ids, free[st] = free[st][:n], free[st][n:]
            call(base, "POST", f"/api/showtimes/{st}/lock", {"seatIds": seat_ids}, tok)  # some apps only sell locked seats
            s, _ = call(base, "POST", "/api/checkout", {"showtimeId": st, "seatIds": seat_ids}, tok)
            res["orders"] += s == 201
        s, _ = call(base, "GET", "/api/orders", token=tok)
        res["order_queries"] += s == 200
    return res


SEEDS = {"ecommerce": seed_ecommerce, "cinema": seed_cinema}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--domain", default="ecommerce", choices=sorted(SEEDS))
    ap.add_argument("--users", type=int, default=25)
    ap.add_argument("--output", help="write the summary to this JSON file")
    a = ap.parse_args()
    res = SEEDS[a.domain](a.base, a.users, str(int(time.time() * 1000)))
    print(json.dumps(res))
    if a.output:
        Path(a.output).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 1 if "error" in res else 0


if __name__ == "__main__":
    sys.exit(main())
