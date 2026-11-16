"""Machine-readable contract (OpenAPI/Swagger): its operations, base paths, properties and Spectral errors.
"""
import json
import re
from pathlib import Path

from evaluator.common import BIN, HERE, rel, sh, walk


def find_contracts(app):
    return [rel(p, app) for p in walk(app)
            if re.match(r"^(openapi|swagger)[\w.-]*\.(json|ya?ml)$", p.name, re.I)]


def run_contract(app, out, contracts):
    info = {"files": contracts, "spectral_errors": None, "paths": [], "properties": []}
    if not contracts:
        return info
    # operations, plus the base paths the contract declares (OpenAPI 3 servers[].url, Swagger 2 basePath): /api + /orders
    node_js = ("const Y=require('yaml'),fs=require('fs');const t=fs.readFileSync(process.argv[1],'utf8');"
               "const d=process.argv[1].endsWith('.json')?JSON.parse(t):Y.parse(t);const out=[];"
               "for(const [p,v] of Object.entries(d.paths||{}))for(const m of Object.keys(v||{}))"
               "if(['get','post','put','patch','delete'].includes(m))out.push([m.toUpperCase(),p]);"
               "const bases=(d.servers||[]).map((s)=>{try{return new URL(String(s.url||''),'http://h').pathname}catch(e){return ''}});"
               "if(d.basePath)bases.push(String(d.basePath));"
               "console.log(JSON.stringify({paths:out,bases:bases.map((b)=>b.replace(/\\/+$/,''))}))")
    rc, so, _ = sh(["node", "-e", node_js, str(Path(app) / contracts[0])], cwd=HERE)
    try:
        d = json.loads(so)
        info["paths"], info["bases"] = (d["paths"], d.get("bases", [])) if isinstance(d, dict) else (d, [])
    except Exception:
        pass
    props_js = ("const Y=require('yaml'),fs=require('fs');const t=fs.readFileSync(process.argv[1],'utf8');"
                "const d=process.argv[1].endsWith('.json')?JSON.parse(t):Y.parse(t);const s=new Set();"
                "const w=(o)=>{if(o&&typeof o==='object'){for(const [k,v] of Object.entries(o)){if(k==='properties'&&v&&typeof v==='object')Object.keys(v).forEach((x)=>s.add(x));w(v)}}};"
                "w(d);console.log(JSON.stringify([...s]))")
    rc, so, _ = sh(["node", "-e", props_js, str(Path(app) / contracts[0])], cwd=HERE)
    try:
        info["properties"] = json.loads(so)
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
