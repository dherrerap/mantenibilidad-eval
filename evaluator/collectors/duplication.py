"""Code clones (CWE-1041) with jscpd.
"""
import json
import os
import shutil
from pathlib import Path

from evaluator.common import HERE, RUBRIC, sh


def run_duplication(app, out):
    """Code clones (copy-paste) with jscpd. Returns {ok, pct, clones, duplicated_lines, lines, top}."""
    T = RUBRIC["thresholds"]["duplication"]
    jscpd = HERE / "node_modules" / "jscpd" / "bin" / "jscpd"  # via node: Windows' .cmd splits the arguments at commas
    if not jscpd.exists():
        return {"ok": False, "reason": "jscpd not installed (npm install)"}
    d = out / "jscpd"; shutil.rmtree(d, ignore_errors=True)
    ign = ",".join([f"**/{x}/**" for x in ("node_modules", "tests", "test", "__tests__", "coverage", "dist", "build")] +
                   ["**/*.test.*", "**/*.spec.*", "**/*.min.js"])
    rc, so, se = sh(["node", str(jscpd), Path(app).as_posix(), "--silent", "--reporters", "json", "--output", d.as_posix(),
                     "--min-lines", str(T["min_lines"]), "--min-tokens", str(T["min_tokens"]),
                     "--format", "javascript,typescript,jsx,tsx", "--ignore", ign], timeout=300)
    rep = d / "jscpd-report.json"
    if not rep.exists():
        return {"ok": False, "reason": (se or so)[-200:] or f"rc={rc}"}
    r = json.loads(rep.read_text(encoding="utf-8")); t = r["statistics"]["total"]
    top = sorted(r.get("duplicates", []), key=lambda c: -c["lines"])[:5]
    name = lambda f: os.path.relpath(Path(f).resolve(), Path(app).resolve()).replace("\\", "/")  # jscpd reports them relative to the cwd
    return {"ok": True, "pct": t["percentage"], "clones": t["clones"], "duplicated_lines": t["duplicatedLines"], "lines": t["lines"],
            "top": [f"{name(c['firstFile']['name'])}:{c['firstFile']['start']} ≈ {name(c['secondFile']['name'])}:{c['secondFile']['start']} ({c['lines']} lines)" for c in top]}
