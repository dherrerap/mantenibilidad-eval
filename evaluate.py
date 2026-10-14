#!/usr/bin/env python3
"""
evaluate.py — Automatización del marco de evaluación de mantenibilidad (PIA-02).

Aplica el protocolo de la sección 5.3.3 sobre una aplicación MERN generada por un
agente: recolecta evidencia (pasos 2-4), evalúa los 11 puntos de decisión con la
rúbrica de la Tabla 26 (paso 5-7), arma la matriz de trazabilidad (paso 8) y aplica
el esquema de ponderación (paso 9). Lo que no es automatizable queda explícitamente
"pendiente" y se reporta como un RANGO [mínimo, máximo] hasta que el evaluador lo
complete en manual.json.

USO
  python3 evaluate.py run <app_dir> --out resultados/claude-n2-ecommerce \
        --agente claude --modelo "claude-sonnet-5-5" --nivel N2 --dominio ecommerce \
        [--run-tests] [--test-cmd "npm test -- --coverage ..."] [--offline]
        [--aceptar-heuristicas] [--manual manual.json] [--layers layers.json]
  python3 evaluate.py aggregate resultados/ [--out resultados/_comparativo]

SEGURIDAD: --run-tests instala dependencias y ejecuta código generado por un LLM
(no confiable). Úsalo dentro de un contenedor/VM desechable.
"""
import argparse, csv, datetime, json, os, re, shutil, statistics, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "node_modules" / ".bin"
RUBRIC = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))
SKIP_DIRS = {"node_modules", "dist", "build", "coverage", ".git", ".next", "out"}
NIVELES = ["No cumple", "Parcial", "Cumple"]


# ───────────────────────── utilidades ─────────────────────────
def sh(cmd, cwd=None, timeout=600, env=None):
    cmd = [shutil.which(cmd[0]) or cmd[0]] + list(cmd[1:])  # Windows: npm -> npm.cmd
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def walk(app):
    for d, dirs, files in os.walk(app):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".git")]
        for f in files:
            yield Path(d) / f


def rel(p, app):
    return Path(p).resolve().relative_to(Path(app).resolve()).as_posix()


def glob_to_re(g):
    g = re.escape(g).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.compile("^" + g + "$")


def pct(a, b):
    return None if not b else 100.0 * a / b


def median(xs):
    return statistics.median(xs) if xs else None


# ───────────────────────── recolección ─────────────────────────
def find_packages(app):
    return sorted({p.parent for p in walk(app) if p.name == "package.json"})


def read_pkg(d):
    try:
        return json.loads((d / "package.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_ast(app, out):
    f = out / "ast.json"
    rc, so, se = sh(["node", str(HERE / "ast_metrics.js"), str(app), str(f)], timeout=600)
    if rc != 0:
        raise SystemExit(f"ast_metrics.js falló:\n{se or so}")
    return json.loads(f.read_text(encoding="utf-8"))


def run_depcruise(app, out):
    cfg = {
        "forbidden": [{"name": "no-circular", "severity": "warn", "from": {}, "to": {"circular": True}}],
        "options": {
            "doNotFollow": {"path": "node_modules"},
            "exclude": {"path": r"(^|/)(node_modules|dist|build|coverage|\.git)/|(__tests__|__mocks__)|\.(test|spec)\.[cm]?[jt]sx?$|(^|/)(tests?|e2e|cypress)/"},
            "moduleSystems": ["es6", "cjs"],
            "tsPreCompilationDeps": True,
        },
    }
    cfgf = out / "depcruise.config.json"
    cfgf.write_text(json.dumps(cfg), encoding="utf-8")
    rc, so, se = sh([str(BIN / "depcruise"), "--config", str(cfgf), "--output-type", "json", "."], cwd=app, timeout=600)
    try:
        data = json.loads(so)
    except Exception:
        return {"error": (se or so)[:500], "modules": [], "cycles": []}
    mods, cycles = [], set()
    for m in data.get("modules", []):
        deps = []
        for d in m.get("dependencies", []):
            local = not d.get("coreModule") and not d.get("couldNotResolve") and "node_modules" not in d.get("resolved", "")
            deps.append({"to": d.get("resolved"), "local": local, "module": d.get("module")})
        mods.append({"source": m["source"], "deps": deps})
    for v in data.get("summary", {}).get("violations", []):
        c = v.get("cycle")
        if c:
            names = [x["name"] if isinstance(x, dict) else x for x in c]
            cycles.add(tuple(sorted(set(names))))
    return {"modules": mods, "cycles": [list(c) for c in sorted(cycles)]}


def run_depcheck(pkgdir, include_dev):
    rc, so, se = sh([str(BIN / "depcheck"), str(pkgdir), "--json"], timeout=300)
    try:
        d = json.loads(so)
    except Exception:
        return None
    unused = list(d.get("dependencies", []))
    if include_dev:
        unused += d.get("devDependencies", [])
    return unused


def coerce_version(spec):
    m = re.search(r"(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?", spec or "")
    if not m or re.match(r"^(git|http|file|link|workspace)", spec or ""):
        return None
    return ".".join(x if (x and x.isdigit()) else "0" for x in m.groups())


def npm_view(args):
    pkg, spec = args
    base = coerce_version(spec)
    r = {"pkg": pkg, "spec": spec, "base": base, "latest": None, "deprecated": None}
    rc, so, _ = sh(["npm", "view", pkg, "dist-tags.latest", "--json"], timeout=60)
    if rc == 0:
        try:
            r["latest"] = json.loads(so)
        except Exception:
            pass
    if base:
        rc, so, _ = sh(["npm", "view", f"{pkg}@{base}", "deprecated", "--json"], timeout=60)
        if rc == 0 and so.strip():
            try:
                r["deprecated"] = json.loads(so) or None
            except Exception:
                pass
    return r


def run_audit(pkgdir):
    with tempfile.TemporaryDirectory() as t:
        for fn in ("package.json", "package-lock.json"):
            if (pkgdir / fn).exists():
                shutil.copy(pkgdir / fn, t)
        sh(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=t, timeout=300)
        rc, so, _ = sh(["npm", "audit", "--json"], cwd=t, timeout=120)
    try:
        v = json.loads(so)["metadata"]["vulnerabilities"]
        return {"high": v.get("high", 0), "critical": v.get("critical", 0)}
    except Exception:
        return None


def analyze_packages(app, offline, include_dev_unused):
    res = {"packages": [], "unused": [], "directas": 0, "unused_dev_incl": include_dev_unused,
           "npm": {"ok": False, "items": []}, "audit": {"ok": False, "high": 0, "critical": 0}}
    pairs, unused_total, ok_dc = [], 0, True
    for d in find_packages(app):
        pkg = read_pkg(d)
        deps = dict(pkg.get("dependencies", {}))
        dev = dict(pkg.get("devDependencies", {}))
        rd = rel(d, app) or "."
        res["packages"].append({"dir": rd, "name": pkg.get("name"), "dependencies": deps, "devDependencies": dev,
                                "scripts": pkg.get("scripts", {}), "engines": pkg.get("engines", {})})
        res["directas"] += len(deps) + (len(dev) if include_dev_unused else 0)
        u = run_depcheck(d, include_dev_unused)
        if u is None:
            ok_dc = False
        else:
            res["unused"] += [f"{rd}:{x}" for x in u]
        pairs += list({**deps, **dev}.items())
    res["depcheck_ok"] = ok_dc
    if offline or not pairs:
        return res
    with ThreadPoolExecutor(8) as ex:
        items = list(ex.map(npm_view, pairs))
    res["npm"] = {"ok": any(i["latest"] for i in items), "items": items}
    hi = cr = 0
    ok = False
    for d in find_packages(app):
        a = run_audit(d)
        if a:
            ok = True
            hi += a["high"]; cr += a["critical"]
    res["audit"] = {"ok": ok, "high": hi, "critical": cr}
    return res


def find_contracts(app):
    return [rel(p, app) for p in walk(app)
            if re.match(r"^(openapi|swagger)[\w.-]*\.(json|ya?ml)$", p.name, re.I)]


def run_contract(app, out, contracts):
    info = {"files": contracts, "spectral_errors": None, "paths": []}
    if not contracts:
        return info
    node_js = ("const Y=require('yaml'),fs=require('fs');const t=fs.readFileSync(process.argv[1],'utf8');"
               "const d=process.argv[1].endsWith('.json')?JSON.parse(t):Y.parse(t);const out=[];"
               "for(const [p,v] of Object.entries(d.paths||{}))for(const m of Object.keys(v||{}))"
               "if(['get','post','put','patch','delete'].includes(m))out.push([m.toUpperCase(),p]);"
               "console.log(JSON.stringify(out))")
    rc, so, _ = sh(["node", "-e", node_js, str(Path(app) / contracts[0])], cwd=HERE)
    try:
        info["paths"] = json.loads(so)
    except Exception:
        pass
    ruleset = out / ".spectral.yaml"
    ruleset.write_text('extends: ["spectral:oas"]\n', encoding="utf-8")
    rc, so, _ = sh([str(BIN / "spectral"), "lint", str(Path(app) / contracts[0]), "--ruleset", str(ruleset), "-f", "json", "-q"], timeout=120)
    try:
        info["spectral_errors"] = sum(1 for x in json.loads(so or "[]") if x.get("severity") == 0)
    except Exception:
        pass
    return info


def static_tests(ast, app):
    files = [f["path"] for f in ast["files"] if f["test"]]
    n = 0
    for f in files:
        try:
            n += len(re.findall(r"\b(?:it|test)(?:\.each)?\s*\(", (Path(app) / f).read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            pass
    return {"test_files": files, "test_cases": n}


def parse_lcov(lcov, d):
    """Suma LF/LH/BRF/BRH de un lcov.info. Node sólo reporta los archivos que las pruebas cargan, así que los
    fuentes .js/.ts sin cargar se suman con 0 líneas cubiertas (equivalente a collectCoverageFrom de Jest);
    sus ramas no se pueden contar sin instrumentarlos y quedan fuera del denominador."""
    tot = {"lines_total": 0, "lines_cov": 0, "br_total": 0, "br_cov": 0, "unloaded": 0}
    seen = set()
    for ln in lcov.read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith("SF:"): seen.add(os.path.normcase(os.path.normpath(str((d / ln[3:]) if not os.path.isabs(ln[3:]) else ln[3:]))))
        elif ln.startswith("LF:"): tot["lines_total"] += int(ln[3:])
        elif ln.startswith("LH:"): tot["lines_cov"] += int(ln[3:])
        elif ln.startswith("BRF:"): tot["br_total"] += int(ln[4:])
        elif ln.startswith("BRH:"): tot["br_cov"] += int(ln[4:])
    for f in walk(d):
        f = Path(f)
        if f.suffix not in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"): continue
        if re.search(r"\.(test|spec)\.", f.name) or {"tests", "__tests__", "coverage"} & set(f.parts): continue
        if os.path.normcase(os.path.normpath(str(f))) in seen: continue
        try: n = sum(1 for x in f.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip())
        except OSError: continue
        tot["lines_total"] += n; tot["unloaded"] += 1
    return tot


def run_tests(app, pkgs, test_cmd, out):
    res = {"executed": True, "packages": [], "lines_total": 0, "lines_cov": 0, "br_total": 0, "br_cov": 0, "all_passed": True, "ran_any": False}
    for p in pkgs:
        script = p["scripts"].get("test", "")
        if not script or "no test specified" in script:
            continue
        d = Path(app) / p["dir"]
        if not (d / "node_modules").exists():
            sh(["npm", "install", "--no-audit", "--no-fund"], cwd=d, timeout=900)
        native = (not test_cmd) and bool(re.search(r"\bnode\b.*--test\b|node:test", script))
        lcov = d / "coverage" / "lcov.info"
        if native:
            # runner nativo de Node (node --test): no acepta banderas de Jest; la cobertura se lee de lcov
            lcov.parent.mkdir(exist_ok=True)
            cmd = [shutil.which("node") or "node", "--test", "--experimental-test-coverage",
                   "--test-coverage-exclude=**/*.test.*", "--test-coverage-exclude=**/{tests,__tests__,coverage}/**",
                   "--test-reporter=spec", "--test-reporter-destination=stdout",
                   "--test-reporter=lcov", f"--test-reporter-destination={lcov}"]
        else:
          cmd = test_cmd.split() if test_cmd else ["npm", "test", "--silent", "--", "--coverage",
                                                  "--coverageReporters=json-summary", "--watchAll=false",
                                                  # sin esto Jest sólo mide los archivos que las pruebas importan (cobertura inflada)
                                                  "--collectCoverageFrom=**/*.{js,jsx,ts,tsx}", "--collectCoverageFrom=!**/node_modules/**",
                                                  "--collectCoverageFrom=!**/{tests,__tests__,coverage,dist,build}/**", "--collectCoverageFrom=!**/*.{test,spec}.*"]
        env = {**os.environ, "CI": "true"}
        rc, so, se = sh(cmd, cwd=d, timeout=900, env=env)
        entry = {"dir": p["dir"], "rc": rc, "tail": (so + se)[-400:]}
        res["ran_any"] = True
        if rc != 0:
            res["all_passed"] = False
        cs = d / "coverage" / "coverage-summary.json"
        if native and lcov.exists():
            t = parse_lcov(lcov, d)
            res["lines_total"] += t["lines_total"]; res["lines_cov"] += t["lines_cov"]
            res["br_total"] += t["br_total"]; res["br_cov"] += t["br_cov"]
            entry["coverage"] = {"lines": round(100.0 * t["lines_cov"] / t["lines_total"], 1) if t["lines_total"] else 0.0,
                                 "branches": round(100.0 * t["br_cov"] / t["br_total"], 1) if t["br_total"] else 0.0,
                                 "runner": "node:test", "archivos_sin_cargar": t["unloaded"]}
        elif cs.exists():
            t = json.loads(cs.read_text())["total"]
            res["lines_total"] += t["lines"]["total"]; res["lines_cov"] += t["lines"]["covered"]
            res["br_total"] += t["branches"]["total"]; res["br_cov"] += t["branches"]["covered"]
            entry["coverage"] = {"lines": t["lines"]["pct"], "branches": t["branches"]["pct"]}
        res["packages"].append(entry)
    return res


def classify_layers(ast, app, override):
    L = RUBRIC["capas_por_defecto"]
    names = ["presentacion", "negocio", "datos", "compartida"]
    ov = None
    if override and Path(override).exists():
        ov = {k: [glob_to_re(g) for g in v] for k, v in json.loads(Path(override).read_text()).items() if not k.startswith("_")}
    out = {}; origen = {}
    for f in ast["files"]:
        if f["test"] or f["frontend"]:
            continue
        p = f["path"]
        layer = None
        if ov:
            for k, rs in ov.items():
                if any(r.match(p) for r in rs):
                    layer = k; origen[p] = "override"; break
        else:
            parts = p.lower().split("/")
            stem = re.sub(r"\.[a-z]+$", "", parts[-1])
            stem = re.sub(r"([a-z])([A-Z])", r"\1.\2", Path(p).stem).lower()
            tokens = [t for t in re.split(r"[.\-_]", stem) if t] + list(reversed(parts[:-1]))
            norm = lambda s: s.rstrip("s")
            # Primero las capas arquitectónicas (token más cercano al archivo); 'compartida' sólo si nada más coincide
            for group in (names[:3], names[3:]):
                for tok in tokens:
                    for n in group:
                        if norm(tok) in {norm(k) for k in L[n]}:
                            layer = n; origen[p] = tok; break
                    if layer:
                        break
                if layer:
                    break
        if layer:
            out[p] = layer
    return out, origen


def readme_text(app):
    for p in walk(app):
        if p.name.lower() == "readme.md" and "node_modules" not in p.parts:
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def collect(app, out, opts):
    app = Path(app).resolve()
    m = {"app": str(app), "fecha": datetime.datetime.now().isoformat(timespec="seconds")}
    m["ast"] = run_ast(app, out)
    m["graph"] = run_depcruise(app, out)
    inc_dev = RUBRIC["umbrales"]["acoplamiento"]["incluir_devdependencies"]
    m["packages"] = analyze_packages(app, opts.offline, inc_dev)
    m["contract"] = run_contract(app, out, find_contracts(app))
    m["tests_static"] = static_tests(m["ast"], app)
    m["tests_run"] = run_tests(app, m["packages"]["packages"], opts.test_cmd, out) if opts.run_tests else {"executed": False}
    m["layers"], m["layers_origen"] = classify_layers(m["ast"], app, opts.layers or (app / ".layers.json"))
    m["readme"] = readme_text(app)
    m["env_example"] = any(p.name in (".env.example", ".env.sample", ".env.template", "env.example") for p in walk(app))
    return m


# ───────────────────────── evaluación ─────────────────────────
def C(ok, desc, valor=None, fuente="auto", sugerido=None):
    return {"ok": ok, "desc": desc, "valor": valor, "fuente": fuente, "sugerido": sugerido}


def apply_manual(pid, crits, manual):
    for cid, v in (manual.get(pid) or {}).items():
        if cid in crits and cid != "nota":
            ok = v.get("ok") if isinstance(v, dict) else v
            if ok is None:
                continue
            crits[cid]["ok"] = bool(ok)
            crits[cid]["fuente"] = "manual"
            if isinstance(v, dict) and v.get("nota"):
                crits[cid]["valor"] = v["nota"]


def heur(crit, opts):
    """Criterio de fuente heurística: sólo cuenta si se aceptan las heurísticas."""
    if crit["sugerido"] is not None:
        crit["fuente"] = "heuristica"
        crit["ok"] = crit["sugerido"] if opts.aceptar_heuristicas else None
    return crit


def level_from(crits, must=()):
    """Devuelve (nivel, nivel_min, nivel_max). None en un criterio = pendiente."""
    pm = RUBRIC["parcial_min_fraccion"]

    def lvl(vals):
        if any(not vals[k] for k in must if k in vals):
            return "No cumple"
        n, k = len(vals), sum(vals.values())
        return "Cumple" if k == n else ("Parcial" if k / n >= pm else "No cumple")

    lo = lvl({k: bool(v["ok"]) for k, v in crits.items()})
    hi = lvl({k: (True if v["ok"] is None else bool(v["ok"])) for k, v in crits.items()})
    return (lo if lo == hi else None), lo, hi


def level_from_pct(value, cumple_ok, parcial_ok):
    return "Cumple" if cumple_ok(value) else ("Parcial" if parcial_ok(value) else "No cumple")


def pdict(pid):
    d = RUBRIC["puntos"][pid]
    return {"id": pid, **d}


def eval_capas(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["capas"]; P = RUBRIC["capas_por_defecto"]["permitidas"]
    amb = {x.lower() for x in RUBRIC["capas_por_defecto"].get("ambiguas", [])}
    layers, origen = m["layers"], m.get("layers_origen", {})
    main = {"presentacion", "negocio", "datos"}
    ident = sorted(set(layers.values()) & main)
    cross = viol = dudosas = 0; ev = []
    for mod in m["graph"].get("modules", []):
        a = layers.get(mod["source"])
        if a not in main:
            continue
        for d in mod["deps"]:
            b = layers.get(d["to"]) if d["local"] else None
            if b in main and a != b:
                cross += 1
                if [a, b] not in P:
                    viol += 1
                    # clasificación dudosa: algún extremo se asignó por un directorio ambiguo (p. ej. domain)
                    dud = (origen.get(mod["source"], "").lower() in amb) or (origen.get(d["to"], "").lower() in amb)
                    dudosas += dud
                    if len(ev) < 8:
                        ev.append(f"{mod['source']} ({a}) → {d['to']} ({b})" + (" [clasificación dudosa]" if dud else ""))
    if len(ident) < T["min_capas_identificables"]:
        crit = {"C1": C(False, f"Capas identificables (≥{T['min_capas_identificables']})", ident),
                "C2": C(False, "Violaciones ≤ 5% de dependencias entre capas", "n/a")}
        return crit, {"capas": ident, "dependencias_entre_capas": cross, "violaciones": viol, "violaciones_pct": 0.0}, ev,             f"Capas detectadas: {', '.join(ident) or 'ninguna'}; no hay capas suficientes.", ("No cumple",) * 3

    def nivel_con(v):
        vp = pct(v, cross) if cross else 0.0
        return level_from_pct(vp, lambda x: x <= T["cumple_max_violaciones_pct"], lambda x: x <= T["parcial_max_violaciones_pct"]), vp
    n_todas, vpct = nivel_con(viol)
    n_firmes, _ = nivel_con(viol - dudosas)
    crit = {"C1": C(True, f"Capas identificables (≥{T['min_capas_identificables']})", ident)}
    desc2 = "Violaciones ≤ 5% de dependencias entre capas"
    if cross == 0:
        # Sin aristas entre capas (p. ej. inyección de dependencias): el resultado no es evidencia de separación
        c2 = C(None, desc2, "0 dependencias entre capas", fuente="pendiente (manual)")
        apply_manual("capas", {"C2": c2}, manual); crit["C2"] = c2
        forced = ("Cumple",) * 3 if c2["ok"] else ("No cumple",) * 3 if c2["ok"] is False else (None, "No cumple", "Cumple")
        hall = (f"Capas detectadas: {', '.join(ident)}; 0 dependencias entre capas (posible inyección de dependencias): "
                "no hay evidencia estructural; requiere revisión manual (capas.C2).")
    elif dudosas and n_firmes != n_todas:
        c2 = C(None, desc2 + " (descontando clasificaciones dudosas)", f"{viol}/{cross} violaciones, {dudosas} con clasificación dudosa",
               fuente="pendiente (manual)")
        apply_manual("capas", {"C2": c2}, manual); crit["C2"] = c2
        # ok=true: las dudosas no son violaciones; ok=false: sí lo son
        forced = (n_firmes,) * 3 if c2["ok"] else (n_todas,) * 3 if c2["ok"] is False else (None, n_todas, n_firmes)
        hall = (f"Capas detectadas: {', '.join(ident)}; {viol} de {cross} dependencias violan la regla, {dudosas} por una clasificación dudosa "
                f"(directorio ambiguo): de {n_todas} a {n_firmes} según la revisión manual (capas.C2) o un .layers.json.")
    else:
        crit["C2"] = C(n_todas != "No cumple", desc2, f"{viol}/{cross} = {vpct:.1f}%")
        forced = (n_todas,) * 3
        hall = f"Capas detectadas: {', '.join(ident)}; {viol} de {cross} dependencias entre capas violan la regla."
    return crit, {"capas": ident, "dependencias_entre_capas": cross, "violaciones": viol, "violaciones_dudosas": dudosas,
                  "violaciones_pct": vpct}, ev, hall, forced


def eval_ciclomatica(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["ciclomatica"]
    fns = [f for f in m["ast"]["functions"] if not f["test"]]
    B = len(fns); big = [f for f in fns if f["cc"] > T["umbral_funcion"]]
    X = 1 - len(big) / B if B else None
    ccs = sorted(f["cc"] for f in fns)
    met = {"funciones": B, "funciones_cc_mayor_umbral": len(big), "X": X,
           "mediana": median(ccs), "p90": ccs[int(0.9 * (len(ccs) - 1))] if ccs else None, "max": ccs[-1] if ccs else None}
    if X is None:
        return {}, met, [], "Sin funciones implementadas.", (None, None, None)
    nivel = level_from_pct(X, lambda v: v >= T["cumple_X_min"], lambda v: v >= T["parcial_X_min"])
    ev = [f"{f['file']}:{f['line']} {f['name']} (CC={f['cc']})" for f in sorted(big, key=lambda f: -f["cc"])[:8]]
    crit = {"C1": C(X >= T["parcial_X_min"], "X ≥ 0,95 (Parcial)", round(X, 4)), "C2": C(X >= T["cumple_X_min"], "X ≥ 0,98 (Cumple)", round(X, 4))}
    hall = f"X = 1 − {len(big)}/{B} = {X:.3f}; mediana CC {met['mediana']}, p90 {met['p90']}, máx {met['max']}."
    return crit, met, ev, hall, (nivel, nivel, nivel)


def fan_in(m):
    fi = {}
    for mod in m["graph"].get("modules", []):
        for d in mod["deps"]:
            if d["local"]:
                fi[d["to"]] = fi.get(d["to"], 0) + 1
    return fi


def eval_cohesion(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["cohesion"]
    fns = [f for f in m["ast"]["functions"] if not f["test"]]
    hi = [f for f in fns if f["fanout"] > T["fanout_max"]]
    p = pct(len(hi), len(fns))
    fi = fan_in(m); locs = {f["path"]: f["loc"] for f in m["ast"]["files"]}
    dioses = [f"{k} (LOC={locs.get(k)}, fan-in={v})" for k, v in fi.items()
              if locs.get(k, 0) >= T["dios_loc_min"] and v >= T["dios_fanin_min"]]
    prod = [f for f in m["ast"]["files"] if not f["test"]]
    frag = pct(sum(1 for f in prod if f["loc"] < 10), len(prod)) if prod else 0
    dl = (manual.get("dv8") or {}).get("DL")
    c1 = C(p is not None and p <= T["pct_fanout_max"], "≤ 5% de funciones con fan-out > 5", f"{len(hi)}/{len(fns)} = {p:.1f}%" if p is not None else None)
    c2 = C(None if dl is None else dl >= T["DL_min"], "DL de DV8 ≥ 60%", dl, fuente="dv8" if dl is not None else "pendiente (DV8)")
    c3 = heur(C(None, "Lista de verificación sin hallazgos (módulo 'dios', mezcla de responsabilidades, fragmentación)",
                {"modulos_dios_sugeridos": dioses, "archivos_<10_LOC_pct": round(frag, 1)}, sugerido=(not dioses and frag < 40)), opts)
    crit = {"C1": c1, "C2": c2, "C3": c3}
    apply_manual("cohesion", crit, manual)
    ev = [f"{f['file']}:{f['line']} {f['name']} (fan-out={f['fanout']})" for f in sorted(hi, key=lambda f: -f["fanout"])[:5]] + dioses[:3]
    return crit, {"pct_fanout": p, "modulos_dios_sugeridos": dioses}, ev, f"{len(hi)} de {len(fns)} funciones con fan-out > {T['fanout_max']}; {len(dioses)} módulo(s) candidatos a 'dios'.", None


def eval_jerarquias(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["jerarquias"]
    cls = m["ast"]["classes"]; byname = {c["name"]: c for c in cls}
    def depth(c, seen=()):
        if not c["extends"]:
            return 0
        parent = byname.get(c["extends"].split(".")[-1])
        return 1 + (depth(parent, seen + (c["name"],)) if parent and parent["name"] not in seen else 0)
    kids = {}
    for c in cls:
        if c["extends"]:
            kids[c["extends"]] = kids.get(c["extends"], 0) + 1
    deep = [c for c in cls if depth(c) > T["profundidad_max"]]
    wide = [k for k, v in kids.items() if v > T["hijos_max"]]
    uih = (manual.get("dv8") or {}).get("unhealthy_inheritance")
    c3_ok = True if not cls else (None if uih is None else uih == 0)
    crit = {"C1": C(not deep, "0 clases con profundidad > 7", len(deep)),
            "C2": C(not wide, "0 clases con > 10 hijos directos", len(wide)),
            "C3": C(c3_ok, "0 patrones Unhealthy Inheritance (DV8)", uih, fuente="auto (sin clases)" if not cls else ("dv8" if uih is not None else "pendiente (DV8)"))}
    apply_manual("jerarquias", crit, manual)
    return crit, {"clases": len(cls)}, [f"{c['file']}: {c['name']}" for c in deep[:5]], f"{len(cls)} clases; {len(deep)} con profundidad excesiva; {len(wide)} con demasiados hijos.", None


def eval_tecnologias(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["tecnologias"]; S = RUBRIC["runtimes_con_soporte"]
    pk = m["packages"]; npm = pk["npm"]
    if not npm["ok"]:
        crit = {k: C(None, d, fuente="pendiente (sin red)") for k, d in
                [("C1", "Sin paquetes deprecados"), ("C2", "Runtime y framework en soporte"), ("C3", "≤ 20% de directas con versión mayor atrasada"), ("C4", "0 vulnerabilidades altas/críticas")]}
        apply_manual("tecnologias", crit, manual)
        return crit, {}, [], "No se consultó el registro npm (modo offline o sin red).", None
    items = npm["items"]
    dep = [i for i in items if i["deprecated"]]
    atras = []
    for i in items:
        b, l = coerce_version(i["spec"]), i["latest"]
        if b and l and int(b.split(".")[0]) < int(str(l).split(".")[0]):
            atras.append(f"{i['pkg']} {i['spec']} (latest {l})")
    pa = pct(len(atras), len(items))
    fuera = []
    for pkg in pk["packages"]:
        for name, spec in {**pkg["dependencies"], **pkg["devDependencies"]}.items():
            if name in S and coerce_version(spec) and int(coerce_version(spec).split(".")[0]) not in S[name]:
                fuera.append(f"{name} {spec}")
        eng = pkg["engines"].get("node")
        if eng and coerce_version(eng) and int(coerce_version(eng).split(".")[0]) not in S["node"]:
            fuera.append(f"node {eng}")
    vuln = pk["audit"]["high"] + pk["audit"]["critical"] if pk["audit"]["ok"] else None
    crit = {"C1": C(not dep, "Sin paquetes deprecados", [i["pkg"] for i in dep]),
            "C2": C(not fuera, f"Runtime y framework en soporte (tabla en rubric.json, {S['fecha']})", fuera),
            "C3": C(pa <= T["pct_mayor_atrasada_max"], "≤ 20% de directas con versión mayor atrasada", f"{len(atras)}/{len(items)} = {pa:.1f}%"),
            "C4": C(None if vuln is None else vuln <= T["vuln_altas_criticas_max"], "0 vulnerabilidades altas o críticas", vuln, fuente="auto" if vuln is not None else "pendiente (npm audit)")}
    apply_manual("tecnologias", crit, manual)
    return crit, {"directas": len(items), "deprecadas": len(dep), "atrasadas": len(atras)}, atras[:6] + fuera[:4], \
        f"{len(items)} dependencias directas: {len(dep)} deprecadas, {len(atras)} con mayor atrasada, {vuln if vuln is not None else '?'} vulnerabilidades altas/críticas.", None


def eval_acoplamiento(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["acoplamiento"]
    mods = m["graph"].get("modules", [])
    in_cycle = {n for c in m["graph"].get("cycles", []) for n in c}
    A = sum(1 for x in mods if x["source"] not in in_cycle and len({d["module"] for d in x["deps"]}) < T["deps_salientes_max"])
    X = A / len(mods) if mods else None
    pc = (manual.get("dv8") or {}).get("PC")
    unused = m["packages"]["unused"]; pu = pct(len(unused), m["packages"]["directas"]) if m["packages"]["directas"] else 0.0
    crit = {"C1": C(len(m["graph"].get("cycles", [])) == 0, "0 ciclos de dependencia (CWE-1047)", len(m["graph"].get("cycles", []))),
            "C2": C(None if X is None else X >= T["X_min"], "X (MMo-1-G) ≥ 0,90", None if X is None else round(X, 3)),
            "C3": C(None if pc is None else pc <= T["PC_max"], "Package Cycle (DV8) ≤ 20%", pc, fuente="dv8" if pc is not None else "pendiente (DV8)"),
            "C4": C(pu <= T["pct_sin_uso_max"] if m["packages"]["depcheck_ok"] else None, "≤ 10% de dependencias sin uso", f"{len(unused)}/{m['packages']['directas']} = {pu:.1f}%")}
    apply_manual("acoplamiento", crit, manual)
    ev = [" ↔ ".join(c[:4]) for c in m["graph"].get("cycles", [])[:4]] + unused[:6]
    return crit, {"modulos": len(mods), "ciclos": len(m["graph"].get("cycles", [])), "X": X}, ev, \
        f"{len(m['graph'].get('cycles', []))} ciclos; X={'n/d' if X is None else f'{X:.2f}'}; {len(unused)} dependencias sin uso.", None


def eval_modelo_datos(m, manual, ex, opts):
    S = m["ast"]["schemas"]; n = len(S)
    c1 = n >= 1 and (n == 1 or any(s["refs"] or s["embedded"] for s in S))
    c3 = n >= 1 and all(s["required"] > 0 for s in S)
    c4 = n >= 1 and all((s["indexedFields"] + s["schemaIndexCalls"]) > 0 for s in S if s["refs"]) and any(s["indexedFields"] + s["schemaIndexCalls"] for s in S)
    crit = {"C1": heur(C(None, "Entidades y relaciones explícitas", f"{n} esquemas", sugerido=c1), opts),
            "C2": C(None, "Referencia o embebido coherente con el acceso", fuente="pendiente (manual)"),
            "C3": heur(C(None, "Validación de esquema", f"{sum(1 for s in S if s['required'])}/{n} esquemas con required", sugerido=c3), opts),
            "C4": heur(C(None, "Índices en campos de consulta y relación", sum(s["indexedFields"] + s["schemaIndexCalls"] for s in S), sugerido=c4), opts),
            "C5": C(None, "Sin redundancia injustificada ni tipos inconsistentes", fuente="pendiente (manual)")}
    apply_manual("modelo_datos", crit, manual)
    ev = [f"{s['file']}:{s['line']} {s['name']} (campos={s['fields']}, required={s['required']}, refs={s['refs']}, índices={s['indexedFields'] + s['schemaIndexCalls']})" for s in S[:6]]
    return crit, {"esquemas": n}, ev, f"{n} esquemas Mongoose detectados.", None


def route_match(contract_paths, route):
    norm = lambda p: re.sub(r":(\w+)", r"{\1}", p).rstrip("/") or "/"
    r = norm(route["path"])
    for meth, p in contract_paths:
        c = norm(p)
        if meth == route["method"] and (c == r or c.endswith(r) or r.endswith(c)):
            return True
    return False


def eval_contratos(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["contratos"]; ct = m["contract"]; routes = m["ast"]["routes"]
    has = bool(ct["files"])
    cov = None
    if has and routes:
        cov = 100.0 * sum(route_match(ct["paths"], r) for r in routes) / len(routes)
    deps = {d for p in m["packages"]["packages"] for d in {**p["dependencies"], **p["devDependencies"]}}
    vlibs = sorted(deps & set(RUBRIC["libs_validacion"]))
    crit = {"C1": C(has, "Contrato legible por máquina (OpenAPI/…)", ct["files"]),
            "C2": C((ct["spectral_errors"] == 0) if (has and ct["spectral_errors"] is not None) else (False if not has else None), "0 errores de Spectral (spectral:oas)", ct["spectral_errors"]),
            "C3": C((cov >= T["cobertura_min"]) if cov is not None else False, "Cobertura del contrato ≥ 90% de las rutas", None if cov is None else f"{cov:.0f}% de {len(routes)} rutas"),
            "C4": heur(C(None, "Validación de entradas coherente con el contrato", vlibs, sugerido=bool(vlibs) and has), opts)}
    apply_manual("contratos", crit, manual)
    return crit, {"rutas_implementadas": len(routes), "cobertura_pct": cov}, ct["files"][:3] + [f"{r['method']} {r['path']}" for r in routes[:4]], \
        f"{'Contrato: ' + ', '.join(ct['files']) if has else 'Sin contrato legible por máquina'}; {len(routes)} rutas implementadas.", None


def eval_observabilidad(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["observabilidad"]; cb = m["ast"]["catchBlocks"]
    deps = {d for p in m["packages"]["packages"] for d in {**p["dependencies"], **p["devDependencies"]}}
    logger = sorted(deps & set(RUBRIC["libs_logger"])); metrics = sorted(deps & set(RUBRIC["libs_metricas"]))
    mw = m["ast"]["errorMiddleware"]
    central_logs = False
    for e in mw:
        try:
            central_logs |= bool(re.search(r"console\.|logger\.|log\.", (Path(m["app"]) / e["file"]).read_text(errors="ignore")))
        except Exception:
            pass
    X = (cb["logging"] + (cb["delegating"] if central_logs else 0)) / cb["total"] if cb["total"] else None
    c1 = (X >= T["X_min"]) if X is not None else bool(mw and central_logs)
    cons = len(m["ast"]["consoleCalls"])
    health = [r for r in m["ast"]["routes"] if re.search(r"health|ready|live|metrics|status", r["path"], re.I)]
    crit = {"C1": C(c1, "X ≥ 0,80 de eventos críticos registrados (proxy: bloques catch con log o delegación a handler que registra)",
                    None if X is None else round(X, 2), fuente="auto (proxy)"),
            "C2": C(bool(logger) and cons == 0, "Logger estructurado y sin console.* en producción", {"logger": logger, "console_calls": cons}),
            "C3": C(bool(mw), "Manejo centralizado de errores", len(mw)),
            "C4": C(bool(health or metrics), "Health check, métricas o trazas", {"rutas": [r["path"] for r in health], "libs": metrics})}
    apply_manual("observabilidad", crit, manual)
    ev = [f"{c['file']}:{c['line']} console.*" for c in m["ast"]["consoleCalls"][:5]] + [f"catch sin registro {c['file']}:{c['line']}" for c in cb["silent"][:3]]
    return crit, {"catch_total": cb["total"], "console_calls": cons}, ev, \
        f"{cb['total']} bloques catch ({cb['logging']} con log, {cb['delegating']} delegan, {len(cb['silent'])} silenciosos); {cons} console.*; {len(mw)} middleware(s) de errores.", None


def eval_pruebas(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["pruebas"]; a = m["ast"]
    bad = len(a["switchesMissingDefault"]) + len(a["fallthrough"]) + len(a["labeledJumps"])
    ts = m["tests_static"]; tr = m["tests_run"]; exist = ts["test_cases"] > 0
    c2 = False if not exist else (None if not tr["executed"] or not tr.get("ran_any") else tr["all_passed"])
    lines = branches = None
    if tr["executed"] and tr.get("lines_total"):
        lines = 100.0 * tr["lines_cov"] / tr["lines_total"]; branches = 100.0 * tr["br_cov"] / tr["br_total"] if tr["br_total"] else 0.0
    def cov_ok(v, thr):
        if not exist: return False
        return None if v is None else v >= thr
    crit = {"C1": C(bad == 0, "0 violaciones CWE-478/484/1075", {"switch_sin_default": len(a["switchesMissingDefault"]), "fallthrough": len(a["fallthrough"]), "saltos_etiqueta": len(a["labeledJumps"])}),
            "C2": C(c2, "Pruebas existentes y aprobadas", f"{ts['test_cases']} casos en {len(ts['test_files'])} archivos", fuente="auto" if c2 is not None else "pendiente (--run-tests)"),
            "C3": C(cov_ok(lines, T["lineas_min"]), "Cobertura de líneas ≥ 70%", None if lines is None else round(lines, 1), fuente="auto" if (lines is not None or not exist) else "pendiente (--run-tests)"),
            "C4": C(cov_ok(branches, T["ramas_min"]), "Cobertura de ramas ≥ 50%", None if branches is None else round(branches, 1), fuente="auto" if (branches is not None or not exist) else "pendiente (--run-tests)")}
    apply_manual("pruebas", crit, manual)
    ev = [f"switch sin default {x['file']}:{x['line']}" for x in a["switchesMissingDefault"][:3]] + ts["test_files"][:3]
    return crit, {"casos": ts["test_cases"], "cobertura_lineas": lines, "cobertura_ramas": branches}, ev, \
        f"{ts['test_cases']} casos de prueba; cobertura líneas {'n/d' if lines is None else f'{lines:.0f}%'}, ramas {'n/d' if branches is None else f'{branches:.0f}%'}.", None


def eval_configuracion(m, manual, ex, opts):
    T = RUBRIC["umbrales"]["configuracion"]; a = m["ast"]
    lits = [x for x in a["networkLiterals"] if not (T["cwe1051_ignorar_fallback_env"] and x["envFallback"])]
    kloc = sum(f["loc"] for f in a["files"] if not f["test"]) / 1000.0
    occ = a["literalOccurrences"]
    dups = {k: v for k, v in occ.items() if len(v) > 1 and len(k) >= 4}
    excess = sum(len(v) - 1 for v in dups.values()); dens = excess / kloc if kloc else 0.0  # sólo informativo
    # Regla S1192 de SonarQube (eslint-plugin-sonarjs no-duplicate-string): umbral, longitud mínima, sin literales "\w*" ni ignorados
    flagged = {k: len(v) for k, v in occ.items()
               if len(v) >= T["dup_literal_umbral"] and len(k) >= T["dup_literal_min_len"]
               and not (T["dup_literal_ignorar_solo_palabra"] and re.fullmatch(r"\w*", k, re.ASCII)) and k not in T["dup_literal_ignorar"]}
    cfg_mod = any(re.search(r"(^|/)config(\.|/)", f) for f in a["envFiles"])
    crit = {"C1": C(len(lits) == 0, "0 literales de red (URL/IP/puerto) (CWE-1051)", len(lits)),
            "C2": C(not flagged, f"0 literales de ≥{T['dup_literal_min_len']} caracteres repetidos ≥{T['dup_literal_umbral']} veces (SonarQube S1192)",
                    flagged or 0),
            "C3": C(m["env_example"] or cfg_mod, "Configuración externa (.env.example o módulo de configuración)", {"env_example": m["env_example"], "modulo_config": cfg_mod})}
    apply_manual("configuracion", crit, manual)
    ev = [f"{x['file']}:{x['line']} {x['value']}" + (" [fallback env]" if x["envFallback"] else "") for x in lits[:6]]
    return crit, {"literales_red": len(lits), "dup_por_kloc": dens, "kloc": kloc, "literales_s1192": flagged}, ev, \
        f"{len(lits)} literales de red; {len(flagged)} literal(es) duplicado(s) según S1192 ({dens:.1f} repeticiones/KLOC, informativo).", None


EVALUATORS = {"capas": eval_capas, "ciclomatica": eval_ciclomatica, "cohesion": eval_cohesion, "jerarquias": eval_jerarquias,
              "tecnologias": eval_tecnologias, "acoplamiento": eval_acoplamiento, "modelo_datos": eval_modelo_datos,
              "contratos": eval_contratos, "observabilidad": eval_observabilidad, "pruebas": eval_pruebas, "configuracion": eval_configuracion}
MUST = {"contratos": ("C1",), "pruebas": ("C2",)}
DECLARA = {"capas": r"capas|layer|controller|service|repositor", "ciclomatica": None, "cohesion": r"cohesi|responsabilidad|single",
           "jerarquias": None, "tecnologias": r"versi|stack|react|express", "acoplamiento": r"acopl|inyecci|dependenc",
           "modelo_datos": r"schema|esquema|modelo de datos|índice|index", "contratos": r"openapi|swagger|contrato|api",
           "observabilidad": r"log|winston|pino|health|observab", "pruebas": r"test|prueba|jest|cobertura|coverage", "configuracion": r"\.env|variable[s]? de entorno|config"}


def evaluate_points(m, manual, extras, opts):
    pts = []
    sc = RUBRIC["puntaje_nivel"]
    for pid, fn in EVALUATORS.items():
        crits, met, ev, hall, forced = fn(m, manual, extras, opts)
        if forced and (forced[0] or forced[1] != forced[2]):  # forzado, o rango pendiente (nivel None, lo ≠ hi)
            nivel, lo, hi = forced
        elif crits:
            nivel, lo, hi = level_from(crits, MUST.get(pid, ()))
        else:
            nivel = lo = hi = None
        pend = [k for k, v in crits.items() if v["ok"] is None]
        declared = bool(re.search(DECLARA[pid], m["readme"], re.I)) if (m["readme"] and DECLARA[pid]) else False
        brecha = None
        if DECLARA[pid]:  # sólo puntos cuya decisión suele declararse en la documentación
            if nivel == "No cumple" and declared: brecha = "declarada pero no sustentada por la estructura"
            elif nivel == "Cumple" and not declared: brecha = "implementada pero no declarada"
        pts.append({**pdict(pid), "nivel": nivel, "nivel_min": lo, "nivel_max": hi,
                    "completo": nivel is not None, "criterios_pendientes": pend,
                    "severidad": RUBRIC["severidad_nivel"].get(nivel) if nivel else ("Indeterminada" if lo != hi else None),
                    "hallazgo": hall, "metricas": met, "criterios": crits, "evidencia": ev,
                    "debilidades": [f"{k}: {v['desc']} → {v['valor']}" for k, v in crits.items() if v["ok"] is False],
                    "declarado_en_readme": declared, "brecha_declarativa": brecha,
                    "puntaje_min": sc[lo] if lo else None, "puntaje_max": sc[hi] if hi else None})
    return pts


def perfil(points):
    W = RUBRIC["pesos_subcaracteristicas"]; subs = {}
    for s in W:
        ps = [p for p in points if s in p["subcaracteristicas"] and p["puntaje_min"] is not None]
        tot = [p for p in points if s in p["subcaracteristicas"]]
        lo = sum(p["puntaje_min"] for p in ps) / len(ps) if ps else None
        hi = sum(p["puntaje_max"] for p in ps) / len(ps) if ps else None
        subs[s] = {"peso": W[s], "puntos": [p["id"] for p in tot], "puntos_evaluables": len(ps),
                   "min": None if lo is None else round(100 * lo, 1), "max": None if hi is None else round(100 * hi, 1)}
    ok = all(v["min"] is not None for v in subs.values())
    lo = round(sum(v["peso"] * v["min"] for v in subs.values() if v["min"] is not None), 1) if ok else None
    hi = round(sum(v["peso"] * v["max"] for v in subs.values() if v["max"] is not None), 1) if ok else None
    return {"subcaracteristicas": subs, "mantenibilidad_min": lo, "mantenibilidad_max": hi,
            "completo": all(p["completo"] for p in points)}


# ───────────────────────── salidas ─────────────────────────
def fmt_rng(a, b):
    return "n/d" if a is None else (f"{a:.1f}" if a == b else f"{a:.1f}–{b:.1f}")


def write_outputs(out, meta, points, prof, m):
    out.mkdir(parents=True, exist_ok=True)
    (out / "ficha.json").write_text(json.dumps({"meta": meta, "puntos": points}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "perfil.json").write_text(json.dumps({"meta": meta, **prof}, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(out / "ficha.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["punto", "categoria", "nivel", "nivel_min", "nivel_max", "severidad", "criterios_pendientes", "hallazgo", "evidencia"])
        for p in points:
            w.writerow([p["nombre"], p["categoria"], p["nivel"] or "pendiente", p["nivel_min"], p["nivel_max"], p["severidad"], " ".join(p["criterios_pendientes"]), p["hallazgo"], " | ".join(p["evidencia"][:5])])
    with open(out / "trazabilidad.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["decision_de_diseno", "debilidad_detectada", "subcaracteristicas_afectadas", "nivel", "evidencia", "brecha_declarativa"])
        for p in points:
            w.writerow([p["hallazgo"], "; ".join(p["debilidades"]) or "—", ", ".join(p["subcaracteristicas"]), p["nivel"] or "pendiente", " | ".join(p["evidencia"][:5]), p["brecha_declarativa"] or ""])
    L = [f"# Perfil de mantenibilidad — {meta.get('run_id')}", "",
         f"Agente: {meta.get('agente')} · Modelo: {meta.get('modelo')} · Nivel de prompt: {meta.get('nivel')} · Dominio: {meta.get('dominio')} · {m['fecha']}", "",
         f"**Mantenibilidad global: {fmt_rng(prof['mantenibilidad_min'], prof['mantenibilidad_max'])} / 100**" + ("" if prof["completo"] else "  _(rango: hay criterios pendientes; ver manual.template.json)_"), "",
         "| Subcaracterística | Peso | Puntaje |", "|---|---|---|"]
    for s, v in prof["subcaracteristicas"].items():
        L.append(f"| {s} | {int(v['peso'] * 100)}% | {fmt_rng(v['min'], v['max'])} |")
    L += ["", "| Punto de decisión | Nivel | Severidad | Pendientes | Hallazgo |", "|---|---|---|---|---|"]
    for p in points:
        n = p["nivel"] or f"{p['nivel_min']}…{p['nivel_max']}"
        L.append(f"| {p['nombre']} | {n} | {p['severidad'] or '—'} | {', '.join(p['criterios_pendientes']) or '—'} | {p['hallazgo']} |")
    br = [p for p in points if p["brecha_declarativa"]]
    if br:
        L += ["", "## Brechas declarativas (README vs. estructura)"] + [f"- {p['nombre']}: {p['brecha_declarativa']}" for p in br]
    (out / "perfil.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    tpl = {"_instrucciones": "Complete ok=true/false (y nota) en los criterios pendientes y vuelva a ejecutar 'run' con --manual manual.json. Valores de DV8 en 'dv8'.",
           "dv8": {"DL": None, "PC": None, "unhealthy_inheritance": None}}
    for p in points:
        pend = {k: {"ok": None, "sugerido": v["sugerido"], "nota": ""} for k, v in p["criterios"].items() if v["ok"] is None}
        if pend:
            tpl[p["id"]] = pend
    (out / "manual.template.json").write_text(json.dumps(tpl, indent=1, ensure_ascii=False), encoding="utf-8")


# ───────────────────────── comandos ─────────────────────────
def cmd_run(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    app = Path(a.app).resolve()
    # Revisión manual: --manual > <app>/manual.json > <out>/revision_manual.json (lo que genera/completa plantilla_manual.py)
    mfile = next((Path(p) for p in (a.manual, app / "manual.json", out / "revision_manual.json") if p and Path(p).exists()), None)
    manual = json.loads(mfile.read_text(encoding="utf-8")) if mfile else {}
    # Prioridad: manual.json > dv8/dv8_manual.json (revisión humana, no se regenera) > dv8/dv8_metrics.json (dv8_metrics.py)
    for fuente in ("dv8_manual.json", "dv8_metrics.json"):
        f = out / "dv8" / fuente
        if f.exists():
            dv8 = manual.setdefault("dv8", {})
            for k, v in json.loads(f.read_text(encoding="utf-8")).items():
                if not k.startswith("_") and v is not None and dv8.get(k) is None:
                    dv8[k] = v
    print(f"[1/4] Recolectando evidencia de {app} …")
    m = collect(app, out, a)
    meta = {"run_id": a.run_id or out.name, "agente": a.agente, "modelo": a.modelo, "nivel": a.nivel, "dominio": a.dominio,
            "aceptar_heuristicas": a.aceptar_heuristicas, "run_tests": a.run_tests, "offline": a.offline, "fecha": m["fecha"]}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (out / "manual.json").write_text(json.dumps(manual, indent=1), encoding="utf-8")
    slim = {k: v for k, v in m.items() if k != "readme"}
    slim["readme"] = m["readme"]
    (out / "metrics.json").write_text(json.dumps(slim, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "layers_detectadas.json").write_text(json.dumps(
        {p: {"capa": c, "origen": m["layers_origen"].get(p)} for p, c in m["layers"].items()}, indent=1), encoding="utf-8")
    print("[2/4] Evaluando los 11 puntos …")
    pts = evaluate_points(m, manual, {}, a); prof = perfil(pts)
    print("[3/4] Escribiendo ficha, trazabilidad y perfil …")
    write_outputs(out, meta, pts, prof, m)
    print(f"[4/4] Mantenibilidad: {fmt_rng(prof['mantenibilidad_min'], prof['mantenibilidad_max'])}/100 · completo={prof['completo']} → {out}")


def cmd_aggregate(a):
    root = Path(a.dir); runs = [d for d in sorted(root.iterdir()) if (d / "metrics.json").exists()]
    if not runs:
        raise SystemExit("No hay corridas con metrics.json en " + str(root))
    ms = {d.name: json.loads((d / "metrics.json").read_text(encoding="utf-8")) for d in runs}
    rows = []
    for d in runs:
        meta = json.loads((d / "meta.json").read_text()); manual = json.loads((d / "manual.json").read_text())
        class O: aceptar_heuristicas = meta.get("aceptar_heuristicas", False)
        pts = evaluate_points(ms[d.name], manual, {}, O); prof = perfil(pts)
        write_outputs(d, meta, pts, prof, ms[d.name])
        acc = None
        if (d / "acceptance.json").exists():
            acc = json.loads((d / "acceptance.json").read_text()).get("aceptacion_pct")
        rows.append((meta, pts, prof, acc))
    out = Path(a.out) if a.out else root / "_comparativo"; out.mkdir(parents=True, exist_ok=True)
    ids = list(RUBRIC["puntos"])
    with open(out / "comparativo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["run_id", "agente", "nivel", "dominio"] + ids + list(RUBRIC["pesos_subcaracteristicas"]) + ["mantenibilidad_min", "mantenibilidad_max", "completo", "aceptacion_pct"])
        for meta, pts, prof, acc in rows:
            lv = {p["id"]: (p["nivel"] or f"{p['nivel_min']}…{p['nivel_max']}") for p in pts}
            w.writerow([meta["run_id"], meta["agente"], meta["nivel"], meta["dominio"]] + [lv[i] for i in ids] +
                       [fmt_rng(v["min"], v["max"]) for v in prof["subcaracteristicas"].values()] + [prof["mantenibilidad_min"], prof["mantenibilidad_max"], prof["completo"], acc])
    L = [f"# Comparativo ({len(rows)} corridas)", "", "| Corrida | Agente | Nivel | " + " | ".join(i for i in ids) + " | Global | Aceptación % |", "|" + "---|" * (len(ids) + 5)]
    ab = {"Cumple": "✔", "Parcial": "◐", "No cumple": "✘"}
    for meta, pts, prof, acc in rows:
        L.append(f"| {meta['run_id']} | {meta['agente']} | {meta['nivel']} | " + " | ".join(ab.get(p["nivel"], "?") for p in pts) + f" | {fmt_rng(prof['mantenibilidad_min'], prof['mantenibilidad_max'])} | {'n/d' if acc is None else acc} |")
    (out / "comparativo.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Comparativo escrito en {out} ({len(rows)} corridas)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("app"); r.add_argument("--out", required=True)
    for k in ("agente", "modelo", "nivel", "dominio", "run-id", "manual", "layers", "test-cmd"):
        r.add_argument("--" + k)
    r.add_argument("--run-tests", action="store_true"); r.add_argument("--offline", action="store_true")
    r.add_argument("--aceptar-heuristicas", action="store_true")
    g = sp.add_parser("aggregate"); g.add_argument("dir"); g.add_argument("--out")
    a = ap.parse_args()
    a.run_id = getattr(a, "run_id", None); a.test_cmd = getattr(a, "test_cmd", None)
    {"run": cmd_run, "aggregate": cmd_aggregate}[a.cmd](a)


if __name__ == "__main__":
    main()
