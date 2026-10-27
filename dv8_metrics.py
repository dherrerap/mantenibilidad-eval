#!/usr/bin/env python3
"""
Computes DL (Decoupling Level) and PC (Propagation Cost) with DV8 from the module graph
that evaluate.py already extracts (metrics.json -> graph), because DV8's depends:parser does not support JS/TS.

Flow: metrics.json -> JSON matrix (from dv8/matrix-template.json) -> core:convert-matrix (.dv8-dsm)
      -> metrics:decoupling-level, metrics:propagation-cost and metrics:independence-level -> <res>/dv8/dv8_metrics.json

evaluate.py run takes those values (if they exist) as manual["dv8"]; explicit values in manual.json take precedence.

Usage:
  python3 dv8_metrics.py results/claude-n1-ecommerce-r1 [--dv8 "C:/Program Files/DV8/bin/dv8-console.exe"]
Unhealthy Inheritance is not computed here (it requires inheritance types that dependency-cruiser does not extract): it stays null.
"""
import argparse, copy, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DV8_DEFAULT = r"C:\Program Files\DV8\bin\dv8-console.exe"
DSM = "matrix.dv8-dsm"


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    noise = "Picked up JAVA_TOOL_OPTIONS"
    err = "\n".join(l for l in (p.stdout + p.stderr).splitlines() if l.strip() and noise not in l)
    if p.returncode != 0 or err.startswith("ERROR"):
        sys.exit(f"DV8 failed ({' '.join(map(str, cmd[1:3]))}): {err or 'rc=' + str(p.returncode)}")


def build_matrix(graph, template, name):
    """Fills in the template: variables = local modules; cells = local imports (count per pair)."""
    dep_type = next(iter(template["cells"][0]["values"]))  # dependency type defined by the template
    variables = sorted({m["source"] for m in graph["modules"]} |
                       {d["to"] for m in graph["modules"] for d in m["deps"] if d.get("local")})
    idx = {v: i for i, v in enumerate(variables)}
    pairs = {}
    for m in graph["modules"]:
        for d in m["deps"]:
            if d.get("local") and d["to"] in idx and d["to"] != m["source"]:
                k = (idx[m["source"]], idx[d["to"]])
                pairs[k] = pairs.get(k, 0) + 1
    matrix = copy.deepcopy(template)
    matrix["name"] = name
    matrix["variables"] = variables
    matrix["cells"] = [{"src": s, "dest": t, "values": {dep_type: float(n)}} for (s, t), n in sorted(pairs.items())]
    return matrix, dep_type


def unhealthy_inheritance(res):
    """Unhealthy Inheritance needs a base class defined in the project: only then can there be a parent that depends on
    its child or a client that depends on both. If no class extends another class of the project (e.g. all inherit
    from Error) there is no own hierarchy and the count is 0. If there is one, returns None: it is reviewed by hand."""
    classes = json.loads((res / "ast.json").read_text(encoding="utf-8")).get("classes", [])
    own = {c["name"] for c in classes}
    return 0 if not any(c.get("extends") in own for c in classes) else None


def pct(txt):
    return round(float(str(txt).rstrip("%")) / 100.0, 4)


def main():
    for s_ in (sys.stdout, sys.stderr):  # Windows console (cp1252): avoids UnicodeEncodeError with →, ·, ≥
        s_.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("res", help="results folder of a run (with metrics.json)")
    ap.add_argument("--dv8", default=os.environ.get("DV8_CONSOLE") or shutil.which("dv8-console") or DV8_DEFAULT)
    ap.add_argument("--template", default=str(HERE / "dv8" / "matrix-template.json"))
    a = ap.parse_args()

    res = Path(a.res).resolve()
    if not Path(a.dv8).exists():
        sys.exit(f"dv8-console not found at {a.dv8} (use --dv8 or the DV8_CONSOLE variable)")
    graph = json.loads((res / "metrics.json").read_text(encoding="utf-8"))["graph"]
    template = json.loads(Path(a.template).read_text(encoding="utf-8"))
    out = res / "dv8"; out.mkdir(exist_ok=True)

    matrix, dep_type = build_matrix(graph, template, res.name)
    (out / "matrix.json").write_text(json.dumps(matrix, indent=1), encoding="utf-8")
    run([a.dv8, "core:convert-matrix", "-outputFile", DSM, "matrix.json"], out)
    run([a.dv8, "metrics:decoupling-level", "-outputFile", "dl.json", DSM], out)
    run([a.dv8, "metrics:propagation-cost", "-outputFile", "pc.json", DSM], out)
    run([a.dv8, "metrics:independence-level", "-outputFile", "il.json", DSM], out)
    dl = json.loads((out / "dl.json").read_text(encoding="utf-8"))
    pc = json.loads((out / "pc.json").read_text(encoding="utf-8"))
    il = json.loads((out / "il.json").read_text(encoding="utf-8"))

    uih = unhealthy_inheritance(res)
    # The "exclude isolated" variants are used: a file without dependencies (e.g. vite.config.js) inflates DL to 100% in DV8.
    result = {"DL": pct(dl["decouplingLevelExcludeIsolatedItems"]), "PC": pct(pc["propagationCostExcludeIsolatedItems"]),
              "IL": pct(il["independenceLevel"]),
              "unhealthy_inheritance": uih,
              "_origin": {"files": len(matrix["variables"]), "dependencies": len(matrix["cells"]), "dependency_type": dep_type,
                          "isolated": int(dl["numberOfIsolatedItems"]),
                          "DL_with_isolated": pct(dl["decouplingLevel"]),
                          "PC_with_isolated": pct(pc["propagationCost"]),
                          "note": "matrix derived from dependency-cruiser, not from DV8's native parser; values exclude isolated files"}}
    (out / "dv8_metrics.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"DV8 {res.name}: DL={result['DL']:.2%}  PC={result['PC']:.2%}  ({len(matrix['variables'])} files, {len(matrix['cells'])} dependencies, {result['_origin']['isolated']} isolated)")


if __name__ == "__main__":
    main()
