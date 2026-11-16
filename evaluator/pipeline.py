"""Scoring of a run from its saved evidence, without collecting it again.

Collecting (collectors.collect: AST, npm registry, npm audit, the app's tests, jscpd…) is the slow part of an evaluation; scoring
is instantaneous. Everything a later step adds — DV8 values (dv8_metrics.py), the live database (pg_analysis.py), the judge's
decisions (judge.py), a manual review — only changes the scoring, so after those steps a run is RE-SCORED from
results/<run>/metrics.json instead of being evaluated again.

Inputs of the scoring, read fresh every time:
  metrics.json                     evidence (written by `evaluate.py run`)
  meta.json                        identity of the run and the options that affect the scoring (accept_heuristics)
  manual review                    --manual of the run > <app>/manual.json > <res>/manual_review.json
  dv8/dv8_manual.json, dv8_metrics.json   DV8 values (the manual review takes precedence)
  pg_schema.json                   catalog of the live database (pg_analysis.py)
  judge.json                       the judge's decisions (lowest priority)
"""
import json
from pathlib import Path
from types import SimpleNamespace

from evaluator.artifacts import refresh_schema_artifact
from evaluator.outputs import write_outputs
from evaluator.scoring import evaluate_profile, load_judge, load_pg

MANUAL_REVIEW = "manual_review.json"


def assemble_manual(app, res, explicit=None):
    """The manual review of a run: the first of `explicit` (--manual), <app>/manual.json and <res>/manual_review.json that exists,
    plus the DV8 values. Priority for DV8: the review > dv8/dv8_manual.json (human, never regenerated) > dv8/dv8_metrics.json."""
    res = Path(res)
    cands = [explicit, Path(app) / "manual.json" if app else None, res / MANUAL_REVIEW]
    mfile = next((Path(p) for p in cands if p and Path(p).exists()), None)
    manual = json.loads(mfile.read_text(encoding="utf-8")) if mfile else {}
    for source in ("dv8_manual.json", "dv8_metrics.json"):
        f = res / "dv8" / source
        if f.exists():
            dv8 = manual.setdefault("dv8", {})
            for k, v in json.loads(f.read_text(encoding="utf-8")).items():
                if not k.startswith("_") and v is not None and dv8.get(k) is None:
                    dv8[k] = v
    return manual


def score(res, m, meta, manual_file=None):
    """Scores a run from its evidence `m` and writes every output of results/<run>/. Returns (points, profile)."""
    res = Path(res)
    manual = assemble_manual(m.get("app"), res, manual_file)
    (res / "manual.json").write_text(json.dumps(manual, indent=1), encoding="utf-8")  # what this scoring used, for traceability
    load_pg(res, m)
    refresh_schema_artifact(m)
    load_judge(res, manual)
    pts, prof = evaluate_profile(m, manual, SimpleNamespace(accept_heuristics=bool(meta.get("accept_heuristics"))))
    write_outputs(res, meta, pts, prof, m)
    return pts, prof


def load_run(res):
    """(metrics, meta) saved by `evaluate.py run` in results/<run>/."""
    res = Path(res)
    m = json.loads((res / "metrics.json").read_text(encoding="utf-8"))
    meta = json.loads((res / "meta.json").read_text(encoding="utf-8"))
    return m, meta


def rescore(res):
    """Scores an already evaluated run again from its saved evidence (no collection). Returns (meta, points, profile)."""
    m, meta = load_run(res)
    pts, prof = score(res, m, meta, meta.get("manual_file"))
    return meta, pts, prof
