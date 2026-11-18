#!/usr/bin/env python3
"""
cli.py — single entry point of the maintainability evaluation framework.

  python cli.py doctor                    checks that the environment has everything it needs
  python cli.py evaluate [apps...]        evaluates each app (tests, DV8, manual templates) and aggregates
  python cli.py report                    generates results/report.md with the results and the pending items

Tokens: the tokens the agent used to create each app (phase initial) and to implement the additional requirements (phase r2)
are recorded with token_usage.py in token-usage/<app>.json; evaluate copies them to results/<run>/token_usage.json and the report
shows them next to the maintainability score (they are not part of it).

Convention: each app is a folder (by default inside apps/). If it is named <agent>-<level> (e.g. claude-n2) or
<agent>-<domain>-<level> (e.g. claude-cinema-n2, where <domain> has a specs/requirements-<domain>.md) the agent, the level and the
domain are deduced from the name; the domain of the name takes precedence over --domain. Options can go in experiment.json (see
experiment.example.json); the command line takes precedence over the file.

Judge: with --judge MODEL (different from the generator) a model decides the pending design-judgment criteria (layers C2, cohesion
C3, data model C1–C6, contracts C4); the range closes only if nothing else is pending (DV8, ESLint, Knip, the tests…); see judge.py. The decisions are saved in results/<run>/judge.json and manual review always overrides them.

Manual review: evaluate leaves results/<run>/manual_review.md and manual_review.draft.json. Copy the draft to
manual_review.json, fill in ok=true/false and run `evaluate --rescore`: it is read automatically and only the scoring is redone.

Collection happens once per app: after DV8, the live database and the judge the run is re-scored from metrics.json
(evaluate.py rescore), not evaluated again.
"""
import argparse, contextlib, datetime, json, os, platform, re, shutil, socket, subprocess, sys
from pathlib import Path

SRC = Path(__file__).resolve().parent  # python/: this reference implementation
HERE = SRC.parent  # repository root: rubric.json, specs/, node_modules/, js/tools/
PY = sys.executable
UTF8 = {**os.environ, "PYTHONIOENCODING": "utf-8"}
sys.path.insert(0, str(SRC))
from dv8_metrics import DV8_DEFAULT  # noqa: E402
import pg_runtime  # noqa: E402
import pg_temp  # noqa: E402
import evaluate as ev  # noqa: E402
import token_usage as tu  # noqa: E402

OK, FAIL, WARN = "✔", "✘", "!"
SYMBOL = {"Meets": "✔", "Partial": "◐", "Fails": "✘"}


TIMEOUT_RC = 124


def execute(cmd, cwd=None, timeout=1800):
    """(returncode, stdout+stderr). A command that exceeds `timeout` returns 124 instead of aborting the whole batch."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=UTF8, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        partial = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return TIMEOUT_RC, partial + f"\nTIMEOUT: the command did not finish within {timeout} s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def version(cmd):
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        rc, out = execute([exe] + cmd[1:], timeout=30)
        return out.strip().splitlines()[-1] if rc == 0 and out.strip() else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def find_dv8():
    for c in (os.environ.get("DV8_CONSOLE"), shutil.which("dv8-console"), DV8_DEFAULT):
        if c and Path(c).exists():
            return c
    return None


# ───────────────────────── doctor ─────────────────────────
def node_version(text):
    """(major, minor, patch) of `node --version` output ("v22.17.1"); (0, 0, 0) when Node is not found."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def node_supported(v):
    """The Node.js lines every required tool runs on: ESLint 10 (^20.19 || ^22.13 || >=24) and Knip 6 (^20.19 || >=22.12)."""
    return (v[0] == 20 and v >= (20, 19, 0)) or (v[0] == 22 and v >= (22, 13, 0)) or v[0] >= 24


def cmd_doctor(a):
    rows = []  # (status, name, detail, help)

    def add(ok, name, detail, help_="", required=True):
        rows.append((OK if ok else (FAIL if required else WARN), name, detail, "" if ok else help_, required))

    add(sys.version_info >= (3, 9), "Python ≥ 3.9", platform.python_version(), "Install Python 3.9 or later (python.org).")
    node = version(["node", "--version"])
    nv = node_version(node)
    add(node_supported(nv), "Node.js 20.19+, 22.13+ or 24+", node or "not found",
        "Install Node.js 22 LTS (nodejs.org): ESLint 10 needs ^20.19 || ^22.13 || >=24 and Knip 6 ^20.19 || >=22.12.")
    add(nv >= (22, 0, 0), "Node.js ≥ 22 for --mutation (optional)", node or "not found",
        "StrykerJS 10 needs Node.js 22 or later; without it --mutation cannot run.", required=False)
    add(bool(shutil.which("npm")), "npm", version(["npm", "--version"]) or "not found", "npm comes with Node.js.")
    missing = [d for d in ("ts-morph", "dependency-cruiser", "knip", "eslint", "eslint-plugin-sonarjs", "typescript-eslint")
               if not (HERE / "node_modules" / d / "package.json").exists()]
    add(not missing, "Evaluator dependencies", "installed" if not missing else "missing: " + ", ".join(missing),
        f"Run 'npm install' in {HERE}. Without ESLint, Configuration C2 (S1192) stays pending and the cognitive complexity and "
        "the ASCMM indicators are not measured.")
    extra = [n for n, p in (("Prism", "@stoplight/prism-cli"), ("StrykerJS", "@stryker-mutator/core")) if not (HERE / "node_modules" / p / "package.json").exists()]
    add(not extra, "Prism and StrykerJS (optional)", "installed" if not extra else "missing: " + ", ".join(extra),
        "Without Prism the runtime conformance to the OpenAPI contract is not measured during the acceptance gate; without StrykerJS "
        f"--mutation is not available. Run 'npm install' in {HERE}.", required=False)
    pg = (HERE / "node_modules" / "pg" / "package.json").exists()
    pg_bin = pg_temp.find_bin()
    server_txt = "; PG_ADMIN_URL set" if os.environ.get("PG_ADMIN_URL") else (f"; temporary server from {pg_bin}" if pg_bin else "; no PG_ADMIN_URL and no PostgreSQL binaries")
    add(pg and bool(os.environ.get("PG_ADMIN_URL") or pg_bin), "PostgreSQL analysis and acceptance gate (optional: --postgres)",
        ("pg installed" if pg else "pg missing") + server_txt,
        "Without it the data model is evaluated from the code only and the acceptance gate does not run. Run 'npm install' and either install "
        "PostgreSQL (a temporary server is started from its initdb/pg_ctl; PG_BIN if they are not found) or set PG_ADMIN_URL (a role with CREATEDB).", required=False)
    try:
        json.loads((HERE / "rubric.json").read_text(encoding="utf-8")); rub = True
    except (OSError, ValueError):
        rub = False
    add(rub, "rubric.json", "valid" if rub else "missing or invalid", "Restore rubric.json from the repository.")
    dv8 = find_dv8()
    status = "not found"
    if dv8:
        try:
            rc, out = execute([dv8, "license:status"], timeout=90)
            status = "valid license" if '"valid"' in out else "invalid license"
        except (subprocess.TimeoutExpired, OSError):
            status = "did not respond"
    add(status == "valid license", "DV8 (optional: DL and PC)", f"{dv8 or '—'} · {status}",
        "Without DV8, DL and PC stay pending; use --skip-dv8 or install DV8 and set DV8_CONSOLE.", required=False)
    compose, why = pg_runtime.docker_status()
    add(compose is not None, "Docker + Compose (optional: acceptance gate)", " ".join(compose) if compose else why,
        "Without Docker, js/run_experiment.mjs skips the acceptance gate (the apps are not checked against PostgreSQL).", required=False)
    try:
        socket.create_connection(("registry.npmjs.org", 443), timeout=5).close(); online = True
    except OSError:
        online = False
    add(online, "Network access to the npm registry (optional)", "reachable" if online else "no access",
        "Without a network, use --offline: versions and vulnerabilities stay pending.", required=False)
    apps = HERE / "apps"
    n = len([d for d in apps.iterdir() if d.is_dir()]) if apps.exists() else 0
    add(n > 0, "apps/ folder", f"{n} application(s)", "Create apps/<agent>-<level>/ with each generated application.", required=False)

    for status, name, detail, help_, _ in rows:
        print(f" {status}  {name:<44} {detail}")
        if help_:
            print(f"      → {help_}")
    blocking = [f for f in rows if f[0] == FAIL]
    print("\n" + ("Environment ready." if not blocking else f"{len(blocking)} required item(s) missing."))
    return 1 if blocking else 0


# ───────────────────────── evaluate ─────────────────────────
def load_config(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def options(a):
    cfg = load_config(a.config)
    def pick(name, default):
        v = getattr(a, name, None)
        return v if v not in (None, False) else cfg.get(name, default)
    return {"apps": a.apps or cfg.get("apps") or None, "apps_dir": pick("apps_dir", "apps"), "results": pick("results", "results"),
            "domain": pick("domain", "ecommerce"), "model": pick("model", None), "allow_missing_model": pick("allow_missing_model", False), "rep": pick("rep", 1),
            "skip_tests": pick("skip_tests", False), "skip_dv8": pick("skip_dv8", False), "offline": pick("offline", False), "as_of": pick("as_of", None),
            "accept_heuristics": pick("accept_heuristics", False), "mutation": pick("mutation", False),
            "judge": pick("judge", None), "judge_votes": pick("judge_votes", 3), "judge_cmd": pick("judge_cmd", None),
            "allow_same_model": pick("allow_same_model", False), "postgres": pick("postgres", False),
            "usage_dir": pick("usage_dir", tu.DEFAULT_DIR),
            "rescore_only": bool(getattr(a, "rescore", False))}  # command line only: never fixed in experiment.json


def known_domains():
    """Domains that have a requirements file: specs/requirements-<domain>.md."""
    return sorted(p.stem[len("requirements-"):] for p in (HERE / "specs").glob("requirements-*.md"))


def identity(name, domains=None):
    """(agent, level, domain) from an app folder named <agent>-<level> or <agent>-<domain>-<level>; domain is None when the name
    does not carry one. A middle part that is not a known domain makes the name unrecognized: (name, "n/a", None)."""
    domains = known_domains() if domains is None else domains
    m = re.fullmatch(r"(?P<ag>[A-Za-z0-9]+)(?:-(?P<dom>[A-Za-z0-9]+))?-(?P<lv>[Nn]\d+)", name)
    if not m or (m["dom"] and m["dom"].lower() not in domains):
        return name, "n/a", None
    return m["ag"].lower(), m["lv"].upper(), (m["dom"] or "").lower() or None


def last_line(output, pattern):
    return next((l.strip() for l in reversed(output.splitlines()) if re.search(pattern, l)), None)


def evaluate_app(app, o, dv8):
    agent, level, named_domain = identity(app.name)
    domain = named_domain or o["domain"]
    # the domain is not repeated when the folder name already carries it: claude-cinema-n1 -> claude-cinema-n1-r1
    run_id = f"{app.name}-r{o['rep']}" if named_domain else f"{app.name}-{domain}-r{o['rep']}"
    out = Path(o["results"]).resolve() / run_id
    cmd = [PY, str(SRC / "evaluate.py"), "run", str(app), "--out", str(out), "--agent", agent, "--model", o["model"] or "n/a",
           "--level", level, "--domain", domain, "--run-id", run_id]
    if ev.model_missing(o["model"]): cmd.append("--allow-missing-model")  # cmd_evaluate already refused unless it was allowed
    if not o["skip_tests"]: cmd.append("--run-tests")
    if not o["skip_tests"] and o.get("mutation"): cmd.append("--mutation")  # mutation testing runs the tests: never with --skip-tests
    if o["offline"]: cmd.append("--offline")
    if o.get("as_of"): cmd += ["--as-of", o["as_of"]]
    if o["accept_heuristics"]: cmd.append("--accept-heuristics")
    warnings = [copy_token_usage(app, out, o["usage_dir"])]
    if o.get("rescore_only"):  # --rescore: the evidence is already collected; only the scoring is redone
        if not (out / "metrics.json").exists():
            return run_id, f"ERROR\nno metrics.json in {out}: evaluate it once without --rescore"
        rc, output = execute(rescore_cmd(out))
        if rc != 0:
            return run_id, f"ERROR\n{output[-800:]}"
        return run_id, "; ".join([final_summary(out)] + [w for w in warnings if w])
    rc, output = execute(cmd)  # the only collection of evidence (tests, npm, jscpd…): every later step just re-scores
    if rc != 0:
        return run_id, f"ERROR\n{output[-800:]}"
    warnings += post_collection_steps(out, o, dv8)
    return run_id, "; ".join([final_summary(out)] + [w for w in warnings if w])


def rescore_cmd(out):
    return [PY, str(SRC / "evaluate.py"), "rescore", str(out)]


def final_summary(out):
    """'Maintainability: a–b/100 · complete=…' of the last scoring of the run (profile.json), after DV8, the database and the judge."""
    f = Path(out) / "profile.json"
    if not f.exists():
        return ""
    p = json.loads(f.read_text(encoding="utf-8"))
    return f"Maintainability: {ev.fmt_rng(p['maintainability_min'], p['maintainability_max'])}/100 · complete={p['complete']}"


def post_collection_steps(out, o, dv8):
    """DV8, manual-review templates, live database and judge on an evaluated run. Each step that changes the inputs of the scoring
    is followed by a re-score from metrics.json (`evaluate.py rescore`), never by a new collection. Returns the warnings."""
    warnings = []

    def rescore(after):
        rc, s = execute(rescore_cmd(out))
        if rc != 0:
            warnings.append(f"re-scoring after {after} failed: " + (last_line(s, r"\S") or ""))
    if dv8:
        rc2, s2 = execute([PY, str(SRC / "dv8_metrics.py"), str(out)] + ([] if dv8 == DV8_DEFAULT else ["--dv8", dv8]))
        if rc2 == 0:
            rescore("DV8")  # brings DL/PC into the profile
        else:
            warnings.append("DV8 failed: " + (last_line(s2, r"\S") or ""))
    execute([PY, str(SRC / "manual_template.py"), str(out)])
    if o["postgres"]:  # real database: catalog of a disposable eval_<run> database (PG_ADMIN_URL or a pg_temp server; see pg_analysis.py)
        if not UTF8.get("PG_ADMIN_URL"):
            warnings.append("--postgres requested but there is no PG_ADMIN_URL and no PostgreSQL binaries for a temporary server: database analysis skipped")
        else:
            rcp, sp = execute([PY, str(SRC / "pg_analysis.py"), str(out)])
            warnings.append("postgres: " + (last_line(sp, r"Acceptance|ERROR") or "no output") if rcp == 0 else "postgres failed: " + (last_line(sp, r"\S") or ""))
            rescore("the live database")  # brings the real database into the profile and the scorecard the judge reads
    if o["judge"]:  # the judge decides what is still pending on design judgment and the run is re-scored with its decisions
        jcmd = [PY, str(SRC / "judge.py"), str(out), "--model", o["judge"], "--votes", str(o["judge_votes"])]
        if o["judge_cmd"]: jcmd += ["--cmd", o["judge_cmd"]]
        if o["allow_same_model"]: jcmd.append("--allow-same-model")
        rcj, sj = execute(jcmd)
        if rcj == 0:
            rescore("the judge")
            warnings.append("judge: " + (last_line(sj, r"Judge|No judgeable") or "no output"))
        else:
            warnings.append("the judge failed: " + (last_line(sj, r"\S") or ""))
    return warnings


def copy_token_usage(app, out, usage_dir):
    """token-usage/<app>.json → results/<run>/token_usage.json (a stale copy is removed when the record no longer exists)."""
    src, dst = tu.usage_path(app, usage_dir), out / tu.RESULT_FILE
    out.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        dst.unlink(missing_ok=True)
        return "tokens not recorded (see js/token_usage.mjs)"
    shutil.copy(src, dst)
    missing = [p for p in ("initial", "r2") if p not in (tu.load(src) or {}).get("phases", {})]
    return f"tokens of phase {', '.join(missing)} not recorded" if missing else None


def record_environment(o, dv8, apps):
    res = Path(o["results"]).resolve(); res.mkdir(parents=True, exist_ok=True)
    rub = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))
    info = {"date": datetime.datetime.now().isoformat(timespec="seconds"), "python": platform.python_version(),
            "node": version(["node", "--version"]), "npm": version(["npm", "--version"]), "os": platform.platform(),
            "generator_model": None if ev.model_missing(o["model"]) else o["model"], "generator_model_missing": ev.model_missing(o["model"]),
            "dv8": dv8, "apps": [a.name for a in apps], "options": {k: v for k, v in o.items() if k != "apps"},
            "supported_runtimes": rub.get("supported_runtimes", {}).get("date"),
            # reference date of versions, advisories and supported runtimes (Technologies); the evaluation date when not fixed
            "as_of": o.get("as_of") or datetime.date.today().isoformat()}
    (res / "environment.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")


def cmd_evaluate(a):
    o = options(a)
    if ev.model_missing(o["model"]) and not o["allow_missing_model"]:
        print("ERROR: " + ev.MODEL_ERROR)
        return 2
    if o["apps"]:
        apps = [Path(p).resolve() for p in o["apps"]]
    else:
        base = Path(o["apps_dir"])
        apps = sorted(d.resolve() for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")) if base.exists() else []
    missing = [p for p in apps if not p.is_dir()]
    if not apps or missing:
        print("No applications to evaluate." if not apps else "Does not exist: " + ", ".join(map(str, missing)))
        print("Create apps/<agent>-<level>/ or pass the folders: python cli.py evaluate path/app1 path/app2")
        return 1
    dv8 = None if (o["skip_dv8"] or o["rescore_only"]) else find_dv8()
    if not o["skip_dv8"] and not o["rescore_only"] and not dv8:
        print("Warning: DV8 not found; DL and PC will stay pending (use --skip-dv8 to silence this warning).")
    if not o["rescore_only"]:  # environment.json describes the collection; re-scoring keeps it
        record_environment(o, dv8, apps)
    errors = 0
    with contextlib.ExitStack() as stack:
        if o["postgres"] and not o["rescore_only"] and not UTF8.get("PG_ADMIN_URL"):
            # No server given: a disposable one (pg_temp.py) for the whole batch, stopped and deleted at the end
            try:
                url = stack.enter_context(pg_temp.server())
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
                url = None
                print(f"Warning: the temporary PostgreSQL server could not start ({e}).")
            if url:
                UTF8["PG_ADMIN_URL"] = url  # only for the evaluator's child processes; pg_analysis.py does not pass it to the backend
                print(f"PostgreSQL: temporary server on 127.0.0.1:{url.rsplit(':', 1)[1].split('/')[0]} (no PG_ADMIN_URL set).")
        for i, app in enumerate(apps, 1):
            print(f"[{i}/{len(apps)}] {app.name} …", flush=True)
            run_id, summary = evaluate_app(app, o, dv8)
            errors += summary.startswith("ERROR")
            print(f"      {summary}")
        if not os.environ.get("PG_ADMIN_URL"):
            UTF8.pop("PG_ADMIN_URL", None)  # the temporary server stops here: nothing after the batch may point at it
    rc, output = execute([PY, str(SRC / "evaluate.py"), "aggregate", str(Path(o["results"]).resolve())])
    if rc != 0:
        print("Error while aggregating:\n" + output[-600:]); return 1
    path = write_report(Path(o["results"]).resolve())
    print(f"\nReport: {path}")
    return 1 if errors else 0


# ───────────────────────── report ─────────────────────────
LIGHT = {"green": "🟢", "yellow": "🟡", "red": "🔴", "undecided": "⚪", "not_evaluable": "▨"}


def level_txt(p):
    if p.get("evaluable") is False:
        return "▨"
    if p["level"]:
        return SYMBOL[p["level"]]
    lo, hi = p.get("level_min"), p.get("level_max")
    return f"{SYMBOL.get(lo, '?')}…{SYMBOL.get(hi, '?')}" if lo and hi else "?"


def fmt_range(lo, hi):
    return "n/a" if lo is None else (f"{lo:.1f}" if lo == hi else f"{lo:.1f}–{hi:.1f}")


def native_coverage_runs(runs):
    """Runs whose `node --test` coverage was measured without c8 (runner "node:test" in metrics.json): their branches are overestimated."""
    out = []
    for d, pf, _ in runs:
        try:
            m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if any(p.get("runner") == "node:test" for p in (m.get("tests_run") or {}).get("packages", [])):
            out.append(pf["meta"]["run_id"])
    return out


def write_report(res):
    runs = []
    for d in sorted(res.iterdir()):
        if (d / "profile.json").exists() and (d / "scorecard.json").exists():
            runs.append((d, json.loads((d / "profile.json").read_text(encoding="utf-8")), json.loads((d / "scorecard.json").read_text(encoding="utf-8"))["points"]))
    if not runs:
        raise SystemExit(f"No results in {res}. Run first: python cli.py evaluate")
    env = json.loads((res / "environment.json").read_text(encoding="utf-8")) if (res / "environment.json").exists() else {}
    ids = [p["id"] for p in runs[0][2]]; names = {p["id"]: p["name"] for p in runs[0][2]}
    subs = list(runs[0][1]["subcharacteristics"])
    no_model = [r[1]["meta"]["run_id"] for r in runs if ev.model_missing(r[1]["meta"].get("model"))]
    model_txt = env.get("generator_model") or ("NOT RECORDED" if no_model else "")
    L = ["# Maintainability report", "", f"Generated: {datetime.datetime.now():%Y-%m-%d %H:%M} · {len(runs)} application(s)" + (f" · Generator model: {model_txt}" if model_txt else ""), "",
         *([f"> ⚠ **Generator model not recorded** for {', '.join(no_model)}. {ev.MODEL_WARNING}", ""] if no_model else []),
         "## Overall result (0–100)", "",
         "| Application | Level | Overall | " + " | ".join(subs) + " | Complete |", "|---|---|---|" + "---|" * len(subs) + "---|"]
    for d, pf, pts in runs:
        m = pf["meta"]
        L.append(f"| {m['run_id']} | {m['level']} | **{fmt_range(pf['maintainability_min'], pf['maintainability_max'])}** | "
                 + " | ".join(fmt_range(pf["subcharacteristics"][s]["min"], pf["subcharacteristics"][s]["max"]) for s in subs)
                 + f" | {'yes' if pf['complete'] else 'no'} |")
    L += ["", "A range (a–b) indicates pending criteria: the real value lies between both ends until the manual review is completed.", ""]
    L += ev.sensitivity_md(ev.sensitivity([(pf["meta"], pts) for _, pf, pts in runs]))
    L += ["## Risk dashboard", "",
          "Semaphore per subcharacteristic (weighted score, worst case of the range; cut-offs in `rubric.json`). A high-severity finding forces red (↑). "
          "▨ = not evaluable for lack of evidence. Each application folder has `risk_dashboard.html` / `.md` with the full points × subcharacteristics heat map and the module hotspots.", "",
          "| Application | " + " | ".join(subs) + " |", "|---|" + "---|" * len(subs)]
    for d, pf, pts in runs:
        sem = pf.get("dashboard", {}).get("semaphore", {})
        L.append(f"| {pf['meta']['run_id']} | " + " | ".join(
            (LIGHT[sem[x]["state"]] + (" ↑" if sem[x]["escalated"] else "") + " " + fmt_range(sem[x]["min"], sem[x]["max"])) if x in sem else "?" for x in subs) + " |")
    ne = [(pf["meta"]["run_id"], x["name"], x["missing"]) for d, pf, pts in runs for x in pf.get("dashboard", {}).get("not_evaluable", [])]
    L += ["", "**Not evaluable (no evidence):** " + ("; ".join(f"{r}: {n} (missing {', '.join(m)})" for r, n, m in ne) if ne else "none"), ""]
    L += ["### Hotspots (worst files per automatable indicator)", ""]
    for d, pf, pts in runs:
        hs = pf.get("dashboard", {}).get("hotspots", {})
        parts = [f"{t}: " + ", ".join(f"`{x['file']}` ({x['detail']})" for x in hs.get(k, [])[:2]) for k, t in (("complexity", "complexity"), ("layer_violations", "layers"), ("cyclic_dependencies", "cycles")) if hs.get(k)]
        L.append(f"- **{pf['meta']['run_id']}** — " + ("; ".join(parts) or "none"))
    arts = {d.name: json.loads((d / "artifacts.json").read_text(encoding="utf-8")) for d, _, _ in runs if (d / "artifacts.json").exists()}
    if arts:
        first = next(iter(arts.values()))
        L += ["", "## Input artifacts (Table 27)", "",
              "✔ present · ✘ missing. Core artifacts missing make their points not evaluable; complementary ones are recorded as findings and lower confidence "
              "(a missing test suite is a High finding); optional ones only enrich the analysis. Details per application in `artifacts.json`.", "",
              "| Artifact | Level | Feeds | " + " | ".join(arts) + " |", "|---|---|---|" + "---|" * len(arts)]
        for i, a in enumerate(first):
            L.append(f"| {a['name']} | {a['level']} | {', '.join(a['feeds']) or '—'} | "
                     + " | ".join(("✔" if v[i]["present"] else "✘") for v in arts.values()) + " |")
    L += [""] + ev.ascmm_comparison_md([(pf["meta"]["run_id"], pf) for _, pf, _ in runs])
    L += token_section(runs)
    L += ["",
          "## Risk heat map", "",
          "🔴 Fails · 🟡 Partial · 🟢 Meets · ⚪ undecided (pending criteria). Rows are ordered by how much of the overall score each point "
          "puts at stake, so the riskiest points come first.", "",
          "| Point | " + " | ".join(r[1]["meta"]["run_id"] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    order = {r["id"]: i for i, r in enumerate(max((pf.get("risk", []) for _, pf, _ in runs), key=lambda x: sum(y["at_stake_max"] for y in x), default=[]))}
    for pid in sorted(ids, key=lambda i: order.get(i, 99)):
        L.append(f"| {names[pid]} | " + " | ".join(
            next((f"{x['light']} {x['at_stake_max']:.1f}" for x in pf.get("risk", []) if x["id"] == pid), "▨ not evaluable") for _, pf, _ in runs) + " |")
    L += ["", "Each cell: traffic light and overall points at stake in the worst case.", "", "### Top risks per application", ""]
    for d, pf, pts in runs:
        top = [x for x in pf.get("risk", []) if x["at_stake_max"] > 0][:3]
        L.append(f"- **{pf['meta']['run_id']}** — " + ("; ".join(f"{x['light']} {x['name']} ({x['at_stake_max']:.1f} pts)" for x in top) or "no points at risk"))
    L += ["",
          "## Decision points", "", "✔ Meets · ◐ Partial · ✘ Fails · a…b range due to pending criteria · ? not evaluated", "",
          "| Point | " + " | ".join(r[1]["meta"]["run_id"] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    for pid in ids:
        L.append(f"| {names[pid]} | " + " | ".join(level_txt(next(p for p in pts if p["id"] == pid)) for _, _, pts in runs) + " |")
    L += ["", "## Pending manual review", ""]
    any_pending = False
    for d, pf, pts in runs:
        pend = [(p["id"], p["pending_criteria"]) for p in pts if p["pending_criteria"]]
        if pend:
            any_pending = True
            L.append(f"- **{pf['meta']['run_id']}** — " + "; ".join(f"{i}: {', '.join(c)}" for i, c in pend) + f" → `{d.name}/manual_review.md`")
    L += ([] if any_pending else ["None."]) + ["", "## Findings per application", ""]
    for d, pf, pts in runs:
        L.append(f"### {pf['meta']['run_id']}")
        for p in pts:
            if p["level"] in ("Partial", "Fails") or (not p["level"] and p["level_min"] != p["level_max"]):
                L.append(f"- **{p['name']}** ({level_txt(p)}): {p['finding']}")
        L.append("")
    for d, pf, pts in runs:
        fs = pf.get("artifact_findings", [])
        if fs:
            L.append(f"### {pf['meta']['run_id']} — findings from missing artifacts")
            L += [f"- **{f['severity']}** — {f['name']}: {f['note']}" for f in fs] + [""]
    warn = ["Each level has a single run: differences between levels are not statistically conclusive.",
            "Unless acceptance.json is present, the applications were not run against PostgreSQL (no acceptance gate): it is not known whether they work.",
            "Layer classification is a directory-name heuristic; review `detected_layers.json`."]
    native = native_coverage_runs(runs)
    if native:
        warn.append(f"Test coverage of {', '.join(native)} was measured with Node's native coverage because c8 was not installed: files that no "
                    "test loads count as 0% of lines, but their branches do not enter the denominator (branches overestimated).")
    if any((d / tu.RESULT_FILE).exists() for d, _, _ in runs):
        warn.append("Tokens come from the agents' own usage records (Claude Code transcripts or results, Codex rollouts) normalized so that input "
                    "includes the cache; a cache read is much cheaper than a fresh input token, so compare totals between agents with care.")
    if any((d / "dv8" / "dv8_metrics.json").exists() for d, _, _ in runs):
        warn.append("DV8's DL and PC are computed on a matrix derived from dependency-cruiser (DV8 does not analyze JS/TS) and without isolated files.")
    if no_model:
        warn.append(ev.MODEL_WARNING)
    L += ["## Methodological warnings", ""] + [f"- {x}" for x in warn]
    if env:
        L += ["", "## Environment", "", f"Python {env.get('python')} · Node {env.get('node')} · npm {env.get('npm')} · DV8: {env.get('dv8') or 'not used'}",
              f"System: {env.get('os')} · evaluated on {env.get('date')} · versions and advisories as of {env.get('as_of') or env.get('date', '')[:10]}"
              f"{'' if (env.get('options') or {}).get('as_of') else ' (the evaluation date: fix it with --as-of to reproduce the result)'}"
              f" · supported-runtimes table dated {env.get('supported_runtimes')}"]
    path = res / "report.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


def token_section(runs):
    """AI token consumption per application: creation (initial) and additional requirements (r2), from results/<run>/token_usage.json."""
    data = {pf["meta"]["run_id"]: tu.load(d / tu.RESULT_FILE) for d, pf, _ in runs}
    if not any(data.values()):
        return ["", "## AI token consumption", "", "Not recorded. Record the tokens of each phase with `node js/token_usage.mjs scan` and `record` "
                "(see docs/generating-apps.md) and run evaluate again."]
    L = ["", "## AI token consumption", "",
         "Tokens the generator agent used to create the application (**initial**) and to implement the additional requirements (**R2**). "
         "Input includes the prompt-cache reads and writes; output includes reasoning. They are not part of the maintainability score. "
         "Details per session in `<run>/token_usage.json`.", "",
         "| Application | Initial input | Initial output | **Initial total** | R2 input | R2 output | **R2 total** | R2 / initial | Initial + R2 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for rid, u in data.items():
        sm = tu.summary(u) or {"phases": {}}
        i, r = sm["phases"].get("initial"), sm["phases"].get("r2")
        def g(t, k):
            return tu.fmt(t[k]) if t else "—"
        ratio = (sm.get("r2_vs_initial") or {}).get("total_tokens")
        both = tu.fmt(i["total_tokens"] + r["total_tokens"]) if i and r else "—"
        L.append(f"| {rid} | {g(i, 'input_tokens')} | {g(i, 'output_tokens')} | **{g(i, 'total_tokens')}** | {g(r, 'input_tokens')} | "
                 f"{g(r, 'output_tokens')} | **{g(r, 'total_tokens')}** | {'—' if ratio is None else f'×{ratio:.2f}'} | {both} |")
    return L


def cmd_report(a):
    path = write_report(Path(a.results or "results").resolve())
    print(path.read_text(encoding="utf-8"))
    print(f"(saved to {path})")
    return 0


def main():
    for s_ in (sys.stdout, sys.stderr):  # Windows console (cp1252): avoids UnicodeEncodeError with →, ·, ≥
        s_.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor", help="check the environment").set_defaults(fn=cmd_doctor)
    e = sp.add_parser("evaluate", help="evaluate the applications"); e.set_defaults(fn=cmd_evaluate)
    e.add_argument("apps", nargs="*", help="app folders (by default, all of those in --apps-dir)")
    e.add_argument("--config", default="experiment.json")
    e.add_argument("--apps-dir"); e.add_argument("--results"); e.add_argument("--domain"); e.add_argument("--model", help="REQUIRED: the model that generated the applications")
    e.add_argument("--rep", type=int)
    e.add_argument("--allow-missing-model", action="store_true", default=None, dest="allow_missing_model",
                   help="evaluate without --model (profile.md and report.md carry a warning)")
    e.add_argument("--judge", help="judge model that decides the design-judgment criteria (must differ from the generator)")
    e.add_argument("--judge-votes", type=int, dest="judge_votes"); e.add_argument("--judge-cmd", dest="judge_cmd")
    e.add_argument("--allow-same-model", action="store_true", default=None)
    e.add_argument("--postgres", action="store_true", default=None, help="acceptance gate and real-database analysis (pg_analysis.py) on PG_ADMIN_URL, or on a temporary server started from the local PostgreSQL binaries")
    e.add_argument("--mutation", action="store_true", default=None, help="mutation testing with StrykerJS on the apps' own tests (slow: up to "
                                                                       "rubric.json mutation.max_minutes_per_package per package; informational; not with --skip-tests)")
    e.add_argument("--usage-dir", dest="usage_dir", help="folder of the token records written by token_usage.py (default token-usage)")
    e.add_argument("--rescore", action="store_true", help="do not collect again: re-score the evaluated apps from results/<run>/metrics.json "
                                                          "(after filling manual_review.json, editing dv8_manual.json or changing the rubric)")
    for f in ("skip-tests", "skip-dv8", "offline", "accept-heuristics"):
        e.add_argument("--" + f, action="store_true", default=None)
    e.add_argument("--as-of", dest="as_of", help="reference date YYYY-MM-DD of the versions, advisories and supported runtimes (default: "
                                                 "today). Fix it, for example to the generation date, to get the same result when evaluating again")
    i = sp.add_parser("report", help="generate the report"); i.set_defaults(fn=cmd_report); i.add_argument("--results")
    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
