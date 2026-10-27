#!/usr/bin/env python3
"""
seed_api.py — Common data for analyzing the data model on a real database.

After the acceptance gate (which leaves 2-3 documents per collection) it creates, using only the API from the requirements,
enough users and orders for the observed schema, document size and array growth to mean something.
It is the SAME script for all apps, so the results are comparable.

Usage: python seed_api.py --base http://127.0.0.1:4000 [--users 25]
Standard library only. Reuses `call` from acceptance_check.py.
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_check import call  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--users", type=int, default=25)
    ap.add_argument("--output", help="write the summary to this JSON file")
    a = ap.parse_args()
    s, prods = call(a.base, "GET", "/api/products")
    if s != 200 or not isinstance(prods, list):
        print(json.dumps({"error": f"GET /api/products returned {s}"})); return 1
    ids = [p.get("id", p.get("_id")) for p in prods if (p.get("stock") or 0) > 1]  # no sold-out items: a 409 would void the whole order
    if not ids:
        print(json.dumps({"error": "no products in stock"})); return 1
    stamp = str(int(time.time() * 1000))
    res = {"users": 0, "orders": 0, "order_queries": 0, "errors": 0}
    for i in range(a.users):
        u = {"name": f"User {i}", "email": f"seed{i}_{stamp}@test.com", "password": "Passw0rd!x"}
        s, _ = call(a.base, "POST", "/api/auth/register", u)
        if s != 201:
            res["errors"] += 1; continue
        res["users"] += 1
        s, b = call(a.base, "POST", "/api/auth/login", {"email": u["email"], "password": u["password"]})
        tok = b.get("token") if isinstance(b, dict) else None
        if not tok:
            res["errors"] += 1; continue
        # 1 to 3 orders with 1 to 3 lines (cycling through the catalog): variety of array sizes
        for k in range(1 + i % 3):
            items = [{"productId": ids[(i + k + j) % len(ids)], "quantity": 1} for j in range(1 + (i + k) % 3)]
            items = list({x["productId"]: x for x in items}.values())
            s, _ = call(a.base, "POST", "/api/checkout", {"items": items}, tok)
            res["orders"] += s == 201  # a 409 for sold-out stock is expected; it is not an error
        s, _ = call(a.base, "GET", "/api/orders", token=tok)
        res["order_queries"] += s == 200
    print(json.dumps(res))
    if a.output:
        Path(a.output).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
