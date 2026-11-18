"""Layer of each backend file (presentation, business, data, shared) from directory and file names, or .layers.json.
"""
import json
import re
from pathlib import Path

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_schema as rs  # noqa: E402
from evaluator.common import RUBRIC, glob_to_re


def classify_layers(ast, app, override):
    L = RUBRIC["default_layers"]
    names = ["presentation", "business", "data", "shared"]
    ov = None
    if override and Path(override).exists():
        ov = {k: [glob_to_re(g) for g in v] for k, v in json.loads(Path(override).read_text()).items() if not k.startswith("_")}
    out = {}; origin = {}
    for f in ast["files"]:
        if f["test"] or f["frontend"]:
            continue
        p = f["path"]
        layer = None
        if ov:
            for k, rs in ov.items():
                if any(r.match(p) for r in rs):
                    layer = k; origin[p] = "override"; break
        else:
            parts = p.lower().split("/")
            stem = re.sub(r"([a-z])([A-Z])", r"\1.\2", Path(p).stem).lower()
            tokens = [t for t in re.split(r"[.\-_]", stem) if t] + list(reversed(parts[:-1]))
            norm = lambda s: s.rstrip("s")
            # Architectural layers first (token closest to the file); 'shared' only if nothing else matches
            for group in (names[:3], names[3:]):
                for tok in tokens:
                    for n in group:
                        if norm(tok) in {norm(k) for k in L[n]}:
                            layer = n; origin[p] = tok; break
                    if layer:
                        break
                if layer:
                    break
        if layer:
            out[p] = layer
    return out, origin
