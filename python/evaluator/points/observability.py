"""Decision point *Observability* (Analyzability): C1 critical events logged, C2 structured logger without console.*,
C3 centralized error handling, C4 health check, metrics or traces.
"""
import re
from pathlib import Path

from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual
from evaluator.routes import full_routes, is_health_route


def eval_observability(m, manual, opts):
    T = RUBRIC["thresholds"]["observability"]; cb = m["ast"]["catchBlocks"]
    deps = {d for p in m["packages"]["packages"] for d in {**p["dependencies"], **p["devDependencies"]}}
    logger = sorted(deps & set(RUBRIC["libs_logger"])); metrics = sorted(deps & set(RUBRIC["libs_metrics"]))
    mw = m["ast"]["errorMiddleware"]
    central_logs = False
    for e in mw:
        try:
            text = (Path(m["app"]) / e["file"]).read_text(encoding="utf-8", errors="ignore")
            central_logs |= bool(re.search(r"\b(console|logger|log)\.\w+", text))  # \b: "catalog.find" is not a log call
        except Exception:
            pass
    reqlog = sorted(deps & set(RUBRIC["libs_request_logger"]))  # morgan, pino-http…: log every request, writes included
    evs = [f for f in m["ast"]["functions"] if f.get("event")]
    ev_ok = [f for f in evs if f["logs"] or reqlog]
    A = cb["logging"] + (cb["delegating"] if central_logs else 0) + len(ev_ok); B = cb["total"] + len(evs)
    X = A / B if B else None
    c1 = (X >= T["X_min"]) if X is not None else bool(mw and central_logs)
    cons = len(m["ast"]["consoleCalls"])
    health = [r for r in full_routes(m["ast"]) if is_health_route(r["full_path"])]
    crit = {"C1": C(c1, "X ≥ 0.80 of critical events logged (errors: catch blocks; authentication and writes: functions that log, or a request logger)",
                    None if X is None else round(X, 2), source="auto (proxy)"),
            "C2": C(bool(logger) and cons == 0, "Structured logger and no console.* in production", {"logger": logger, "console_calls": cons}),
            "C3": C(bool(mw), "Centralized error handling", len(mw)),
            "C4": C(bool(health or metrics), "Health check, metrics or traces", {"routes": [r["full_path"] for r in health], "libs": metrics})}
    apply_manual("observability", crit, manual)
    ev = [f"{c['file']}:{c['line']} console.*" for c in m["ast"]["consoleCalls"][:5]] + [f"catch without logging {c['file']}:{c['line']}" for c in cb["silent"][:3]]
    ev += [f"{f['event']} without logging {f['file']}:{f['line']} {f['name']}" for f in evs if f not in ev_ok][:4]
    return crit, {"catch_total": cb["total"], "console_calls": cons, "auth_write_events": len(evs), "logged_events": len(ev_ok), "request_logger": reqlog}, ev, \
        f"{cb['total']} catch blocks ({cb['logging']} log, {cb['delegating']} delegate, {len(cb['silent'])} silent); {len(evs)} authentication/write functions ({len(ev_ok)} logged{', request logger' if reqlog else ''}); {cons} console.*; {len(mw)} error middleware(s).", None
