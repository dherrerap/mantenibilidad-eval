#!/usr/bin/env python3
"""
Calcula DL (Decoupling Level) y PC (Propagation Cost) con DV8 a partir del grafo de módulos
que ya extrae evaluate.py (metrics.json -> graph), porque depends:parser de DV8 no soporta JS/TS.

Flujo: metrics.json -> matriz JSON (a partir de dv8/plantilla-matriz.json) -> core:convert-matrix (.dv8-dsm)
       -> metrics:decoupling-level y metrics:propagation-cost -> <res>/dv8/dv8_metrics.json

evaluate.py run toma esos valores (si existen) como manual["dv8"]; los valores explícitos de manual.json mandan.

Uso:
  python3 dv8_metrics.py resultados/claude-n1-ecommerce-r1 [--dv8 "C:/Program Files/DV8/bin/dv8-console.exe"]
Unhealthy Inheritance no se calcula aquí (requiere tipos de herencia que dependency-cruiser no extrae): queda en null.
"""
import argparse, copy, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DV8_POR_DEFECTO = r"C:\Program Files\DV8\bin\dv8-console.exe"


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    ruido = "Picked up JAVA_TOOL_OPTIONS"
    err = "\n".join(l for l in (p.stdout + p.stderr).splitlines() if l.strip() and ruido not in l)
    if p.returncode != 0 or err.startswith("ERROR"):
        sys.exit(f"DV8 falló ({' '.join(map(str, cmd[1:3]))}): {err or 'rc=' + str(p.returncode)}")


def construir_matriz(graph, plantilla, nombre):
    """Rellena la plantilla: variables = módulos locales; celdas = imports locales (conteo por par)."""
    tipo = next(iter(plantilla["cells"][0]["values"]))  # tipo de dependencia definido por la plantilla
    variables = sorted({m["source"] for m in graph["modules"]} |
                       {d["to"] for m in graph["modules"] for d in m["deps"] if d.get("local")})
    idx = {v: i for i, v in enumerate(variables)}
    pares = {}
    for m in graph["modules"]:
        for d in m["deps"]:
            if d.get("local") and d["to"] in idx and d["to"] != m["source"]:
                k = (idx[m["source"]], idx[d["to"]])
                pares[k] = pares.get(k, 0) + 1
    matriz = copy.deepcopy(plantilla)
    matriz["name"] = nombre
    matriz["variables"] = variables
    matriz["cells"] = [{"src": s, "dest": t, "values": {tipo: float(n)}} for (s, t), n in sorted(pares.items())]
    return matriz, tipo


def unhealthy_inheritance(res):
    """Unhealthy Inheritance necesita una clase base definida en el proyecto: sólo así puede haber un padre que dependa
    de su hijo o un cliente que dependa de ambos. Si ninguna clase extiende a otra del proyecto (p. ej. todas heredan
    de Error) no hay jerarquía propia y el conteo es 0. Si la hay, devuelve None: se revisa a mano."""
    clases = json.loads((res / "ast.json").read_text(encoding="utf-8")).get("classes", [])
    propias = {c["name"] for c in clases}
    return 0 if not any(c.get("extends") in propias for c in clases) else None


def pct(txt):
    return round(float(str(txt).rstrip("%")) / 100.0, 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("res", help="carpeta de resultados de una corrida (con metrics.json)")
    ap.add_argument("--dv8", default=os.environ.get("DV8_CONSOLE") or shutil.which("dv8-console") or DV8_POR_DEFECTO)
    ap.add_argument("--plantilla", default=str(HERE / "dv8" / "plantilla-matriz.json"))
    a = ap.parse_args()

    res = Path(a.res).resolve()
    if not Path(a.dv8).exists():
        sys.exit(f"No se encontró dv8-console en {a.dv8} (use --dv8 o la variable DV8_CONSOLE)")
    graph = json.loads((res / "metrics.json").read_text(encoding="utf-8"))["graph"]
    plantilla = json.loads(Path(a.plantilla).read_text(encoding="utf-8"))
    out = res / "dv8"; out.mkdir(exist_ok=True)

    matriz, tipo = construir_matriz(graph, plantilla, res.name)
    (out / "matriz.json").write_text(json.dumps(matriz, indent=1), encoding="utf-8")
    run([a.dv8, "core:convert-matrix", "-outputFile", "matriz.dv8-dsm", "matriz.json"], out)
    run([a.dv8, "metrics:decoupling-level", "-outputFile", "dl.json", "matriz.dv8-dsm"], out)
    run([a.dv8, "metrics:propagation-cost", "-outputFile", "pc.json", "matriz.dv8-dsm"], out)
    dl = json.loads((out / "dl.json").read_text(encoding="utf-8"))
    pc = json.loads((out / "pc.json").read_text(encoding="utf-8"))

    uih = unhealthy_inheritance(res)
    # Se usan las variantes "sin aislados": un archivo sin dependencias (p. ej. vite.config.js) infla DL a 100% en DV8.
    resultado = {"DL": pct(dl["decouplingLevelExcludeIsolatedItems"]), "PC": pct(pc["propagationCostExcludeIsolatedItems"]),
                 "unhealthy_inheritance": uih,
                 "_origen": {"archivos": len(matriz["variables"]), "dependencias": len(matriz["cells"]), "tipo_dependencia": tipo,
                             "aislados": int(dl["numberOfIsolatedItems"]),
                             "DL_con_aislados": pct(dl["decouplingLevel"]),
                             "PC_con_aislados": pct(pc["propagationCost"]),
                             "nota": "matriz derivada de dependency-cruiser, no del parser nativo de DV8; valores sin archivos aislados"}}
    (out / "dv8_metrics.json").write_text(json.dumps(resultado, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"DV8 {res.name}: DL={resultado['DL']:.2%}  PC={resultado['PC']:.2%}  ({len(matriz['variables'])} archivos, {len(matriz['cells'])} dependencias, {resultado['_origen']['aislados']} aislados)")


if __name__ == "__main__":
    main()
