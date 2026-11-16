"""Decision point *Contracts* (Modularity, Testability): C1 machine-readable contract, C2 Spectral errors, C3 routes covered
by the contract, C4 input validation consistent with the contract.
"""

from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual
from evaluator.routes import full_routes, route_match


def eval_contracts(m, manual, opts):
    T = RUBRIC["thresholds"]["contracts"]; ct = m["contract"]; routes = full_routes(m["ast"])
    has = bool(ct["files"])
    cov = None
    if has and routes:
        cov = 100.0 * sum(route_match(ct["paths"], r, ct.get("bases")) for r in routes) / len(routes)
    unresolved = sum(1 for r in routes if not r["resolved"])
    deps = {d for p in m["packages"]["packages"] for d in {**p["dependencies"], **p["devDependencies"]}}
    vlibs = sorted(deps & set(RUBRIC["libs_validation"]))
    # C4: there is a contract, there is a validation library, POST/PUT/PATCH routes validate their input and the validated fields exist in the contract
    writes = [r for r in routes if r["method"] in ("POST", "PUT", "PATCH")]
    validated = sum(1 for r in writes if r.get("validated"))
    val_pct = 100.0 * validated / len(writes) if writes else None
    val_txt = "no write routes" if val_pct is None else f"{validated}/{len(writes)} = {val_pct:.0f}%"
    vf = {c for v in m["ast"].get("validationFields", []) for c in v["fields"]}
    props = set(ct.get("properties") or [])
    outside = sorted(vf - props)
    fields_ok = None if not (vf and props) else not outside
    if not has: c4_ok = False
    elif val_pct is None: c4_ok = True
    elif not vlibs: c4_ok = False
    else: c4_ok = val_pct >= T["coverage_min"] and fields_ok is not False
    c4_value = {"libs": vlibs, "validated_write_routes": val_txt, "validated_fields_outside_contract": outside if props else "no properties in the contract"}
    crit = {"C1": C(has, "Machine-readable contract (OpenAPI/…)", ct["files"]),
            "C2": C((ct["spectral_errors"] == 0) if (has and ct["spectral_errors"] is not None) else (False if not has else None), "0 Spectral errors (spectral:oas)", ct["spectral_errors"]),
            "C3": C((cov >= T["coverage_min"]) if cov is not None else False, "Contract covers ≥ 90% of routes", None if cov is None else f"{cov:.0f}% of {len(routes)} routes"),
            "C4": C(c4_ok, "Input validation consistent with the contract (write routes validated ≥ 90% and validated fields present in the contract)", c4_value)}
    apply_manual("contracts", crit, manual)
    return crit, {"implemented_routes": len(routes), "coverage_pct": cov, "routes_with_unresolved_prefix": unresolved,
                  "contract_endpoints_over_implemented": (len(ct["paths"]) / len(routes)) if routes and ct["paths"] else None}, \
        ct["files"][:3] + [f"{r['method']} {r['full_path']}" for r in routes[:4]], \
        f"{'Contract: ' + ', '.join(ct['files']) if has else 'No machine-readable contract'}; {len(routes)} implemented routes" \
        + (f" ({unresolved} with a mount prefix that could not be resolved)." if unresolved else "."), None
