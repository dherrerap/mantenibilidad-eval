#!/usr/bin/env python3
"""
record_relational.py — Golden cases for the JavaScript port of relational_schema.py and relational_analysis.py.

Wraps the public functions of both modules, runs the whole Python test suite and evaluates the applications in apps/ (when there
are any), and records every distinct call as {fn, args, result}. The JavaScript port must return exactly the same JSON for the same
arguments (tests/js/relational.test.mjs).

  python python/golden/record_relational.py

Writes:
  tests/golden/relational.json         calls made by the test suite (committed: the fixtures are part of the repository)
  results/_golden/relational-apps.json calls on the generated apps (local only: apps/ is not versioned)

The rubric's `relational` section, passed to almost every function, is written once as {"$R": true}.
"""
import copy, functools, hashlib, json, os, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE / "python")); sys.path.insert(0, str(HERE / "python" / "tests"))
os.chdir(HERE)
import relational_schema as rs  # noqa: E402
import relational_analysis as ra  # noqa: E402
import evaluate as ev  # noqa: E402

R = ev.RUBRIC["relational"]
PUBLIC = {
    rs: ["ident_name", "qname_table", "fold", "snake", "singular", "plural", "clean_and_split", "mask", "split_top", "match_paren", "col_list",
         "type_family", "sequelize_type", "secondary_store", "path_tokens", "table_for_model", "extract", "summary"],
    ra: ["from_catalog", "parse_er", "er_searched", "norm_entity", "card_flags", "compare_er", "tables_without_pk", "polymorphic_references",
         "implicit_relations", "unique_sets", "constraint_stats", "leading_columns", "resolve_column", "sql_filters", "index_analysis",
         "repeating_groups", "denormalized_copies", "type_conflicts", "duplicate_tables"],
}
MAX_PER_FN = 300


def to_json(x):
    if x is R:
        return {"$R": True}
    if isinstance(x, dict):
        return {str(k): to_json(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_json(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(to_json(v) for v in x)
    if isinstance(x, Path):
        return str(x)
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    raise TypeError(type(x).__name__)


class Recorder:
    def __init__(self):
        self.calls, self.seen, self.count, self.depth = [], set(), {}, 0

    def wrap(self, mod, name):
        fn = getattr(mod, name)

        @functools.wraps(fn)
        def inner(*args, **kw):
            top = self.depth == 0
            try:
                before = to_json([copy.deepcopy(a) if a is not R else R for a in args]) if top else None
                kw_json = to_json(kw) if top else None
            except TypeError:
                before = None
            self.depth += 1
            try:
                result = fn(*args, **kw)
            finally:
                self.depth -= 1
            # only calls made from outside the two modules: the internal ones are covered by them
            if top and before is not None:
                try:
                    rec = {"fn": f"{mod.__name__}.{name}", "args": before, "kwargs": kw_json, "result": to_json(result)}
                except TypeError:
                    return result
                key = hashlib.sha256(json.dumps([rec["fn"], rec["args"], rec["kwargs"]], sort_keys=True).encode()).hexdigest()
                if key not in self.seen and self.count.get(rec["fn"], 0) < MAX_PER_FN:
                    self.seen.add(key); self.count[rec["fn"]] = self.count.get(rec["fn"], 0) + 1
                    self.calls.append(rec)
            return result
        return inner

    def install(self):
        saved = []
        for mod, names in PUBLIC.items():
            for n in names:
                saved.append((mod, n, getattr(mod, n)))
                setattr(mod, n, self.wrap(mod, n))
        # the modules that imported the names directly (`from relational_schema import fold`) must see the wrappers too
        for m in list(sys.modules.values()):
            for mod, n, orig in saved:
                if m not in (rs, ra) and getattr(m, n, None) is orig and getattr(m, "__name__", "").split(".")[0] in ("relational_analysis", "evaluator", "evaluate", "test_evaluator", "manual_template", "judge", "pg_analysis"):
                    setattr(m, n, getattr(mod, n))
        return saved


def write(path, calls):
    for c in calls:  # the AST's absolute app folder is not read by extract and would put local paths in the golden file
        if c["fn"] == "relational_schema.extract" and len(c["args"]) > 1 and isinstance(c["args"][1], dict) and "root" in c["args"][1]:
            c["args"][1]["root"] = "<app>"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"R": R, "calls": calls}, ensure_ascii=False, indent=0), encoding="utf-8")
    by = {}
    for c in calls:
        by[c["fn"]] = by.get(c["fn"], 0) + 1
    print(f"{path}: {len(calls)} calls ({', '.join(f'{k.split('.')[1]} {v}' for k, v in sorted(by.items()))})")


def main():
    # 1. the test suite
    rec = Recorder()
    rec.install()
    import test_evaluator  # noqa: F401  (imported after install: its `from … import` names get the wrappers)
    suite = unittest.defaultTestLoader.loadTestsFromName("test_evaluator")
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    if not result.wasSuccessful():
        sys.exit(f"the Python test suite fails ({len(result.failures)} failures, {len(result.errors)} errors): fix it before recording")
    # 2. load_er on the ER fixtures, read from disk. Paths are recorded relative to the repository (resolved again by the JS test),
    #    and er_searched / version_dir / find_file are covered through it.
    for d in sorted((HERE / "tests" / "fixtures" / "er_versions").iterdir()):
        rel_ = d.relative_to(HERE).as_posix()
        rec.calls.append({"fn": "relational_analysis.load_er", "args": [rel_, {"$R": True}], "kwargs": {}, "result": to_json(ra.load_er(d, R))})
    write(HERE / "tests" / "golden" / "relational.json", rec.calls)

    # 3. the generated apps, from their last evaluation (ast.json) and their SQL files
    apps = sorted(d for d in (HERE / "apps").iterdir() if d.is_dir()) if (HERE / "apps").is_dir() else []
    if not apps:
        return 0
    from evaluator.collectors.documents import read_sql_files
    calls = []
    for app in apps:
        runs = sorted((HERE / "results").glob(f"{app.name}-*"))
        ast_f = next((r / "ast.json" for r in runs if (r / "ast.json").exists()), None)
        if not ast_f:
            continue
        ast = json.loads(ast_f.read_text(encoding="utf-8"))
        s = rs.extract(read_sql_files(app), ast, R)
        er = ra.load_er(app, R)
        calls.append({"fn": "relational_schema.extract", "args": to_json([read_sql_files(app), ast, R]), "kwargs": {}, "result": to_json(s)})
        calls.append({"fn": "relational_analysis.parse_er", "args": [er["text"]], "kwargs": {}, "result": to_json(ra.parse_er(er["text"]))})
        if er["diagram"]:
            calls.append({"fn": "relational_analysis.compare_er", "args": to_json([er, s, R]), "kwargs": {}, "result": to_json(ra.compare_er(er, s, R))})
        q = list(ast.get("queryFields", [])) + ra.sql_filters(ast.get("sqlStrings", []), s)
        calls.append({"fn": "relational_analysis.sql_filters", "args": to_json([ast.get("sqlStrings", []), s]), "kwargs": {}, "result": to_json(ra.sql_filters(ast.get("sqlStrings", []), s))})
        calls.append({"fn": "relational_analysis.index_analysis", "args": to_json([s, q, 20.0, s.get("model_tables")]), "kwargs": {}, "result": to_json(ra.index_analysis(s, q, 20.0, s.get("model_tables")))})
        for fn in ("tables_without_pk", "polymorphic_references", "repeating_groups", "type_conflicts", "duplicate_tables"):
            calls.append({"fn": f"relational_analysis.{fn}", "args": to_json([s]), "kwargs": {}, "result": to_json(getattr(ra, fn)(s))})
        for fn in ("implicit_relations", "constraint_stats"):
            calls.append({"fn": f"relational_analysis.{fn}", "args": to_json([s, R]), "kwargs": {}, "result": to_json(getattr(ra, fn)(s, R))})
        calls.append({"fn": "relational_analysis.denormalized_copies", "args": to_json([s, er["text"], R]), "kwargs": {}, "result": to_json(ra.denormalized_copies(s, er["text"], R))})
        pg = next((r / "pg_schema.json" for r in runs if (r / "pg_schema.json").exists()), None)
        if pg:
            cat = json.loads(pg.read_text(encoding="utf-8"))
            calls.append({"fn": "relational_analysis.from_catalog", "args": to_json([cat, R]), "kwargs": {}, "result": to_json(ra.from_catalog(cat, R))})
    write(HERE / "results" / "_golden" / "relational-apps.json", calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
