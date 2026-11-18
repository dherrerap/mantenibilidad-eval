"""Module dependency graph and dependency cycles (dependency-cruiser).
"""
import json

from evaluator.common import BIN, sh


def run_depcruise(app, out):
    cfg = {
        "forbidden": [{"name": "no-circular", "severity": "warn", "from": {}, "to": {"circular": True}}],
        "options": {
            "doNotFollow": {"path": "node_modules"},
            "exclude": {"path": r"(^|/)(node_modules|dist|build|coverage|\.git)/|(__tests__|__mocks__)|\.(test|spec)\.[cm]?[jt]sx?$|(^|/)(tests?|e2e|cypress)/"},
            "moduleSystems": ["es6", "cjs"],
            "tsPreCompilationDeps": True,
        },
    }
    cfgf = out / "depcruise.config.json"
    cfgf.write_text(json.dumps(cfg), encoding="utf-8")
    rc, so, se = sh([str(BIN / "depcruise"), "--config", str(cfgf), "--output-type", "json", "."], cwd=app, timeout=600)
    try:
        data = json.loads(so)
    except Exception:
        return {"error": (se or so)[:500], "modules": [], "cycles": []}
    mods, cycles = [], set()
    for m in data.get("modules", []):
        deps = []
        for d in m.get("dependencies", []):
            local = not d.get("coreModule") and not d.get("couldNotResolve") and "node_modules" not in d.get("resolved", "")
            deps.append({"to": d.get("resolved"), "local": local, "module": d.get("module")})
        mods.append({"source": m["source"], "deps": deps})
    for v in data.get("summary", {}).get("violations", []):
        c = v.get("cycle")
        if c:
            names = [x["name"] if isinstance(x, dict) else x for x in c]
            cycles.add(tuple(sorted(set(names))))
    return {"modules": mods, "cycles": [list(c) for c in sorted(cycles)]}
