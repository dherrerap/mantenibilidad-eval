"""AST metrics of the app's JS/TS code: runs ast_metrics.js (ts-morph).
"""
import json

from evaluator.common import HERE, sh


def run_ast(app, out):
    f = out / "ast.json"
    rc, so, se = sh(["node", str(HERE / "ast_metrics.js"), str(app), str(f)], timeout=600)
    if rc != 0:
        raise SystemExit(f"ast_metrics.js failed:\n{se or so}")
    return json.loads(f.read_text(encoding="utf-8"))
