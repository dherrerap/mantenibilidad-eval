#!/usr/bin/env python3
"""
record_scoring.py — Golden cases for the JavaScript port of the decision points and the scoring (evaluator/points/*,
evaluator/criteria.py, evaluator/scoring.py, evaluator/ascmm.py, evaluator/supplementary.py).

Records every top-level call of the 11 point functions, evaluate_points, evaluate_profile, profile, risk_summary, level_from and
supplementary_indicators made by the Python test suite, and evaluate_profile / risk_summary on each evaluated run in results/ (with
the same inputs `evaluate.py rescore` gives it: metrics.json, manual review, DV8, live database, judge).

Each record also keeps what the call read from disk (the error middleware's file, the design documents), so that the JavaScript
replay does not depend on the temporary folders of the test suite.

  python python/golden/record_scoring.py
Writes tests/golden/scoring.json (test suite, committed) and results/_golden/scoring-apps.json (generated apps, local only).
"""
import copy, functools, hashlib, json, os, pathlib, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE / "python")); sys.path.insert(0, str(HERE / "python" / "tests")); sys.path.insert(0, str(HERE / "python" / "golden"))
os.chdir(HERE)
import evaluate as ev  # noqa: E402,F401
from record_relational import to_json  # noqa: E402
import evaluator.criteria as crit_mod  # noqa: E402
import evaluator.scoring as scoring  # noqa: E402
import evaluator.supplementary as supp  # noqa: E402
import evaluator.points.data_model as dm  # noqa: E402
from evaluator.points import EVALUATORS  # noqa: E402

MAX_PER_FN = 400
TARGETS = {scoring: ["evaluate_points", "evaluate_profile", "profile", "risk_summary"], crit_mod: ["level_from"], supp: ["supplementary_indicators"]}
ORIGINAL_EVALUATORS = dict(EVALUATORS)


def opts_json(x):
    """The `opts` argument (a class, a SimpleNamespace or an argparse result): only the attributes the scoring reads."""
    return {"accept_heuristics": bool(getattr(x, "accept_heuristics", False))}


def anonymize(args):
    """The app folders of the test suite are temporary and local: the JavaScript replay reads nothing from them (it gets the recorded
    files), so their path is replaced."""
    for a in args:
        if isinstance(a, dict) and "app" in a and isinstance(a["app"], str):
            a["app"] = "<app>"
        if isinstance(a, dict) and isinstance(a.get("ast"), dict) and "root" in a["ast"]:
            a["ast"]["root"] = "<app>"
    return args


class Recorder:
    def __init__(self, anonymize_paths=True):
        self.calls, self.seen, self.count, self.depth, self.files, self.design, self.anon = [], set(), {}, 0, None, None, anonymize_paths

    def wrap(self, qual, fn, opts_pos=None):
        @functools.wraps(fn)
        def inner(*args, **kw):
            top = self.depth == 0
            before = None
            if top:
                try:
                    raw = [copy.deepcopy(a) for a in args]
                    if opts_pos is not None and len(raw) > opts_pos:
                        raw[opts_pos] = opts_json(args[opts_pos])
                    before = to_json(raw)
                except TypeError:
                    before = None
                self.files, self.design = {}, {}
            self.depth += 1
            try:
                result = fn(*args, **kw)
            finally:
                self.depth -= 1
            # a test that replaces EVALUATORS with stubs does not exercise the real points: not a golden case
            if top and before is not None and dict(EVALUATORS) == ORIGINAL_EVALUATORS:
                try:
                    res = to_json(result)
                except TypeError:
                    return result
                app = next((a.get("app") for a in args if isinstance(a, dict) and isinstance(a.get("app"), str)), None)
                rec = {"fn": qual, "args": anonymize(before) if self.anon else before, "kwargs": to_json(kw), "result": res,
                       "files": relative_files(self.files, app), "design_text": self.design.get("text")}
                key = hashlib.sha256(json.dumps([qual, rec["args"], rec["kwargs"], rec["files"]], sort_keys=True).encode()).hexdigest()
                if key not in self.seen and self.count.get(qual, 0) < MAX_PER_FN:
                    self.seen.add(key); self.count[qual] = self.count.get(qual, 0) + 1
                    self.calls.append(rec)
            return result
        return inner

    def install(self):
        orig_read = pathlib.Path.read_text
        rec = self

        def read_text(path, *a, **k):  # what a recorded call reads (relative to its app folder when it can tell)
            try:
                text = orig_read(path, *a, **k)
            except Exception:
                if rec.files is not None and rec.depth > 0:
                    rec.files[str(path)] = None  # unreadable: the point skips it, and so must the replay
                raise
            if rec.files is not None and rec.depth > 0:
                rec.files[str(path)] = text
            return text
        pathlib.Path.read_text = read_text
        orig_design = dm.design_text

        def design_text(app):
            t = orig_design(app)
            if rec.design is not None:
                rec.design["text"] = t
            return t
        dm.design_text = design_text
        swaps = []
        for mod, names in TARGETS.items():
            for n in names:
                o = getattr(mod, n)
                w = self.wrap(f"{mod.__name__}.{n}", o, opts_pos=2 if n in ("evaluate_points", "evaluate_profile") else None)
                setattr(mod, n, w); swaps.append((o, w))
        for pid, fn in list(EVALUATORS.items()):
            w = self.wrap(f"points.{fn.__name__}", fn, opts_pos=2)
            swaps.append((fn, w))
        for m in list(sys.modules.values()):  # every module that imported one of the functions by name
            if not getattr(m, "__name__", "").split(".")[0] in ("evaluator", "evaluate", "test_evaluator", "judge", "manual_template"):
                continue
            for o, w in swaps:
                for attr, val in list(vars(m).items()):
                    if val is o:
                        setattr(m, attr, w)
        # EVALUATORS keeps the originals: points called through evaluate_points are covered by it, not recorded twice


def relative_files(files, app):
    """{path relative to the app folder (POSIX): text or None} of what a call read; files outside the app keep only their name."""
    out = {}
    for p, t in (files or {}).items():
        try:
            k = Path(p).resolve().relative_to(Path(app).resolve()).as_posix() if app else Path(p).name
        except ValueError:
            k = Path(p).name
        out[k] = t
    return out


def write(path, calls):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calls": calls}, ensure_ascii=False, indent=0), encoding="utf-8")
    by = {}
    for c in calls:
        by[c["fn"]] = by.get(c["fn"], 0) + 1
    print(f"{path}: {len(calls)} calls ({', '.join(f'{k.split('.')[-1]} {v}' for k, v in sorted(by.items()))})")


def main():
    rec = Recorder()
    import test_evaluator  # noqa: F401
    rec.install()
    suite = unittest.defaultTestLoader.loadTestsFromName("test_evaluator")
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    if not result.wasSuccessful():
        sys.exit(f"the Python test suite fails ({len(result.failures)} failures, {len(result.errors)} errors): fix it before recording")
    write(HERE / "tests" / "golden" / "scoring.json", rec.calls)

    # the evaluated runs, with the inputs of `evaluate.py rescore`
    from evaluator.artifacts import refresh_schema_artifact
    from evaluator.pipeline import assemble_manual, load_run
    from types import SimpleNamespace
    rec2 = Recorder(anonymize_paths=False)
    rec2.install()
    # results/ and any preserved copy of earlier evaluations (results-initial/…): more real inputs for the same code
    runs = sorted(d for base in HERE.glob("results*") if base.is_dir() for d in base.iterdir() if (d / "metrics.json").exists())
    for res in runs:
        m, meta = load_run(res)
        manual = assemble_manual(m.get("app"), res, meta.get("manual_file"))
        scoring.load_pg(res, m); scoring.load_conformance(res, m); refresh_schema_artifact(m); scoring.load_judge(res, manual)
        pts, _ = scoring.evaluate_profile(m, manual, SimpleNamespace(accept_heuristics=bool(meta.get("accept_heuristics"))))
        scoring.risk_summary(pts)
    if rec2.calls:
        write(HERE / "results" / "_golden" / "scoring-apps.json", rec2.calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
