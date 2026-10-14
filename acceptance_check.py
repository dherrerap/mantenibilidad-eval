#!/usr/bin/env python3
"""
acceptance_check.py — Compuerta funcional: verifica contra la API en ejecución los
comportamientos de requisitos-ecommerce.md (descuento, stock, estados, auth).
Equivale al "pass rate" de Yuen et al. (2025): antes de comparar mantenibilidad hay
que saber si las apps hacen lo mismo.

Uso: python3 acceptance_check.py --base http://localhost:4000 --out acceptance.json
Requiere una base de datos RECIÉN creada (los casos dependen del stock inicial).
Sólo biblioteca estándar.
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
    except Exception as e:  # conexión rechazada, timeout, etc.
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
                ok, detail = False, f"excepción: {e!r}"
            results.append({"caso": name, "ok": bool(ok), "detalle": detail})
            return fn
        return deco

    stamp = str(int(time.time() * 1000))
    A = {"name": "Ana", "email": f"ana{stamp}@test.com", "password": "Passw0rd!x"}
    B = {"name": "Beto", "email": f"beto{stamp}@test.com", "password": "Passw0rd!x"}

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

    @case("register duplicado: 409")
    def _():
        s, _b = call(base, "POST", "/api/auth/register", A); return s == 409, s

    @case("login: 200 con token")
    def _():
        s, b = call(base, "POST", "/api/auth/login", {"email": A["email"], "password": A["password"]})
        ctx["ta"] = b.get("token") if isinstance(b, dict) else None
        return s == 200 and bool(ctx["ta"]), s

    @case("login con clave errónea: 401")
    def _():
        s, _b = call(base, "POST", "/api/auth/login", {"email": A["email"], "password": "x"}); return s == 401, s

    @case("catálogo con 3 productos semilla y campos")
    def _():
        p = products(); need = {"Camiseta": (10, 20), "Taza": (5, 2), "Libro": (20, 50)}
        ok = all(k in p and num(p[k].get("price")) == v[0] and p[k].get("stock") == v[1] for k, v in need.items())
        return ok, {k: (p.get(k) or {}).get("stock") for k in need}

    def quote(items):
        s, b = call(base, "POST", "/api/cart/quote", {"items": [{"productId": pid(n), "quantity": q} for n, q in items]})
        return s, b

    for label, items, exp_total in [("2 Camiseta = 20.00", [("Camiseta", 2)], 20.0),
                                    ("3 Camiseta = 27.00 (descuento)", [("Camiseta", 3)], 27.0),
                                    ("5 Camiseta = 45.00 (descuento)", [("Camiseta", 5)], 45.0),
                                    ("3 Camiseta + 1 Libro = 47.00", [("Camiseta", 3), ("Libro", 1)], 47.0)]:
        @case("cart/quote: " + label)
        def _(items=items, exp_total=exp_total):
            s, b = quote(items)
            return s == 200 and isinstance(b, dict) and num(b.get("total")) == exp_total, (s, b.get("total") if isinstance(b, dict) else b)

    @case("checkout sin sesión: 401")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Libro"), "quantity": 1}]}); return s == 401, s

    @case("checkout 3 Camiseta: 201, pendiente, total 27.00")
    def _():
        s, b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Camiseta"), "quantity": 3}]}, ctx.get("ta"))
        ctx["order1"] = (b or {}).get("id") if isinstance(b, dict) else None
        return s == 201 and b.get("status") == "pendiente" and num(b.get("total")) == 27.0, (s, b)

    @case("checkout descuenta stock (Camiseta 20 → 17)")
    def _():
        return stock("Camiseta") == 17, stock("Camiseta")

    @case("checkout con stock insuficiente: 409 y stock intacto")
    def _():
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Taza"), "quantity": 3}]}, ctx.get("ta"))
        return s == 409 and stock("Taza") == 2, (s, stock("Taza"))

    @case("checkout atómico: si un producto no alcanza no se descuenta ninguno")
    def _():
        before = stock("Libro")
        s, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Libro"), "quantity": 1}, {"productId": pid("Taza"), "quantity": 3}]}, ctx.get("ta"))
        return s == 409 and stock("Libro") == before, (s, before, stock("Libro"))

    @case("checkout 2 Taza: 201 y stock 0; luego 1 Taza: 409")
    def _():
        s1, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Taza"), "quantity": 2}]}, ctx.get("ta"))
        s2, _b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Taza"), "quantity": 1}]}, ctx.get("ta"))
        return s1 == 201 and stock("Taza") == 0 and s2 == 409, (s1, stock("Taza"), s2)

    @case("orders: el usuario ve su pedido con estado")
    def _():
        s, b = call(base, "GET", "/api/orders", token=ctx.get("ta"))
        ids = [o.get("id", o.get("_id")) for o in b] if isinstance(b, list) else []
        return s == 200 and ctx.get("order1") in ids, (s, len(ids))

    @case("estados: pendiente→pagado→despachado en orden")
    def _():
        o = ctx.get("order1")
        s1, _b = call(base, "PATCH", f"/api/orders/{o}/status", {"status": "pagado"}, ctx.get("ta"))
        s2, _b = call(base, "PATCH", f"/api/orders/{o}/status", {"status": "despachado"}, ctx.get("ta"))
        return s1 == 200 and s2 == 200, (s1, s2)

    @case("estados: no se puede retroceder ni saltar")
    def _():
        o = ctx.get("order1")
        back, _b = call(base, "PATCH", f"/api/orders/{o}/status", {"status": "pendiente"}, ctx.get("ta"))
        s, b = call(base, "POST", "/api/checkout", {"items": [{"productId": pid("Libro"), "quantity": 1}]}, ctx.get("ta"))
        o2 = b.get("id") if isinstance(b, dict) else None
        skip, _b = call(base, "PATCH", f"/api/orders/{o2}/status", {"status": "despachado"}, ctx.get("ta"))
        return back == 409 and skip == 409, (back, skip)

    @case("aislamiento: otro usuario no ve pedidos ajenos")
    def _():
        call(base, "POST", "/api/auth/register", B)
        s, b = call(base, "POST", "/api/auth/login", {"email": B["email"], "password": B["password"]})
        tb = b.get("token") if isinstance(b, dict) else None
        s, orders = call(base, "GET", "/api/orders", token=tb)
        return s == 200 and orders == [], (s, orders)

    passed = sum(r["ok"] for r in results)
    return {"base": base, "total": len(results), "aprobados": passed,
            "aceptacion_pct": round(100.0 * passed / len(results), 1), "casos": results}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:4000"); ap.add_argument("--out", default="acceptance.json")
    a = ap.parse_args()
    res = run(a.base.rstrip("/"))
    open(a.out, "w", encoding="utf-8").write(json.dumps(res, indent=1, ensure_ascii=False))
    for r in res["casos"]:
        print(("✔" if r["ok"] else "✘"), r["caso"], "" if r["ok"] else f"→ {r['detalle']}")
    print(f"\nAceptación: {res['aprobados']}/{res['total']} = {res['aceptacion_pct']}%")
