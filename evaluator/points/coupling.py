"""Decision point *Coupling* (Modularity): C1 dependency cycles (CWE-1047), C2 MMo-1-G, C3 DV8 Propagation Cost,
C4 unused dependencies and C5 structurally dead files (CWE-561), both measured with Knip (pending if it did not run).
"""
from evaluator.common import RUBRIC, pct
from evaluator.criteria import C, apply_manual
from evaluator.graph import cliques


def knip_result(m):
    """(knip, note): Knip's result if it ran on every package, else (None, why)."""
    kn = m.get("knip") or {}
    if kn.get("ok"):
        return kn, None
    return None, "Knip did not run: " + (kn.get("error") or "no knip result in metrics.json (evaluate the app again)")[:200]


def unused_dependencies(kn, include_dev):
    """'dir:name' of the declared dependencies nothing uses. A devDependency whose binary a script runs counts as used: without the
    app's node_modules Knip cannot map a binary (`jest`, `vite`) to its package and reports both."""
    out = list(kn["dependencies"])
    if include_dev:
        bins = set(kn.get("binaries", []))
        out += [x for x in kn["devDependencies"] if x not in bins]
    return out


def dead_files(m, kn):
    """Production files that no entry point reaches (CWE-561, coupling.C5), per Knip. Only the files ast_metrics.js analyzes as
    production code count (tests, .d.ts, build output and minified files are left out)."""
    prod = {f["path"] for f in m["ast"]["files"] if not f["test"]}
    return sorted(f for f in kn["files"] if f in prod)


def eval_coupling(m, manual, opts):
    T = RUBRIC["thresholds"]["coupling"]
    mods = m["graph"].get("modules", [])
    # MMo-1-G numerator: modules whose outgoing coupling is bounded. The absence of dependency cycles is NOT counted here:
    # it is criterion C1 of this same point (CWE-1047), and counting it twice let one defect lower two of the four criteria.
    A = sum(1 for x in mods if len({d["module"] for d in x["deps"]}) < T["outgoing_deps_max"])
    X = A / len(mods) if mods else None
    pc = (manual.get("dv8") or {}).get("PC")
    kn, note = knip_result(m)
    unused = unused_dependencies(kn, T["include_devdependencies"]) if kn else []
    pu = pct(len(unused), m["packages"]["direct"]) if m["packages"]["direct"] else 0.0
    orphans = dead_files(m, kn) if kn else []
    DC = RUBRIC["thresholds"]["dead_code"]
    src = f"auto (Knip {kn['version']})" if kn else f"pending ({note})"
    crit = {"C1": C(len(m["graph"].get("cycles", [])) == 0, "0 dependency cycles (CWE-1047)", len(m["graph"].get("cycles", []))),
            "C2": C(None if X is None else X >= T["X_min"], "X (MMo-1-G) ≥ 0.90", None if X is None else round(X, 3)),
            "C3": C(None if pc is None else pc <= T["PC_max"], f"Propagation Cost (DV8) ≤ {T['PC_max'] * 100:g}%", pc, source="dv8" if pc is not None else "pending (DV8)"),
            "C4": C(pu <= T["pct_unused_max"] if kn else None, "≤ 10% unused dependencies",
                    f"{len(unused)}/{m['packages']['direct']} = {pu:.1f}%" if kn else None, source=src),
            "C5": C(len(orphans) <= DC["structural_max_files"] if kn else None,
                    f"≤ {DC['structural_max_files']} production file(s) unreachable from every entry point (CWE-561)", len(orphans) if kn else None, source=src)}
    apply_manual("coupling", crit, manual)
    ev = [" ↔ ".join(c[:4]) for c in m["graph"].get("cycles", [])[:4]] + unused[:6]
    cq = cliques(m)
    ev += [f"clique of {len(c)} files: {', '.join(c[:4])}" for c in cq[:3]]
    ev += [f"structurally dead (no entry point reaches it): {h}" for h in orphans[:4]]
    met = {"modules": len(mods), "cycles": len(m["graph"].get("cycles", [])), "X": X, "orphan_files": orphans, "cliques": len(cq),
           "files_in_cliques": sum(len(c) for c in cq), "unused_dependencies": unused}
    finding = f"{len(m['graph'].get('cycles', []))} cycles ({len(cq)} clique(s)); X={'n/a' if X is None else f'{X:.2f}'}; "
    if kn:  # unused exports and undeclared dependencies are informational: they change no level
        met.update({"unused_exports": len(kn["exports"]), "unlisted_dependencies": kn["unlisted"], "unresolved_imports": kn["unresolved"],
                    "knip_config_load_errors": kn["config_load_errors"]})
        ev += [f"used but not declared in package.json: {x['name']} ({x['file']})" for x in kn["unlisted"][:3]]
        finding += (f"{len(unused)} unused dependencies; {len(orphans)} production file(s) no entry point reaches (CWE-561); "
                    f"{len(kn['exports'])} unused export(s) and {len(kn['unlisted'])} dependency(ies) used but not declared (informational).")
    else:
        finding += f"unused dependencies and dead files not measured ({note})."
    return crit, met, ev, finding, None
