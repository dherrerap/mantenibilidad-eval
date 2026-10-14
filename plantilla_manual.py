#!/usr/bin/env python3
"""
Genera, para una corrida ya evaluada, las plantillas de la revisión manual:
  <res>/revision_manual.md          guía con el enunciado de cada criterio, la evidencia recogida y una sugerencia
  <res>/revision_manual.borrador.json   mismo formato que manual.json, con ok=null para que lo decida el evaluador

Criterios que cubre (los que el script no puede decidir): capas C2 (si quedó pendiente), cohesión C3, modelo de datos C1–C5, contratos C4.
Flujo: 1) python3 plantilla_manual.py resultados/<run>
       2) copiar revision_manual.borrador.json a revision_manual.json y completar ok=true/false (y nota)
       3) volver a ejecutar la evaluación: evaluate.py lee <res>/revision_manual.json si no se pasa --manual.
La sugerencia es una ayuda, nunca una decisión: ok queda en null hasta que el evaluador lo fije.
"""
import argparse, json
from pathlib import Path

LINEAS_MODELO = 70  # líneas de cada archivo de modelo que se copian a la guía


def cargar(res):
    m = json.loads((res / "metrics.json").read_text(encoding="utf-8"))
    rub = json.loads((Path(__file__).resolve().parent / "rubric.json").read_text(encoding="utf-8"))
    return m, rub


def fan_in(m):
    fi = {}
    for x in m["graph"]["modules"]:
        for d in x["deps"]:
            if d.get("local"):
                fi[d["to"]] = fi.get(d["to"], 0) + 1
    return fi


def evidencia_cohesion(m, T):
    fns = [f for f in m["ast"]["functions"] if not f["test"]]
    altos = sorted((f for f in fns if f["fanout"] > T["fanout_max"]), key=lambda f: -f["fanout"])
    prod = [f for f in m["ast"]["files"] if not f["test"]]
    fi = fan_in(m)
    grandes = sorted(prod, key=lambda f: -f["loc"])[:5]
    pequenos = [f["path"] for f in prod if f["loc"] < 10]
    dioses = [f"{f['path']} (LOC {f['loc']}, fan-in {fi.get(f['path'], 0)})" for f in prod
              if f["loc"] >= T["dios_loc_min"] and fi.get(f["path"], 0) >= T["dios_fanin_min"]]
    sugerido = not dioses and (len(pequenos) / len(prod) <= 0.3 if prod else True)
    md = ["- Funciones con fan-out > %d: %d de %d" % (T["fanout_max"], len(altos), len(fns))]
    md += [f"  - `{f['file']}:{f['line']}` {f['name']} (fan-out {f['fanout']}, {f['loc']} LOC)" for f in altos[:10]]
    md += [f"- Módulos 'dios' (LOC ≥ {T['dios_loc_min']} y fan-in ≥ {T['dios_fanin_min']}): " + (", ".join(dioses) or "ninguno"),
           "- Archivos más grandes: " + ", ".join(f"`{f['path']}` ({f['loc']})" for f in grandes),
           f"- Archivos de producción con < 10 LOC (posible fragmentación): {len(pequenos)} de {len(prod)}"
           + (": " + ", ".join(f"`{p}`" for p in pequenos[:8]) if pequenos else "")]
    return md, sugerido


def evidencia_modelo(m, app):
    S = m["ast"]["schemas"]
    tabla = ["| Esquema | Archivo | Campos | required | validated | refs | embebidos | índices |", "|---|---|---|---|---|---|---|---|"]
    for s in S:
        tabla.append(f"| {s['name']} | `{s['file']}` | {s['fields']} | {s['required']} | {s['validated']} | {s['refs']} | {s['embedded']} | "
                     f"{s['indexedFields'] + s['schemaIndexCalls']} |")
    fuentes = []
    for f in sorted({s["file"] for s in S}):
        p = app / f
        if p.exists():
            lineas = p.read_text(encoding="utf-8", errors="replace").splitlines()
            fuentes.append(f"<details><summary><code>{f}</code> ({len(lineas)} líneas)</summary>\n\n```js\n" + "\n".join(lineas[:LINEAS_MODELO]) + "\n```\n</details>")
    sug = {"C1": len(S) >= 1 and (len(S) == 1 or any(s["refs"] or s["embedded"] for s in S)),
           "C3": len(S) >= 1 and all(s["required"] > 0 for s in S),
           "C4": len(S) >= 1 and any(s["indexedFields"] + s["schemaIndexCalls"] for s in S)}
    return tabla, fuentes, sug


def evidencia_contratos(m, rub):
    deps = set()
    for p in m["packages"]["packages"]:
        deps |= set(p["dependencies"]) | set(p["devDependencies"])
    libs = sorted(deps & set(rub["libs_validacion"]))
    tiene = bool(m["contract"]["files"])
    return libs, tiene, len(m["ast"]["routes"])


def punto_capas(res):
    """Devuelve el punto 'capas' de la ficha si su C2 quedó pendiente de revisión manual, o None."""
    f = res / "ficha.json"
    if not f.exists():
        return None
    p = next((x for x in json.loads(f.read_text(encoding="utf-8"))["puntos"] if x["id"] == "capas"), None)
    return p if p and "C2" in p.get("criterios_pendientes", []) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("res", help="carpeta de resultados de una corrida (con metrics.json)")
    a = ap.parse_args()
    res = Path(a.res).resolve()
    m, rub = cargar(res)
    app = Path(m["app"])
    T = rub["umbrales"]["cohesion"]

    coh_md, coh_sug = evidencia_cohesion(m, T)
    tabla, fuentes, ms = evidencia_modelo(m, app)
    libs, hay_contrato, n_rutas = evidencia_contratos(m, rub)
    cont_sug = bool(libs) and hay_contrato

    capas = punto_capas(res)
    capas_md = []
    if capas:
        capas_md = ["## Capas · C2 — violaciones ≤ 5% de las dependencias entre capas", "", capas["hallazgo"], "",
                    "Evidencia (violaciones detectadas):", ""] + [f"- {e}" for e in capas["evidencia"]] + [
                    "", "Revise `layers_detectadas.json` (cada archivo trae la capa y el directorio que la decidió) y decida:",
                    "- **true** si la separación es real (p. ej. las dependencias dudosas son legítimas en esta arquitectura, o las capas se conectan por inyección de dependencias).",
                    "- **false** si hay acoplamiento indebido entre capas.",
                    "Alternativa: definir la clasificación en un `.layers.json` dentro de la app y volver a evaluar.", ""]
    L = [f"# Revisión manual — {res.name}", "",
         "Complete `ok: true/false` en `revision_manual.borrador.json` (guárdelo como `revision_manual.json`). Las sugerencias son orientativas.", ""] + capas_md + [
         "## Cohesión · C3 — lista de verificación sin hallazgos", "",
         "Criterio: no hay módulo 'dios', mezcla de responsabilidades distintas en un mismo módulo, ni fragmentación excesiva.", ""] + coh_md + [
         "", f"**Sugerencia:** {'true' if coh_sug else 'false'} (no hay módulo 'dios' ni fragmentación alta). La mezcla de responsabilidades hay que juzgarla leyendo los módulos con más fan-out.", "",
         "## Modelo de datos", "", f"{len(m['ast']['schemas'])} esquemas detectados.", ""] + tabla + ["",
         "| Criterio | Enunciado | Sugerencia |", "|---|---|---|",
         f"| C1 | Entidades y relaciones explícitas | {ms['C1']} |",
         "| C2 | Referencia o embebido coherente con el acceso (¿lo que se consulta junto está junto?) | — decide el evaluador |",
         f"| C3 | Validación de esquema (required/validate en cada esquema) | {ms['C3']} |",
         f"| C4 | Índices en campos de consulta y relación | {ms['C4']} |",
         "| C5 | Sin redundancia injustificada ni tipos inconsistentes | — decide el evaluador |", "",
         "Código de los modelos:", ""] + fuentes + ["",
         "## Contratos · C4 — validación de entradas coherente con el contrato", "",
         f"- Contrato legible por máquina: {'sí' if hay_contrato else 'no'}; rutas implementadas: {n_rutas}.",
         f"- Librerías de validación declaradas: {', '.join(libs) or 'ninguna'}.",
         f"**Sugerencia:** {'true' if cont_sug else 'false'}" + ("" if hay_contrato else " (sin contrato no hay contra qué comparar la validación)."), ""]
    (res / "revision_manual.md").write_text("\n".join(L), encoding="utf-8")

    def item(sug, nota):
        return {"ok": None, "sugerido": sug, "nota": nota}
    borrador = {"_instrucciones": "Cambie ok por true/false, guarde como revision_manual.json y vuelva a ejecutar la evaluación.",
                **({"capas": {"C2": item(None, "")}} if capas else {}),
                "cohesion": {"C3": item(coh_sug, "")},
                "modelo_datos": {"C1": item(ms["C1"], ""), "C2": item(None, ""), "C3": item(ms["C3"], ""), "C4": item(ms["C4"], ""), "C5": item(None, "")},
                "contratos": {"C4": item(cont_sug, "")}}
    (res / "revision_manual.borrador.json").write_text(json.dumps(borrador, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{res.name}: revision_manual.md y revision_manual.borrador.json")


if __name__ == "__main__":
    main()
