"""Decision point *Layers* (Modularity): C1 identifiable layers, C2 violations of the allowed inter-layer dependencies.
"""

from evaluator.common import RUBRIC, pct
from evaluator.criteria import C, apply_manual, level_from_pct


def eval_layers(m, manual, opts):
    T = RUBRIC["thresholds"]["layers"]; P = RUBRIC["default_layers"]["allowed"]
    amb = {x.lower() for x in RUBRIC["default_layers"].get("ambiguous", [])}
    layers, origin = m["layers"], m.get("layers_origin", {})
    main = {"presentation", "business", "data"}
    ident = sorted(set(layers.values()) & main)
    cross = viol = doubtful = 0; ev = []
    for mod in m["graph"].get("modules", []):
        a = layers.get(mod["source"])
        if a not in main:
            continue
        for d in mod["deps"]:
            b = layers.get(d["to"]) if d["local"] else None
            if b in main and a != b:
                cross += 1
                if [a, b] not in P:
                    viol += 1
                    # doubtful classification: one end was assigned through an ambiguous directory (e.g. domain)
                    dbt = (origin.get(mod["source"], "").lower() in amb) or (origin.get(d["to"], "").lower() in amb)
                    doubtful += dbt
                    if len(ev) < 8:
                        ev.append(f"{mod['source']} ({a}) → {d['to']} ({b})" + (" [doubtful classification]" if dbt else ""))
    if len(ident) < T["min_identifiable_layers"]:
        crit = {"C1": C(False, f"Identifiable layers (≥{T['min_identifiable_layers']})", ident),
                "C2": C(False, "Violations ≤ 5% of inter-layer dependencies", "n/a")}
        return (crit, {"layers": ident, "inter_layer_dependencies": cross, "violations": viol, "violations_pct": 0.0}, ev,
                f"Layers detected: {', '.join(ident) or 'none'}; not enough layers.", ("Fails",) * 3)

    def level_with(v):
        vp = pct(v, cross) if cross else 0.0
        return level_from_pct(vp, lambda x: x <= T["meets_max_violations_pct"], lambda x: x <= T["partial_max_violations_pct"]), vp
    n_all, vpct = level_with(viol)
    n_firm, _ = level_with(viol - doubtful)
    crit = {"C1": C(True, f"Identifiable layers (≥{T['min_identifiable_layers']})", ident)}
    desc2 = "Violations ≤ 5% of inter-layer dependencies"
    if cross == 0:
        # No edges between layers (e.g. dependency injection): the result is not evidence of separation
        c2 = C(None, desc2, "0 inter-layer dependencies", source="pending (manual)")
        apply_manual("layers", {"C2": c2}, manual); crit["C2"] = c2
        forced = ("Meets",) * 3 if c2["ok"] else ("Fails",) * 3 if c2["ok"] is False else (None, "Fails", "Meets")
        finding = (f"Layers detected: {', '.join(ident)}; 0 inter-layer dependencies (possible dependency injection): "
                   "no structural evidence; requires manual review (layers.C2).")
    elif doubtful and n_firm != n_all:
        c2 = C(None, desc2 + " (discounting doubtful classifications)", f"{viol}/{cross} violations, {doubtful} with doubtful classification",
               source="pending (manual)")
        apply_manual("layers", {"C2": c2}, manual); crit["C2"] = c2
        # ok=true: the doubtful ones are not violations; ok=false: they are
        forced = (n_firm,) * 3 if c2["ok"] else (n_all,) * 3 if c2["ok"] is False else (None, n_all, n_firm)
        finding = (f"Layers detected: {', '.join(ident)}; {viol} of {cross} dependencies break the rule, {doubtful} because of a doubtful classification "
                   f"(ambiguous directory): from {n_all} to {n_firm} depending on manual review (layers.C2) or a .layers.json.")
    else:
        crit["C2"] = C(n_all != "Fails", desc2, f"{viol}/{cross} = {vpct:.1f}%")
        forced = (n_all,) * 3
        finding = f"Layers detected: {', '.join(ident)}; {viol} of {cross} inter-layer dependencies break the rule."
    return crit, {"layers": ident, "inter_layer_dependencies": cross, "violations": viol, "doubtful_violations": doubtful,
                  "violations_pct": vpct}, ev, finding, forced
