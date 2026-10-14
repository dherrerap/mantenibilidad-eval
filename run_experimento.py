#!/usr/bin/env python3
"""
run_experimento.py — Pipeline completo de un experimento:
  generar (agente) → compuerta de aceptación → evaluar mantenibilidad → comparativo.

El agente sólo ve el prompt y los dos .md (tecnico-<nivel>.md y requisitos); NUNCA se
le menciona la evaluación, para no contaminar sus decisiones de diseño.

Ejemplos
  # una celda
  python3 run_experimento.py --agente claude --nivel N2 --mongo mongodb://localhost:27017
  # matriz completa (2 agentes × 3 niveles × 1 repetición)
  python3 run_experimento.py --agente claude,codex --nivel N1,N2,N3 --mongo mongodb://localhost:27017
  # evaluar una app que ya existe (sin invocar al agente)
  python3 run_experimento.py --agente claude --nivel N1 --app-existente ./mi_app --sin-aceptacion

Salidas en experimentos/<id>/{proyecto/, agente.log, acceptance.json, meta.json} y
resultados/<id>/ (ficha, trazabilidad, perfil). Al final: resultados/_comparativo/.

SEGURIDAD: ejecuta código generado por un LLM (npm install/start/test). Corre esto en un
contenedor o VM desechable.
"""
import argparse, datetime, itertools, json, os, shlex, shutil, signal, socket, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPECS = HERE / "especificaciones"
# Comandos por defecto. VERIFICA los flags con `claude --help` / `codex exec --help` de TU versión.
AGENTES = {
    "claude": ["claude", "-p", "{prompt}", "--dangerously-skip-permissions"],
    "codex": ["codex", "exec", "--full-auto", "{prompt}"],
}


def sh(cmd, cwd=None, timeout=None, env=None, log=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, text=True,
                           stdout=log or subprocess.PIPE, stderr=subprocess.STDOUT)
        return p.returncode
    except subprocess.TimeoutExpired:
        return 124
    except FileNotFoundError:
        return 127


def free_port():
    with socket.socket() as s:
        s.bind(("", 0)); return s.getsockname()[1]


def wait_port(port, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(1)
    return False


def build_prompt(nivel):
    return (SPECS / "prompt-combinador.md").read_text(encoding="utf-8").replace("{NIVEL}", nivel.lower())


def generate(run_id, agente, nivel, a, expdir, proyecto):
    proyecto.mkdir(parents=True, exist_ok=True)
    for f in (f"tecnico-{nivel.lower()}.md", "requisitos-ecommerce.md"):
        shutil.copy(SPECS / f, proyecto / f)
    tpl = shlex.split(a.agent_cmd) if a.agent_cmd else AGENTES[agente]
    cmd = [x.replace("{prompt}", build_prompt(nivel)) for x in tpl]
    if a.modelo and not a.agent_cmd:
        cmd += ["--model", a.modelo]
    ver = subprocess.run([tpl[0], "--version"], capture_output=True, text=True).stdout.strip() if shutil.which(tpl[0]) else "n/d"
    t0 = time.time()
    with open(expdir / "agente.log", "w", encoding="utf-8") as log:
        rc = sh(cmd, cwd=proyecto, timeout=a.timeout_agente, log=log)
    return {"agente_cmd": tpl[0], "agente_version": ver, "rc": rc, "segundos": round(time.time() - t0)}


def acceptance(proyecto, expdir, mongo, run_id):
    be = proyecto / "backend"
    if not be.exists():
        return {"error": "no existe backend/"}
    port = free_port()
    env = {**os.environ, "PORT": str(port), "MONGODB_URI": f"{mongo.rstrip('/')}/exp_{run_id.replace('-', '_')}"}
    with open(expdir / "backend.log", "w") as log:
        if sh(["npm", "install", "--no-audit", "--no-fund"], cwd=be, timeout=900, log=log) != 0:
            return {"error": "npm install falló (ver backend.log)"}
        proc = subprocess.Popen(["npm", "start"], cwd=be, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            if not wait_port(port, 90):
                return {"error": "el backend no abrió el puerto en 90 s (ver backend.log)"}
            time.sleep(2)  # margen para el seed inicial
            sh([sys.executable, str(HERE / "acceptance_check.py"), "--base", f"http://127.0.0.1:{port}", "--out", str(expdir / "acceptance.json")], log=log)
            return json.loads((expdir / "acceptance.json").read_text())
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agente", default="claude", help="claude, codex (separados por coma)")
    ap.add_argument("--nivel", default="N1,N2,N3")
    ap.add_argument("--dominio", default="ecommerce")
    ap.add_argument("--repeticiones", type=int, default=1)
    ap.add_argument("--modelo")
    ap.add_argument("--agent-cmd", help='plantilla propia con {prompt}, p. ej. "mi-agente --run {prompt}"')
    ap.add_argument("--timeout-agente", type=int, default=3600)
    ap.add_argument("--mongo", default="mongodb://localhost:27017", help="servidor MongoDB para la compuerta (cada corrida usa su propia base)")
    ap.add_argument("--sin-aceptacion", action="store_true")
    ap.add_argument("--sin-pruebas", action="store_true", help="no ejecutar las pruebas del proyecto durante la evaluación")
    ap.add_argument("--app-existente", help="evaluar este directorio en lugar de invocar al agente")
    ap.add_argument("--dv8", action="store_true", help="calcular DL y PC con DV8 (ver dv8_metrics.py)")
    ap.add_argument("--aceptar-heuristicas", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--exp", default="experimentos"); ap.add_argument("--res", default="resultados")
    a = ap.parse_args()

    exp_root, res_root = Path(a.exp).resolve(), Path(a.res).resolve()
    for agente, nivel, rep in itertools.product(a.agente.split(","), a.nivel.split(","), range(1, a.repeticiones + 1)):
        run_id = f"{agente}-{nivel.lower()}-{a.dominio}-r{rep}"
        expdir = exp_root / run_id; expdir.mkdir(parents=True, exist_ok=True)
        proyecto = Path(a.app_existente).resolve() if a.app_existente else expdir / "proyecto"
        print(f"\n=== {run_id} ===")
        meta = {"run_id": run_id, "agente": agente, "nivel": nivel, "dominio": a.dominio, "repeticion": rep,
                "modelo": a.modelo, "fecha": datetime.datetime.now().isoformat(timespec="seconds")}
        if not a.app_existente:
            print("[generación] invocando al agente …")
            meta["generacion"] = generate(run_id, agente, nivel, a, expdir, proyecto)
            print(f"  rc={meta['generacion']['rc']} en {meta['generacion']['segundos']} s (log: {expdir / 'agente.log'})")
        if not a.sin_aceptacion:
            print("[aceptación] levantando backend y ejecutando casos …")
            meta["aceptacion"] = acceptance(proyecto, expdir, a.mongo, run_id)
            print("  ", meta["aceptacion"].get("error") or f"{meta['aceptacion']['aprobados']}/{meta['aceptacion']['total']} casos")
        (expdir / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        print("[evaluación] midiendo mantenibilidad …")
        cmd = [sys.executable, str(HERE / "evaluate.py"), "run", str(proyecto), "--out", str(res_root / run_id),
               "--agente", agente, "--modelo", a.modelo or "n/d", "--nivel", nivel, "--dominio", a.dominio, "--run-id", run_id]
        if not a.sin_pruebas: cmd.append("--run-tests")
        if a.aceptar_heuristicas: cmd.append("--aceptar-heuristicas")
        if a.offline: cmd.append("--offline")
        sh(cmd, log=sys.stdout)
        if a.dv8:  # DL/PC con DV8 y segunda pasada para incorporarlos al perfil
            print("[dv8] calculando DL y PC …")
            if sh([sys.executable, str(HERE / "dv8_metrics.py"), str(res_root / run_id)], log=sys.stdout) == 0:
                sh(cmd, log=sys.stdout)
        if (expdir / "acceptance.json").exists():
            shutil.copy(expdir / "acceptance.json", res_root / run_id / "acceptance.json")
    print("\n=== comparativo ===")
    sh([sys.executable, str(HERE / "evaluate.py"), "aggregate", str(res_root)], log=sys.stdout)


if __name__ == "__main__":
    main()
