#!/usr/bin/env python3
"""
acceptance_check.py — Functional gate: verifies, against the running API, the behaviors of the domain requirements and the
contract of their minimum HTTP interface:
  ecommerce  requirements-ecommerce.md: volume discount, stock, order statuses, auth
  cinema     requirements-cinema.md: seat locking, dynamic price per screening, availability, auth
In both, monetary values are JSON numbers (not strings) and identifiers are integers or UUIDs treated as opaque values.
The suites cover the ORIGINAL requirements only: an app that already implements r2-additional-requirements.md changes some of
these rules (prices, shipping, roles), so the gate must run on the state after phase initial (run_experiment.py does that).
Equivalent to the "pass rate" of Yuen et al. (2025): before comparing maintainability
we need to know whether the apps do the same thing.

Usage: python3 acceptance_check.py --base http://localhost:4000 [--domain cinema] --out acceptance.json [--app <app folder>]
Requires a FRESHLY created database (the cases depend on the initial stock).
run_experiment.py (PostgreSQL from the app's own docker-compose.yml) and pg_analysis.py (--postgres) start the backend before
calling this script. With --app, the suite also goes through a Prism proxy that checks every response against the app's OpenAPI
contract and writes contract_conformance.json next to --out (contract_conformance.py); the acceptance result is the same.
Standard library only (Prism comes from this folder's node_modules).
"""
import argparse, datetime, json, re, time, urllib.request, urllib.error

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Calls made while CALLS is a list (acceptance through the Prism proxy: contract_conformance.py), with the contract violations that
# Prism returns in the `sl-violations` header. None: nothing is recorded.
CALLS = None


def record(method, path, status, headers):
    if CALLS is None:
        return
    try:
        v = json.loads((headers or {}).get("sl-violations") or "[]")
    except ValueError:
        v = []
    CALLS.append({"method": method, "path": path.split("?")[0], "status": status, "violations": v if isinstance(v, list) else []})


def call(base, method, path, body=None, token=None):
    req = urllib.request.Request(base + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            status, raw = r.status, r.read().decode("utf-8", "replace")
            record(method, path, status, r.headers)
    except urllib.error.HTTPError as e:
        record(method, path, e.code, e.headers)
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, None
    except Exception as e:  # connection refused, timeout, etc.
        return 0, str(e)
    try:  # a body that is not JSON keeps its real status (it used to be reported as a connection error, status 0)
        return status, json.loads(raw) if raw.strip() else None
    except ValueError:
        return status, raw


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


def case_recorder(results):
    """Decorator factory: `@case(name)` runs the function at once and records (ok, detail); an exception is a failed case."""
    def case(name):
        def deco(fn):
            try:
                ok, detail = fn()
            except Exception as e:  # noqa
                ok, detail = False, f"exception: {e!r}"
            results.append({"case": name, "ok": bool(ok), "detail": detail})
            return fn
        return deco
    return case


def test_users():
    stamp = str(int(time.time() * 1000))
    return ({"name": "Ann", "email": f"ann{stamp}@test.com", "password": "Passw0rd!x"},
            {"name": "Bob", "email": f"bob{stamp}@test.com", "password": "Passw0rd!x"})


def auth_cases(base, case, user, ctx):
    """Registration and login cases shared by every domain; leaves user's token in ctx['ta']."""
    @case("register: 201")
    def _():
        s, _b = call(base, "POST", "/api/auth/register", user); return s == 201, s

    @case("duplicate register: 409")
    def _():
        s, _b = call(base, "POST", "/api/auth/register", user); return s == 409, s

    @case("login: 200 with token")
    def _():
        s, b = call(base, "POST", "/api/auth/login", {"email": user["email"], "password": user["password"]})
        ctx["ta"] = b.get("token") if isinstance(b, dict) else None
        return s == 200 and bool(ctx["ta"]), s

    @case("login with wrong password: 401")
    def _():
        s, _b = call(base, "POST", "/api/auth/login", {"email": user["email"], "password": "x"}); return s == 401, s


def login(base, user):
    """Registers (if needed) and logs in `user`; returns the token or None."""
    call(base, "POST", "/api/auth/register", user)
    _s, b = call(base, "POST", "/api/auth/login", {"email": user["email"], "password": user["password"]})
    return b.get("token") if isinstance(b, dict) else None


def summary(base, results, domain):
    passed = sum(r["ok"] for r in results)
    return {"base": base, "domain": domain, "total": len(results), "passed": passed,
            "acceptance_pct": round(100.0 * passed / len(results), 1) if results else 0.0, "cases": results}


def run(base, domain="ecommerce"):
    """Runs the suite of `domain` (ecommerce, cinema) against `base`."""
    if domain not in SUITES:
        raise ValueError(f"no acceptance suite for domain {domain!r} (available: {', '.join(sorted(SUITES))})")
    return SUITES[domain](base)


def run_ecommerce(base):
    results = []
    ctx = {}
    case = case_recorder(results)
    A, B = test_users()

    def products():
        s, b = call(base, "GET", "/api/products")
        return {p["name"]: p for p in b} if s == 200 and isinstance(b, list) else {}

    def pid(name):
        return (products().get(name) or {}).get("id")  # opaque: passed back exactly as received

    def stock(name):
        return (products().get(name) or {}).get("stock")

    auth_cases(base, case, A, ctx)

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

    return summary(base, results, "ecommerce")


# ───────────────────────── cinema (requirements-cinema.md) ─────────────────────────
CINEMA_TIMES = {"14:00": 6.0, "16:30": 6.0, "20:00": 9.0, "21:00": 9.0}  # seed screenings and their price (before / from 17:00)
CINEMA_SEATS = [f"{r}{n}" for r in "ABCD" for n in range(1, 6)]


def local_hm(starts_at):
    """'HH:MM' of an ISO 8601 date in the local time zone of this machine: the server's, since the gate runs next to the backend
    (the seed fixes the time of day in the server's time zone). A date without offset is taken as local."""
    dt = datetime.datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
    return dt.astimezone().strftime("%H:%M")


def run_cinema(base):
    results = []
    ctx = {}
    case = case_recorder(results)
    A, B = test_users()

    def showtimes():
        s, b = call(base, "GET", "/api/showtimes")
        return b if s == 200 and isinstance(b, list) else []

    def by_time():
        out = {}
        for st in showtimes():
            try:
                out.setdefault(local_hm(st.get("startsAt")), st)
            except (TypeError, ValueError):
                continue
        return out

    def seat_map(time_of_day):
        st = by_time().get(time_of_day) or {}
        s, b = call(base, "GET", f"/api/showtimes/{st.get('id')}/seats")
        return {x.get("label"): x for x in b} if s == 200 and isinstance(b, list) else {}

    def sid(time_of_day):
        return (by_time().get(time_of_day) or {}).get("id")  # opaque: passed back exactly as received

    def seat_ids(time_of_day, labels):
        seats = seat_map(time_of_day)
        return [(seats.get(lb) or {}).get("id") for lb in labels]

    auth_cases(base, case, A, ctx)
    ctx["tb"] = login(base, B)

    @case("movies: fields id, title, description, imageUrl and the 2 seed movies")
    def _():
        s, b = call(base, "GET", "/api/movies")
        want = {"id", "title", "description", "imageUrl"}
        ok = s == 200 and isinstance(b, list) and all(want <= set(m) for m in b) and {"Movie One", "Movie Two"} <= {m.get("title") for m in b}
        return ok, (s, [m.get("title") for m in b] if isinstance(b, list) else b)

    @case("movies: ids are integers or UUIDs")
    def _():
        s, b = call(base, "GET", "/api/movies")
        bad = [m.get("id") for m in b if not is_opaque_id(m.get("id"))] if isinstance(b, list) else None
        return s == 200 and bad == [] and len(b) > 0, bad

    @case("showtimes: fields id, movieId, startsAt, room, price and the 4 seed screenings (14:00, 16:30, 20:00, 21:00)")
    def _():
        sts = showtimes()
        want = {"id", "movieId", "startsAt", "room", "price"}
        return all(want <= set(x) for x in sts) and set(CINEMA_TIMES) <= set(by_time()), sorted(by_time())

    @case("showtimes: price 6.00 before 17:00 and 9.00 from 17:00, as JSON numbers")
    def _():
        bt = by_time()
        got = {t: (bt.get(t) or {}).get("price") for t in CINEMA_TIMES}
        return all(is_number(v) and num(v) == CINEMA_TIMES[t] for t, v in got.items()), got

    @case("seat map: 20 seats A1…D5, all available, with integer or UUID ids")
    def _():
        seats = seat_map("14:00")
        ok = (sorted(seats) == sorted(CINEMA_SEATS) and all(x.get("status") == "available" for x in seats.values())
              and all(is_opaque_id(x.get("id")) for x in seats.values()))
        return ok, {"labels": len(seats), "statuses": sorted({str(x.get("status")) for x in seats.values()})}

    for label, tod, n, exp_unit, exp_total in [("2 seats at 14:00 = 12.00", "14:00", 2, 6.0, 12.0),
                                               ("2 seats at 20:00 = 18.00", "20:00", 2, 9.0, 18.0),
                                               ("3 seats at 16:30 = 18.00", "16:30", 3, 6.0, 18.0)]:
        @case("quote: " + label + " (numeric unitPrice and total)")
        def _(tod=tod, n=n, exp_unit=exp_unit, exp_total=exp_total):
            s, b = call(base, "POST", f"/api/showtimes/{sid(tod)}/quote", {"seatIds": seat_ids(tod, CINEMA_SEATS[-n:])})
            ok = (s == 200 and isinstance(b, dict) and is_number(b.get("unitPrice")) and is_number(b.get("total"))
                  and num(b.get("unitPrice")) == exp_unit and num(b.get("total")) == exp_total and b.get("seats") == n)
            return ok, (s, b)

    @case("lock without session: 401")
    def _():
        s, _b = call(base, "POST", f"/api/showtimes/{sid('20:00')}/lock", {"seatIds": seat_ids("20:00", ["A1"])})
        return s == 401, s

    @case("lock A1 and A2 (20:00): 200 with seatIds and expiresAt")
    def _():
        ids = seat_ids("20:00", ["A1", "A2"])
        s, b = call(base, "POST", f"/api/showtimes/{sid('20:00')}/lock", {"seatIds": ids}, ctx.get("ta"))
        ok = s == 200 and isinstance(b, dict) and bool(b.get("expiresAt")) and {str(x) for x in b.get("seatIds") or []} == {str(x) for x in ids}
        return ok, (s, b)

    @case("lock: another user cannot lock a seat that is locked (409)")
    def _():
        s, _b = call(base, "POST", f"/api/showtimes/{sid('20:00')}/lock", {"seatIds": seat_ids("20:00", ["A1"])}, ctx.get("tb"))
        return s == 409, s

    @case("seat map: a locked seat is shown as locked")
    def _():
        st = (seat_map("20:00").get("A1") or {}).get("status")
        return st == "locked", st

    @case("checkout without session: 401")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"showtimeId": sid("20:00"), "seatIds": seat_ids("20:00", ["A1"])})
        return s == 401, s

    @case("checkout A1 + A2 (20:00): 201 with id, showtimeId, seatIds and total 18.00")
    def _():
        ids = seat_ids("20:00", ["A1", "A2"])
        s, b = call(base, "POST", "/api/checkout", {"showtimeId": sid("20:00"), "seatIds": ids}, ctx.get("ta"))
        ctx["order1"] = b.get("id") if isinstance(b, dict) else None
        ok = (s == 201 and isinstance(b, dict) and str(b.get("showtimeId")) == str(sid("20:00")) and num(b.get("total")) == 18.0
              and {str(x) for x in b.get("seatIds") or []} == {str(x) for x in ids})
        return ok, (s, b)

    @case("checkout: id is an integer or UUID and total is a JSON number")
    def _():
        s, b = call(base, "GET", "/api/orders", token=ctx.get("ta"))
        o = next((x for x in b if x.get("id") == ctx.get("order1")), None) if isinstance(b, list) else None
        return bool(o) and is_opaque_id(ctx.get("order1")) and is_number(o.get("total")), (s, o)

    @case("seat map: the purchased seats are sold")
    def _():
        seats = seat_map("20:00")
        got = {lb: (seats.get(lb) or {}).get("status") for lb in ("A1", "A2")}
        return all(v == "sold" for v in got.values()), got

    @case("checkout with a sold seat: 409 and the other seat stays available")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"showtimeId": sid("20:00"), "seatIds": seat_ids("20:00", ["A2", "A3"])}, ctx.get("tb"))
        a3 = (seat_map("20:00").get("A3") or {}).get("status")
        return s == 409 and a3 == "available", (s, a3)

    @case("seats sold in one screening do not affect another (A1 at 21:00 is available)")
    def _():
        st = (seat_map("21:00").get("A1") or {}).get("status")
        return st == "available", st

    @case("orders: the user sees their purchase with showtimeId, seatIds and a numeric total")
    def _():
        s, b = call(base, "GET", "/api/orders", token=ctx.get("ta"))
        o = next((x for x in b if x.get("id") == ctx.get("order1")), None) if isinstance(b, list) else None
        ok = s == 200 and bool(o) and {"id", "showtimeId", "seatIds", "total"} <= set(o) and is_number(o.get("total"))
        return ok, (s, o)

    @case("protected routes without a session: 401")
    def _():
        s, _b = call(base, "GET", "/api/orders"); return s == 401, s

    @case("isolation: another user does not see other people's purchases")
    def _():
        s, orders = call(base, "GET", "/api/orders", token=ctx.get("tb"))
        return s == 200 and orders == [], (s, orders)

    return summary(base, results, "cinema")


SUITES = {"ecommerce": run_ecommerce, "cinema": run_cinema}


def run_with_contract(base, domain, app):
    """The suite through a Prism proxy that validates every response against the app's OpenAPI contract (contract_conformance.py).
    The acceptance result is the same as without the proxy; `_conformance` carries the conformance, or why it was not measured
    (no contract, Prism not installed, a contract Prism cannot load). A proxy failure never fails the gate: the suite then runs direct."""
    global CALLS
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import contract_conformance as cc
    from evaluator.collectors.contract import find_contracts
    found = find_contracts(Path(app))
    if not found:
        return {**run(base, domain), "_conformance": cc.without_prism("the app has no OpenAPI contract")}
    contract = Path(app) / found[0]
    if not cc.available():
        return {**run(base, domain), "_conformance": cc.without_prism("Prism is not installed (npm install)", found[0])}
    proxy = cc.Proxy(contract, base)
    try:
        proxied = proxy.__enter__()
    except Exception as e:  # Prism did not start or could not load the contract: the suite runs direct (the database is still fresh)
        proxy.__exit__(None, None, None)
        return {**run(base, domain), "_conformance": cc.without_prism(str(e)[:300], found[0])}
    CALLS = []
    try:
        res = run(proxied, domain)
        res["base"] = base
        return {**res, "_conformance": cc.summarize(CALLS, found[0], proxy.base_path)}
    finally:
        CALLS = None
        proxy.__exit__(None, None, None)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:4000"); ap.add_argument("--out", default="acceptance.json")
    ap.add_argument("--domain", default="ecommerce", choices=sorted(SUITES))
    ap.add_argument("--app", help="app folder: if it has an OpenAPI contract, the suite also runs through a Prism proxy that checks every "
                                  "response against it, written to contract_conformance.json next to --out (informational)")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    conformance = None
    if a.app:
        res = run_with_contract(base, a.domain, a.app)
        conformance = res.pop("_conformance")
    else:
        res = run(base, a.domain)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False))
    if conformance is not None:
        import os
        import contract_conformance as cc
        with open(os.path.join(os.path.dirname(os.path.abspath(a.out)), cc.RESULT_FILE), "w", encoding="utf-8") as f:
            f.write(json.dumps(conformance, indent=1, ensure_ascii=False))
        print(f"Contract conformance: {conformance.get('conformance_pct', 'n/a')}%" if conformance.get("ok") else
              f"Contract conformance not measured: {conformance.get('error')}")
    for r in res["cases"]:
        print(("✔" if r["ok"] else "✘"), r["case"], "" if r["ok"] else f"→ {r['detail']}")
    print(f"\nAcceptance: {res['passed']}/{res['total']} = {res['acceptance_pct']}%")
