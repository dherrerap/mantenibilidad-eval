#!/usr/bin/env python3
"""
record_collect.py — Golden cases for the JavaScript port of the collectors: the metrics.json that Python's collect() produces for an
app, plus every network answer it received (npm registry, the lockfile npm resolved, OSV, endoflife.date), so that the JavaScript
collect() can run on the same app with the same answers and be compared field by field.

  python tests/golden/record_collect.py [app …]      (default: every folder of apps/ and the fixture apps of tests/fixtures/)

Writes results/_golden/collect/<name>.json (local only: absolute paths, and the generated apps are not versioned). The tools
themselves (ast_metrics.js, dependency-cruiser, jscpd, Spectral, Knip, ESLint) are run again by the JavaScript side: they are
deterministic for the same input.
"""
import copy, json, os, sys, tempfile, urllib.request
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
os.chdir(HERE)
import evaluator.collectors as col  # noqa: E402
from evaluator.collectors import packages as pk, osv  # noqa: E402

AS_OF = "2026-11-16"
WITH_TESTS = {"mutation_app"}  # fixtures whose tests run without installing anything
FIXTURES = ["sequelize_app", "sequelize_models_only", "knip_app", "lint_app", "conformance_app", "mutation_app"]


def record(app, run_tests=False):
    cache = {"npm": [], "lock": [], "post": [], "get": [], "url": []}
    orig = (pk.npm_json, pk.resolve_lock, osv.post, osv.get, urllib.request.urlopen)

    def npm_json(args):
        r = orig[0](args); cache["npm"].append({"args": list(args), "result": r}); return r

    def resolve_lock(d, as_of):
        lock, src = orig[1](d, as_of)
        cache["lock"].append({"dir": Path(d).resolve().relative_to(app).as_posix() or ".", "as_of": as_of, "lock": lock, "source": src}); return lock, src

    def post(url, body, timeout=60):
        r = orig[2](url, body, timeout); cache["post"].append({"url": url, "body": body, "result": r}); return r

    def get(url, timeout=60):
        r = orig[3](url, timeout); cache["get"].append({"url": url, "result": r}); return r

    class Resp:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(url, *a, **k):  # endoflife.date (fetch_eol); OSV goes through post/get above
        u = url if isinstance(url, str) else url.full_url
        try:
            with orig[4](url, *a, **k) as r:
                data = r.read()
        except Exception as e:
            cache["url"].append({"url": u, "error": str(e)}); raise
        cache["url"].append({"url": u, "body": data.decode("utf-8")})
        return Resp(data)

    pk.npm_json, pk.resolve_lock, osv.post, osv.get, urllib.request.urlopen = npm_json, resolve_lock, post, get, urlopen
    try:
        opts = SimpleNamespace(as_of=AS_OF, offline=False, run_tests=run_tests, mutation=run_tests, test_cmd=None, layers=None)
        with tempfile.TemporaryDirectory() as t:
            m = col.collect(app, Path(t), opts)
            m = json.loads(json.dumps(m, ensure_ascii=False, default=str))  # what metrics.json would hold
    finally:
        pk.npm_json, pk.resolve_lock, osv.post, osv.get, urllib.request.urlopen = orig
    return {"app": str(app), "as_of": AS_OF, "opts": {"as_of": AS_OF, "offline": False, "run_tests": run_tests, "mutation": run_tests}, "network": cache, "metrics": m}


def main(argv):
    apps = [Path(a).resolve() for a in argv] or (
        sorted(d.resolve() for d in (HERE / "apps").iterdir() if d.is_dir()) if (HERE / "apps").is_dir() else []) + \
        [(HERE / "tests" / "fixtures" / f).resolve() for f in FIXTURES if (HERE / "tests" / "fixtures" / f).is_dir()]
    out = HERE / "results" / "_golden" / "collect"; out.mkdir(parents=True, exist_ok=True)
    for app in apps:
        print(f"collect {app.name} …", flush=True)
        rec = record(app)
        (out / f"{app.name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        if app.name in WITH_TESTS:  # also with --run-tests --mutation (the app's own tests, c8 coverage, StrykerJS)
            # on a copy: running the tests installs and writes coverage, which must not change the fixture (nor the next run)
            import shutil
            tmp = Path(tempfile.mkdtemp(prefix="eval-golden-")) / app.name
            shutil.copytree(app, tmp)
            try:
                rec_t = record(tmp.resolve(), run_tests=True)
            finally:
                shutil.rmtree(tmp.parent, ignore_errors=True)
            rec_t["source"] = app.relative_to(HERE).as_posix()  # the JavaScript test copies this folder again
            (out / f"{app.name}-tests.json").write_text(json.dumps(rec_t, ensure_ascii=False), encoding="utf-8")
            print(f"  with tests: tests_run executed={rec_t['metrics']['tests_run'].get('executed')}, mutation ok={rec_t['metrics'].get('mutation', {}).get('ok')}")
        n = rec["network"]
        print(f"  {len(rec['metrics'])} keys; network: {len(n['npm'])} npm view, {len(n['lock'])} lockfiles, {len(n['post'])}+{len(n['get'])} OSV, {len(n['url'])} endoflife")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
