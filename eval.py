#!/usr/bin/env python3
"""
eval.py — punto de entrada único del marco de evaluación de mantenibilidad.

  python eval.py doctor                    comprueba que el entorno tiene todo lo necesario
  python eval.py evaluar [apps...]         evalúa cada app (pruebas, DV8, plantillas manuales) y agrega
  python eval.py informe                   genera resultados/informe.md con los resultados y los pendientes

Convención: cada app es una carpeta (por defecto dentro de apps/). Si se llama <agente>-<nivel> (p. ej. claude-n2)
el agente y el nivel se deducen del nombre. Las opciones pueden ir en experimento.json (ver experimento.ejemplo.json);
la línea de comandos manda sobre el archivo.

Revisión manual: evaluar deja resultados/<run>/revision_manual.md y revision_manual.borrador.json. Copie el borrador a
revision_manual.json, complete ok=true/false y vuelva a ejecutar evaluar: se lee solo.
"""
import argparse, datetime, json, os, platform, re, shutil, socket, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
UTF8 = {**os.environ, "PYTHONIOENCODING": "utf-8"}
sys.path.insert(0, str(HERE))
from dv8_metrics import DV8_POR_DEFECTO  # noqa: E402

OK, FALLA, AVISO = "✔", "✘", "!"
SIMBOLO = {"Cumple": "✔", "Parcial": "◐", "No cumple": "✘"}


def ejecutar(cmd, cwd=None, timeout=1800):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=UTF8, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def version(cmd):
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        rc, out = ejecutar([exe] + cmd[1:], timeout=30)
        return out.strip().splitlines()[-1] if rc == 0 and out.strip() else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def buscar_dv8():
    for c in (os.environ.get("DV8_CONSOLE"), shutil.which("dv8-console"), DV8_POR_DEFECTO):
        if c and Path(c).exists():
            return c
    return None


# ───────────────────────── doctor ─────────────────────────
def cmd_doctor(a):
    filas = []  # (estado, nombre, detalle, ayuda)

    def add(ok, nombre, detalle, ayuda="", requerido=True):
        filas.append((OK if ok else (FALLA if requerido else AVISO), nombre, detalle, "" if ok else ayuda, requerido))

    add(sys.version_info >= (3, 9), "Python ≥ 3.9", platform.python_version(), "Instale Python 3.9 o superior (python.org).")
    node = version(["node", "--version"])
    nmajor = int(re.match(r"v?(\d+)", node).group(1)) if node else 0
    add(nmajor >= 18, "Node.js ≥ 18", node or "no encontrado", "Instale Node.js 18 o superior (nodejs.org).")
    add(bool(shutil.which("npm")), "npm", version(["npm", "--version"]) or "no encontrado", "npm viene con Node.js.")
    faltan = [d for d in ("ts-morph", "dependency-cruiser", "depcheck") if not (HERE / "node_modules" / d / "package.json").exists()]
    add(not faltan, "Dependencias del evaluador", "instaladas" if not faltan else "faltan: " + ", ".join(faltan),
        f"Ejecute 'npm install' en {HERE}.")
    try:
        json.loads((HERE / "rubric.json").read_text(encoding="utf-8")); rub = True
    except (OSError, ValueError):
        rub = False
    add(rub, "rubric.json", "válido" if rub else "ausente o inválido", "Restaure rubric.json del repositorio.")
    dv8 = buscar_dv8()
    estado = "no encontrado"
    if dv8:
        try:
            rc, out = ejecutar([dv8, "license:status"], timeout=90)
            estado = "licencia válida" if '"valid"' in out else "licencia no válida"
        except (subprocess.TimeoutExpired, OSError):
            estado = "no respondió"
    add(estado == "licencia válida", "DV8 (opcional: DL y PC)", f"{dv8 or '—'} · {estado}",
        "Sin DV8, DL y PC quedan pendientes; use --sin-dv8 o instale DV8 y defina DV8_CONSOLE.", requerido=False)
    try:
        socket.create_connection(("registry.npmjs.org", 443), timeout=5).close(); red = True
    except OSError:
        red = False
    add(red, "Red hacia el registro de npm (opcional)", "accesible" if red else "sin acceso",
        "Sin red, use --offline: versiones y vulnerabilidades quedan pendientes.", requerido=False)
    apps = HERE / "apps"
    n = len([d for d in apps.iterdir() if d.is_dir()]) if apps.exists() else 0
    add(n > 0, "Carpeta apps/", f"{n} aplicación(es)", "Cree apps/<agente>-<nivel>/ con cada aplicación generada.", requerido=False)

    for estado, nombre, detalle, ayuda, _ in filas:
        print(f" {estado}  {nombre:<44} {detalle}")
        if ayuda:
            print(f"      → {ayuda}")
    bloqueantes = [f for f in filas if f[0] == FALLA]
    print("\n" + ("Entorno listo." if not bloqueantes else f"Faltan {len(bloqueantes)} requisito(s) obligatorio(s)."))
    return 1 if bloqueantes else 0


# ───────────────────────── evaluar ─────────────────────────
def cargar_config(ruta):
    p = Path(ruta)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def opciones(a):
    cfg = cargar_config(a.config)
    def pick(nombre, defecto):
        v = getattr(a, nombre)
        return v if v not in (None, False) else cfg.get(nombre, defecto)
    return {"apps": a.apps or cfg.get("apps") or None, "apps_dir": pick("apps_dir", "apps"), "res": pick("res", "resultados"),
            "dominio": pick("dominio", "ecommerce"), "modelo": pick("modelo", "n/d"), "rep": pick("rep", 1),
            "sin_pruebas": pick("sin_pruebas", False), "sin_dv8": pick("sin_dv8", False), "offline": pick("offline", False),
            "aceptar_heuristicas": pick("aceptar_heuristicas", False)}


def identidad(nombre):
    m = re.fullmatch(r"(?P<ag>[A-Za-z0-9]+)-(?P<nv>[Nn]\d+)", nombre)
    return (m["ag"].lower(), m["nv"].upper()) if m else (nombre, "n/d")


def ultima(salida, patron):
    return next((l.strip() for l in reversed(salida.splitlines()) if re.search(patron, l)), None)


def evaluar_app(app, o, dv8):
    agente, nivel = identidad(app.name)
    run_id = f"{app.name}-{o['dominio']}-r{o['rep']}"
    out = Path(o["res"]).resolve() / run_id
    cmd = [PY, str(HERE / "evaluate.py"), "run", str(app), "--out", str(out), "--agente", agente, "--modelo", o["modelo"],
           "--nivel", nivel, "--dominio", o["dominio"], "--run-id", run_id]
    if not o["sin_pruebas"]: cmd.append("--run-tests")
    if o["offline"]: cmd.append("--offline")
    if o["aceptar_heuristicas"]: cmd.append("--aceptar-heuristicas")
    rc, salida = ejecutar(cmd)
    if rc != 0:
        return run_id, f"ERROR\n{salida[-800:]}"
    avisos = []
    if dv8:
        rc2, s2 = ejecutar([PY, str(HERE / "dv8_metrics.py"), str(out)] + ([] if dv8 == DV8_POR_DEFECTO else ["--dv8", dv8]))
        if rc2 == 0:
            ejecutar(cmd)  # segunda pasada: incorpora DL/PC al perfil
        else:
            avisos.append("DV8 falló: " + (ultima(s2, r"\S") or ""))
    ejecutar([PY, str(HERE / "plantilla_manual.py"), str(out)])
    resumen = ultima(salida, r"Mantenibilidad:") or ""
    resumen = re.sub(r"\s*→.*$", "", resumen.replace("[4/4] ", ""))
    return run_id, "; ".join([resumen] + avisos)


def registrar_entorno(o, dv8, apps):
    res = Path(o["res"]).resolve(); res.mkdir(parents=True, exist_ok=True)
    rub = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))
    info = {"fecha": datetime.datetime.now().isoformat(timespec="seconds"), "python": platform.python_version(),
            "node": version(["node", "--version"]), "npm": version(["npm", "--version"]), "so": platform.platform(),
            "dv8": dv8, "apps": [a.name for a in apps], "opciones": {k: v for k, v in o.items() if k != "apps"},
            "runtimes_con_soporte": rub.get("runtimes_con_soporte", {}).get("fecha")}
    (res / "entorno.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")


def cmd_evaluar(a):
    o = opciones(a)
    if o["apps"]:
        apps = [Path(p).resolve() for p in o["apps"]]
    else:
        base = Path(o["apps_dir"])
        apps = sorted(d.resolve() for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")) if base.exists() else []
    faltan = [p for p in apps if not p.is_dir()]
    if not apps or faltan:
        print("No hay aplicaciones que evaluar." if not apps else "No existe: " + ", ".join(map(str, faltan)))
        print("Cree apps/<agente>-<nivel>/ o indique las carpetas: python eval.py evaluar ruta/app1 ruta/app2")
        return 1
    dv8 = None if o["sin_dv8"] else buscar_dv8()
    if not o["sin_dv8"] and not dv8:
        print("Aviso: DV8 no encontrado; DL y PC quedarán pendientes (use --sin-dv8 para silenciar este aviso).")
    registrar_entorno(o, dv8, apps)
    errores = 0
    for i, app in enumerate(apps, 1):
        print(f"[{i}/{len(apps)}] {app.name} …", flush=True)
        run_id, resumen = evaluar_app(app, o, dv8)
        errores += resumen.startswith("ERROR")
        print(f"      {resumen}")
    rc, salida = ejecutar([PY, str(HERE / "evaluate.py"), "aggregate", str(Path(o["res"]).resolve())])
    if rc != 0:
        print("Error al agregar:\n" + salida[-600:]); return 1
    ruta = escribir_informe(Path(o["res"]).resolve())
    print(f"\nInforme: {ruta}")
    return 1 if errores else 0


# ───────────────────────── informe ─────────────────────────
def nivel_txt(p):
    if p["nivel"]:
        return SIMBOLO[p["nivel"]]
    lo, hi = p.get("nivel_min"), p.get("nivel_max")
    return f"{SIMBOLO.get(lo, '?')}…{SIMBOLO.get(hi, '?')}" if lo and hi else "?"


def rango(lo, hi):
    return "n/d" if lo is None else (f"{lo:.1f}" if lo == hi else f"{lo:.1f}–{hi:.1f}")


def escribir_informe(res):
    runs = []
    for d in sorted(res.iterdir()):
        if (d / "perfil.json").exists() and (d / "ficha.json").exists():
            runs.append((d, json.loads((d / "perfil.json").read_text(encoding="utf-8")), json.loads((d / "ficha.json").read_text(encoding="utf-8"))["puntos"]))
    if not runs:
        raise SystemExit(f"No hay resultados en {res}. Ejecute primero: python eval.py evaluar")
    entorno = json.loads((res / "entorno.json").read_text(encoding="utf-8")) if (res / "entorno.json").exists() else {}
    ids = [p["id"] for p in runs[0][2]]; nombres = {p["id"]: p["nombre"] for p in runs[0][2]}
    subs = list(runs[0][1]["subcaracteristicas"])
    L = ["# Informe de mantenibilidad", "", f"Generado: {datetime.datetime.now():%Y-%m-%d %H:%M} · {len(runs)} aplicación(es)", "",
         "## Resultado global (0–100)", "",
         "| Aplicación | Nivel | Global | " + " | ".join(subs) + " | Completo |", "|---|---|---|" + "---|" * len(subs) + "---|"]
    for d, pf, pts in runs:
        m = pf["meta"]
        L.append(f"| {m['run_id']} | {m['nivel']} | **{rango(pf['mantenibilidad_min'], pf['mantenibilidad_max'])}** | "
                 + " | ".join(rango(pf["subcaracteristicas"][s]["min"], pf["subcaracteristicas"][s]["max"]) for s in subs)
                 + f" | {'sí' if pf['completo'] else 'no'} |")
    L += ["", "Un rango (a–b) indica criterios pendientes: el valor real queda entre ambos extremos hasta completar la revisión manual.", "",
          "## Puntos de decisión", "", "✔ Cumple · ◐ Parcial · ✘ No cumple · a…b rango por criterios pendientes · ? sin evaluar", "",
          "| Punto | " + " | ".join(r[1]["meta"]["run_id"] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    for pid in ids:
        L.append(f"| {nombres[pid]} | " + " | ".join(nivel_txt(next(p for p in pts if p["id"] == pid)) for _, _, pts in runs) + " |")
    L += ["", "## Pendientes de revisión manual", ""]
    hay = False
    for d, pf, pts in runs:
        pend = [(p["id"], p["criterios_pendientes"]) for p in pts if p["criterios_pendientes"]]
        if pend:
            hay = True
            L.append(f"- **{pf['meta']['run_id']}** — " + "; ".join(f"{i}: {', '.join(c)}" for i, c in pend) + f" → `{d.name}/revision_manual.md`")
    L += ([] if hay else ["Ninguno."]) + ["", "## Hallazgos por aplicación", ""]
    for d, pf, pts in runs:
        L.append(f"### {pf['meta']['run_id']}")
        for p in pts:
            if p["nivel"] in ("Parcial", "No cumple") or (not p["nivel"] and p["nivel_min"] != p["nivel_max"]):
                L.append(f"- **{p['nombre']}** ({nivel_txt(p)}): {p['hallazgo']}")
        L.append("")
    adv = ["Cada nivel tiene una sola corrida: las diferencias entre niveles no son estadísticamente concluyentes.",
           "Las aplicaciones no se ejecutan contra MongoDB (sin compuerta de aceptación): no se sabe si funcionan.",
           "La clasificación de capas es heurística por nombre de directorio; revise `layers_detectadas.json`.",
           "Cobertura de pruebas: con `node --test` se suman como 0% los archivos que ninguna prueba carga, pero sus ramas no entran al denominador (ramas sobreestimadas)."]
    if any((d / "dv8" / "dv8_metrics.json").exists() for d, _, _ in runs):
        adv.append("DL y PC de DV8 se calculan sobre una matriz derivada de dependency-cruiser (DV8 no analiza JS/TS) y sin archivos aislados.")
    if any(r[1]["meta"].get("modelo") in (None, "n/d") for r in runs):
        adv.append("No se registró el modelo generador (`--modelo`): es una variable del experimento.")
    L += ["## Advertencias metodológicas", ""] + [f"- {x}" for x in adv]
    if entorno:
        L += ["", "## Entorno", "", f"Python {entorno.get('python')} · Node {entorno.get('node')} · npm {entorno.get('npm')} · DV8: {entorno.get('dv8') or 'no usado'}",
              f"Sistema: {entorno.get('so')} · evaluado el {entorno.get('fecha')} · tabla de runtimes con soporte fechada {entorno.get('runtimes_con_soporte')}"]
    ruta = res / "informe.md"
    ruta.write_text("\n".join(L) + "\n", encoding="utf-8")
    return ruta


def cmd_informe(a):
    ruta = escribir_informe(Path(a.res or "resultados").resolve())
    print(ruta.read_text(encoding="utf-8"))
    print(f"(guardado en {ruta})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor", help="comprueba el entorno").set_defaults(fn=cmd_doctor)
    e = sp.add_parser("evaluar", help="evalúa las aplicaciones"); e.set_defaults(fn=cmd_evaluar)
    e.add_argument("apps", nargs="*", help="carpetas de las apps (por defecto, todas las de --apps-dir)")
    e.add_argument("--config", default="experimento.json")
    e.add_argument("--apps-dir"); e.add_argument("--res"); e.add_argument("--dominio"); e.add_argument("--modelo")
    e.add_argument("--rep", type=int)
    for f in ("sin-pruebas", "sin-dv8", "offline", "aceptar-heuristicas"):
        e.add_argument("--" + f, action="store_true", default=None)
    i = sp.add_parser("informe", help="genera el informe"); i.set_defaults(fn=cmd_informe); i.add_argument("--res")
    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
