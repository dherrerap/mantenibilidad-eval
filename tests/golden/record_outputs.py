#!/usr/bin/env python3
"""
record_outputs.py — Golden cases for the JavaScript port of the outputs: the files write_outputs writes for a run (scorecard,
profile, dashboard, CSVs, manual template), the weight sensitivity and the ASCMM comparison.

  python tests/golden/record_outputs.py

Records, from the Python test suite, every top-level call of write_outputs (its arguments and the content of every file it wrote),
sensitivity, sensitivity_md, ascmm_comparison_md and ascmm_columns. On every evaluated run in results*/ it records the same with the
inputs of `evaluate.py rescore`, plus those inputs (metrics, manual review, options), so that the JavaScript test can also run the
whole chain metrics.json → evaluate_profile → write_outputs and compare the files.

Writes tests/golden/outputs.json (test suite, committed) and results/_golden/outputs-apps.json (generated apps, local only).
"""
import copy, functools, hashlib, json, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / "tests")); sys.path.insert(0, str(HERE / "tests" / "golden"))
os.chdir(HERE)
import evaluate as ev  # noqa: E402,F401
from record_relational import to_json  # noqa: E402
import evaluator.outputs as outputs  # noqa: E402
import evaluator.pipeline as pipeline  # noqa: E402
import evaluator.sensitivity as sens  # noqa: E402
import evaluator.ascmm as ascmm  # noqa: E402
import evaluator.scoring as scoring  # noqa: E402
import token_usage as tu  # noqa: E402

OUT_FILES = ["scorecard.json", "profile.json", "artifacts.json", "risk_dashboard.json", "risk_dashboard.md", "risk_dashboard.html",
             "scorecard.csv", "traceability.csv", "supplementary.json", "profile.md", "manual.template.json"]
MAX_PER_FN = 200


def read_bytes_text(p):
    """A written file as text, without the Windows newline translation of Path.write_text (CSV files keep their \\r\\n)."""
    b = Path(p).read_bytes().decode("utf-8")
    return b if p.suffix == ".csv" else b.replace("\r\n", "\n")


def anon(x):
    if isinstance(x, dict):
        if isinstance(x.get("app"), str):
            x["app"] = "<app>"
        if isinstance(x.get("ast"), dict) and "root" in x["ast"]:
            x["ast"]["root"] = "<app>"
    return x


class Recorder:
    def __init__(self, anonymize=True):
        self.calls, self.seen, self.count, self.depth, self.anon = [], set(), {}, 0, anonymize

    def keep(self, rec):
        key = hashlib.sha256(json.dumps([rec["fn"], rec["args"]], sort_keys=True).encode()).hexdigest()
        if key in self.seen or self.count.get(rec["fn"], 0) >= MAX_PER_FN:
            return
        self.seen.add(key); self.count[rec["fn"]] = self.count.get(rec["fn"], 0) + 1
        self.calls.append(rec)

    def wrap_plain(self, qual, fn):
        @functools.wraps(fn)
        def inner(*args, **kw):
            top = self.depth == 0
            try:
                before = to_json([copy.deepcopy(a) for a in args]) if top else None
            except TypeError:
                before = None
            self.depth += 1
            try:
                result = fn(*args, **kw)
            finally:
                self.depth -= 1
            if top and before is not None:
                try:
                    self.keep({"fn": qual, "args": [anon(a) for a in before] if self.anon else before, "kwargs": to_json(kw), "result": to_json(result)})
                except TypeError:
                    pass
            return result
        return inner

    def wrap_write(self, fn):
        @functools.wraps(fn)
        def inner(out, meta, points, prof, m):
            top = self.depth == 0
            tok = None
            if top:
                before = to_json([copy.deepcopy(x) for x in (meta, points, prof, m)])
                tf = Path(out) / tu.RESULT_FILE
                tok = tf.read_text(encoding="utf-8") if tf.exists() else None
            self.depth += 1
            try:
                result = fn(out, meta, points, prof, m)
            finally:
                self.depth -= 1
            if top:
                files = {f: read_bytes_text(Path(out) / f) for f in OUT_FILES if (Path(out) / f).exists()}
                args = ["<out>"] + ([anon(a) for a in before] if self.anon else before)
                self.keep({"fn": "evaluator.outputs.write_outputs", "args": args, "kwargs": {}, "token_usage": tok, "files": files})
            return result
        return inner

    def install(self):
        swaps = [(outputs.write_outputs, self.wrap_write(outputs.write_outputs))]
        for mod, names in ((sens, ["sensitivity", "sensitivity_md"]), (ascmm, ["ascmm_comparison_md", "ascmm_columns"])):
            for n in names:
                swaps.append((getattr(mod, n), self.wrap_plain(f"{mod.__name__}.{n}", getattr(mod, n))))
        for m in list(sys.modules.values()):
            if getattr(m, "__name__", "").split(".")[0] not in ("evaluator", "evaluate", "test_evaluator", "cli"):
                continue
            for o, w in swaps:
                for attr, val in list(vars(m).items()):
                    if val is o:
                        setattr(m, attr, w)


def write(path, calls):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calls": calls}, ensure_ascii=False, indent=0), encoding="utf-8")
    by = {}
    for c in calls:
        by[c["fn"]] = by.get(c["fn"], 0) + 1
    print(f"{path}: {len(calls)} calls ({', '.join(f'{k.split('.')[-1]} {v}' for k, v in sorted(by.items()))})")


def main():
    import test_evaluator  # noqa: F401
    rec = Recorder()
    rec.install()
    suite = unittest.defaultTestLoader.loadTestsFromName("test_evaluator")
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    if not result.wasSuccessful():
        sys.exit(f"the Python test suite fails ({len(result.failures)} failures, {len(result.errors)} errors): fix it before recording")
    write(HERE / "tests" / "golden" / "outputs.json", rec.calls)

    # the evaluated runs: the inputs of `evaluate.py rescore`, and the outputs written into a temporary folder (results/ is untouched)
    from evaluator.artifacts import refresh_schema_artifact
    from types import SimpleNamespace
    rec2 = Recorder(anonymize=False)
    rec2.install()
    runs = sorted(d for base in HERE.glob("results*") if base.is_dir() for d in base.iterdir() if (d / "metrics.json").exists())
    rows = []
    for res in runs:
        m, meta = pipeline.load_run(res)
        manual = pipeline.assemble_manual(m.get("app"), res, meta.get("manual_file"))
        scoring.load_pg(res, m); scoring.load_conformance(res, m); refresh_schema_artifact(m); scoring.load_judge(res, manual)
        opts = {"accept_heuristics": bool(meta.get("accept_heuristics"))}
        inputs = to_json([copy.deepcopy(m), copy.deepcopy(manual), opts])
        pts, prof = scoring.evaluate_profile(m, manual, SimpleNamespace(**opts))
        with tempfile.TemporaryDirectory() as t:
            tf = res / tu.RESULT_FILE
            if tf.exists():
                (Path(t) / tu.RESULT_FILE).write_text(tf.read_text(encoding="utf-8"), encoding="utf-8")
            outputs.write_outputs(Path(t), meta, pts, prof, m)
        rec2.calls[-1]["pipeline_inputs"] = inputs  # metrics, manual, opts: for the end-to-end replay
        rows.append((meta, pts))
    if rows:
        sens.sensitivity(rows)
        write(HERE / "results" / "_golden" / "outputs-apps.json", rec2.calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
