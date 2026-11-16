"""Decision point *Coupling* (Modularity): C1 dependency cycles (CWE-1047), C2 MMo-1-G, C3 DV8 Propagation Cost,
C4 unused dependencies, C5 structurally dead files (CWE-561).
"""
import os
import re
from pathlib import Path

from evaluator.common import RUBRIC, pct
from evaluator.criteria import C, apply_manual
from evaluator.graph import cliques, fan_in


SCRIPT_FILE = re.compile(r"(?:^|[\s=\"'])(?:\./)?([\w@.\-/]+\.[cm]?[jt]sx?)(?=$|[\s\"';&|])")


def script_entry_files(packages):
    """App-relative paths of the files that package.json launches: its `main` and the files named in its scripts
    (e.g. "migrate": "node src/data/migrateCli.js"). Nobody imports them, but they are entry points, not dead code."""
    out = set()
    for p in packages or []:
        base = "" if p.get("dir") in (None, ".", "") else p["dir"]
        names = [p.get("main")] + [m.group(1) for s in (p.get("scripts") or {}).values() for m in SCRIPT_FILE.finditer(str(s))]
        for n in filter(None, names):
            out.add(os.path.normpath(os.path.join(base, n)).replace("\\", "/"))
    return out


def orphan_files(m):
    """Production files with fan-in 0 that are not entry points: structurally dead code (CWE-561), scored in coupling.C5.
    Entry points: the names in rubric.json (index, server, app…), config files and the files package.json launches."""
    if not m["graph"].get("modules"):
        return []  # without a graph every file would look orphaned
    entries = set(RUBRIC["thresholds"]["dead_code"]["entry_points"])
    launched = script_entry_files((m.get("packages") or {}).get("packages"))
    fi = fan_in(m)
    return sorted(f["path"] for f in m["ast"]["files"]
                  if not f["test"] and f["path"] not in fi and Path(f["path"]).stem.split(".")[0] not in entries
                  and f["path"] not in launched and not re.search(r"\.config\.|\.d\.ts$", f["path"]))


def eval_coupling(m, manual, opts):
    T = RUBRIC["thresholds"]["coupling"]
    mods = m["graph"].get("modules", [])
    # MMo-1-G numerator: modules whose outgoing coupling is bounded. The absence of dependency cycles is NOT counted here:
    # it is criterion C1 of this same point (CWE-1047), and counting it twice let one defect lower two of the four criteria.
    A = sum(1 for x in mods if len({d["module"] for d in x["deps"]}) < T["outgoing_deps_max"])
    X = A / len(mods) if mods else None
    pc = (manual.get("dv8") or {}).get("PC")
    unused = m["packages"]["unused"]; pu = pct(len(unused), m["packages"]["direct"]) if m["packages"]["direct"] else 0.0
    orphans = orphan_files(m)
    DC = RUBRIC["thresholds"]["dead_code"]
    crit = {"C1": C(len(m["graph"].get("cycles", [])) == 0, "0 dependency cycles (CWE-1047)", len(m["graph"].get("cycles", []))),
            "C2": C(None if X is None else X >= T["X_min"], "X (MMo-1-G) ≥ 0.90", None if X is None else round(X, 3)),
            "C3": C(None if pc is None else pc <= T["PC_max"], f"Propagation Cost (DV8) ≤ {T['PC_max'] * 100:g}%", pc, source="dv8" if pc is not None else "pending (DV8)"),
            "C4": C(pu <= T["pct_unused_max"] if m["packages"]["depcheck_ok"] else None, "≤ 10% unused dependencies", f"{len(unused)}/{m['packages']['direct']} = {pu:.1f}%"),
            "C5": C(len(orphans) <= DC["structural_max_files"], f"≤ {DC['structural_max_files']} structurally dead production file(s) (CWE-561)", len(orphans))}
    apply_manual("coupling", crit, manual)
    ev = [" ↔ ".join(c[:4]) for c in m["graph"].get("cycles", [])[:4]] + unused[:6]
    cq = cliques(m)
    ev += [f"clique of {len(c)} files: {', '.join(c[:4])}" for c in cq[:3]]
    ev += [f"structurally dead (nobody imports it): {h}" for h in orphans[:4]]
    return crit, {"modules": len(mods), "cycles": len(m["graph"].get("cycles", [])), "X": X, "orphan_files": orphans, "cliques": len(cq), "files_in_cliques": sum(len(c) for c in cq)}, ev, \
        f"{len(m['graph'].get('cycles', []))} cycles ({len(cq)} clique(s)); X={'n/a' if X is None else f'{X:.2f}'}; {len(unused)} unused dependencies; " \
        f"{len(orphans)} file(s) that nobody imports (CWE-561).", None
