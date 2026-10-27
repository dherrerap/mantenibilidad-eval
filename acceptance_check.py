#!/usr/bin/env python3
"""
acceptance_check.py — Functional gate: verifies, against the running API, the behaviors of
requirements-ecommerce.md (discount, stock, statuses, auth) and the contract of its minimum HTTP interface:
  - monetary values (price, unitPrice, lineTotal, total) are JSON numbers, not strings;
  - identifiers (id, productId) are integers or UUIDs and are treated as opaque values (never assumed to be an ObjectId).
Equivalent to the "pass rate" of Yuen et al. (2025): before comparing maintainability
we need to know whether the apps do the same thing.

Usage: python3 acceptance_check.py --base http://localhost:4000 --out acceptance.json
Requires a FRESHLY created database (the cases depend on the initial stock).
run_experiment.py starts PostgreSQL from the app's own docker-compose.yml and the backend before calling this script.
Standard library only.
"""
import argparse, json, re, time, urllib.request, urllib.error

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


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


def is_number(x):
    """A JSON number (int or float). A string such as "10.00" is NOT, and neither is a boolean."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_opaque_id(x):
    """An integer or a UUID string. A 24-hex ObjectId (or any other string) is not one of the identifiers the requirements allow."""
    return (isinstance(x, int) and not isinstance(x, bool)) or (isinstance(x, str) and bool(UUID_RE.match(x)))


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
        return (products().get(name) or {}).get("id")  # opaque: passed back exactly as received

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

    @case("catalog: fields id, name, price, description, imageUrl, stock")
    def _():
        b = list(products().values())
        want = {"id", "name", "price", "description", "imageUrl", "stock"}
        return bool(b) and all(want <= set(p) for p in b), sorted(want - set(b[0])) if b else "empty catalog"

    @case("catalog: ids are integers or UUIDs and prices are JSON numbers")
    def _():
        b = list(products().values())
        bad_ids = [p.get("id") for p in b if not is_opaque_id(p.get("id"))]
        bad_prices = [p.get("price") for p in b if not is_number(p.get("price"))]
        return bool(b) and not bad_ids and not bad_prices, {"ids_not_integer_or_uuid": bad_ids[:3], "prices_not_numbers": bad_prices[:3]}

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

    @case("cart/quote: lines carry numeric unitPrice and lineTotal (3 T-shirt = 10 x 3 -10% = 27)")
    def _():
        s, b = quote([("T-shirt", 3)])
        lines = b.get("lines") if isinstance(b, dict) else None
        ln = lines[0] if isinstance(lines, list) and lines else {}
        ok = (s == 200 and is_number(b.get("total")) and is_number(ln.get("unitPrice")) and is_number(ln.get("lineTotal"))
              and num(ln.get("unitPrice")) == 10.0 and num(ln.get("lineTotal")) == 27.0 and ln.get("quantity") == 3 and ln.get("productId") == pid("T-shirt"))
        return ok, (s, ln, b.get("total") if isinstance(b, dict) else b)

    @case("checkout without session: 401")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Book"), "quantity": 1}]}); return s == 401, s

    @case("checkout 3 T-shirt: 201, pending, total 27.00")
    def _():
        s, b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("T-shirt"), "quantity": 3}]}, ctx.get("ta"))
        ctx["order1"] = (b or {}).get("id") if isinstance(b, dict) else None
        return s == 201 and b.get("status") == "pending" and num(b.get("total")) == 27.0, (s, b)

    @case("checkout: id is an integer or UUID and total is a JSON number")
    def _():
        s, b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Book"), "quantity": 1}]}, ctx.get("ta"))
        ctx["order_book"] = b.get("id") if isinstance(b, dict) else None
        return s == 201 and isinstance(b, dict) and is_opaque_id(b.get("id")) and is_number(b.get("total")) and num(b.get("total")) == 20.0, (s, b)

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
        ids = [o.get("id") for o in b] if isinstance(b, list) else []
        return s == 200 and ctx.get("order1") in ids, (s, len(ids))

    @case("orders: each order has id, status and a numeric total")
    def _():
        s, b = call(base, "GET", "/api/orders", token=ctx.get("ta"))
        bad = [o for o in b if not (is_opaque_id(o.get("id")) and o.get("status") in ("pending", "paid", "shipped") and is_number(o.get("total")))] if isinstance(b, list) else None
        return s == 200 and bad == [] and len(b) > 0, (s, bad[:2] if bad else bad)

    @case("protected routes without a session: 401")
    def _():
        s1, _b = call(base, "GET", "/api/orders")
        s2, _b = call(base, "PATCH", f"/api/orders/{ctx.get('order1')}/status", {"status": "paid"})
        return s1 == 401 and s2 == 401, (s1, s2)

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
