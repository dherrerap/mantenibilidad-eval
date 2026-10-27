#!/usr/bin/env python3
"""
acceptance_check.py — Functional gate: verifies, against the running API, the behaviors of
requirements-ecommerce.md (discount, stock, statuses, auth).
Equivalent to the "pass rate" of Yuen et al. (2025): before comparing maintainability
we need to know whether the apps do the same thing.

Usage: python3 acceptance_check.py --base http://localhost:4000 --out acceptance.json
Requires a FRESHLY created database (the cases depend on the initial stock).
Standard library only.
"""
import argparse, json, time, urllib.request, urllib.error


def call(base, method, path, body=None, token=None):
    req = urllib.request.Request(base + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode() or "null"
            return r.status, json.loads(raw) if raw.strip()[:1] in "[{\"0123456789tfn-" else raw
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, None
    except Exception as e:  # connection refused, timeout, etc.
        return 0, str(e)


def num(x):
    try:
        return round(float(x), 2)
    except Exception:
        return None


def run(base):
    results = []
    ctx = {}

    def case(name):
        def deco(fn):
            try:
                ok, detail = fn()
            except Exception as e:  # noqa
                ok, detail = False, f"exception: {e!r}"
            results.append({"case": name, "ok": bool(ok), "detail": detail})
            return fn
        return deco

    stamp = str(int(time.time() * 1000))
    A = {"name": "Ann", "email": f"ann{stamp}@test.com", "password": "Passw0rd!x"}
    B = {"name": "Bob", "email": f"bob{stamp}@test.com", "password": "Passw0rd!x"}

    def products():
        s, b = call(base, "GET", "/api/products")
        return {p["name"]: p for p in b} if s == 200 and isinstance(b, list) else {}

    def pid(name):
        p = products().get(name) or {}
        return p.get("id", p.get("_id"))

    def stock(name):
        return (products().get(name) or {}).get("stock")

    @case("register: 201")
    def _():
        s, _b = call(base, "POST", "/api/auth/register", A); return s == 201, s

    @case("duplicate register: 409")
    def _():
        s, _b = call(base, "POST", "/api/auth/register", A); return s == 409, s

    @case("login: 200 with token")
    def _():
        s, b = call(base, "POST", "/api/auth/login", {"email": A["email"], "password": A["password"]})
        ctx["ta"] = b.get("token") if isinstance(b, dict) else None
        return s == 200 and bool(ctx["ta"]), s

    @case("login with wrong password: 401")
    def _():
        s, _b = call(base, "POST", "/api/auth/login", {"email": A["email"], "password": "x"}); return s == 401, s

    @case("catalog with 3 seed products and fields")
    def _():
        p = products(); need = {"T-shirt": (10, 20), "Mug": (5, 2), "Book": (20, 50)}
        ok = all(k in p and num(p[k].get("price")) == v[0] and p[k].get("stock") == v[1] for k, v in need.items())
        return ok, {k: (p.get(k) or {}).get("stock") for k in need}

    def quote(items):
        s, b = call(base, "POST", "/api/cart/quote", {"items": [{"productId": pid(n), "quantity": q} for n, q in items]})
        return s, b

    for label, items, exp_total in [("2 T-shirt = 20.00", [("T-shirt", 2)], 20.0),
                                    ("3 T-shirt = 27.00 (discount)", [("T-shirt", 3)], 27.0),
                                    ("5 T-shirt = 45.00 (discount)", [("T-shirt", 5)], 45.0),
                                    ("3 T-shirt + 1 Book = 47.00", [("T-shirt", 3), ("Book", 1)], 47.0)]:
        @case("cart/quote: " + label)
        def _(items=items, exp_total=exp_total):
            s, b = quote(items)
            return s == 200 and isinstance(b, dict) and num(b.get("total")) == exp_total, (s, b.get("total") if isinstance(b, dict) else b)

    @case("checkout without session: 401")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Book"), "quantity": 1}]}); return s == 401, s

    @case("checkout 3 T-shirt: 201, pending, total 27.00")
    def _():
        s, b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("T-shirt"), "quantity": 3}]}, ctx.get("ta"))
        ctx["order1"] = (b or {}).get("id") if isinstance(b, dict) else None
        return s == 201 and b.get("status") == "pending" and num(b.get("total")) == 27.0, (s, b)

    @case("checkout deducts stock (T-shirt 20 → 17)")
    def _():
        return stock("T-shirt") == 17, stock("T-shirt")

    @case("checkout with insufficient stock: 409 and stock untouched")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Mug"), "quantity": 3}]}, ctx.get("ta"))
        return s == 409 and stock("Mug") == 2, (s, stock("Mug"))

    @case("atomic checkout: if one product falls short none is deducted")
    def _():
        before = stock("Book")
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Book"), "quantity": 1}, {"productId": pid("Mug"), "quantity": 3}]}, ctx.get("ta"))
        return s == 409 and stock("Book") == before, (s, before, stock("Book"))

    @case("checkout 2 Mug: 201 and stock 0; then 1 Mug: 409")
    def _():
        s1, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Mug"), "quantity": 2}]}, ctx.get("ta"))
        s2, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Mug"), "quantity": 1}]}, ctx.get("ta"))
        return s1 == 201 and stock("Mug") == 0 and s2 == 409, (s1, stock("Mug"), s2)

    @case("orders: the user sees their order with its status")
    def _():
        s, b = call(base, "GET", "/api/orders", token=ctx.get("ta"))
        ids = [o.get("id", o.get("_id")) for o in b] if isinstance(b, list) else []
        return s == 200 and ctx.get("order1") in ids, (s, len(ids))

    @case("statuses: pending→paid→shipped in order")
    def _():
        o = ctx.get("order1")
        s1, _b = call(base, "PATCH", f"/api/orders/{o}/status", {"status": "paid"}, ctx.get("ta"))
        s2, _b = call(base, "PATCH", f"/api/orders/{o}/status", {"status": "shipped"}, ctx.get("ta"))
        return s1 == 200 and s2 == 200, (s1, s2)

    @case("statuses: cannot go back or skip")
    def _():
        o = ctx.get("order1")
        back, _b = call(base, "PATCH", f"/api/orders/{o}/status", {"status": "pending"}, ctx.get("ta"))
        s, b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Book"), "quantity": 1}]}, ctx.get("ta"))
        o2 = b.get("id") if isinstance(b, dict) else None
        skip, _b = call(base, "PATCH", f"/api/orders/{o2}/status", {"status": "shipped"}, ctx.get("ta"))
        return back == 409 and skip == 409, (back, skip)

    @case("isolation: another user does not see other people's orders")
    def _():
        call(base, "POST", "/api/auth/register", B)
        s, b = call(base, "POST", "/api/auth/login", {"email": B["email"], "password": B["password"]})
        tb = b.get("token") if isinstance(b, dict) else None
        s, orders = call(base, "GET", "/api/orders", token=tb)
        return s == 200 and orders == [], (s, orders)

    passed = sum(r["ok"] for r in results)
    return {"base": base, "total": len(results), "passed": passed,
            "acceptance_pct": round(100.0 * passed / len(results), 1), "cases": results}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:4000"); ap.add_argument("--out", default="acceptance.json")
    a = ap.parse_args()
    res = run(a.base.rstrip("/"))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False))
    for r in res["cases"]:
        print(("✔" if r["ok"] else "✘"), r["case"], "" if r["ok"] else f"→ {r['detail']}")
    print(f"\nAcceptance: {res['passed']}/{res['total']} = {res['acceptance_pct']}%")
