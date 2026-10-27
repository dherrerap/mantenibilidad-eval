#!/usr/bin/env python3
"""
For an already evaluated run, generates the manual review templates:
  <res>/manual_review.md             guide with the statement of each criterion, the collected evidence and a suggestion
  <res>/manual_review.draft.json     same format as manual.json, with ok=null for the evaluator to decide

Criteria it covers (those the script cannot decide): layers C2 (if left pending), cohesion C3, data model C1–C5, contracts C4.
Flow: 1) python3 manual_template.py results/<run>
      2) copy manual_review.draft.json to manual_review.json and fill in ok=true/false (and note)
      3) run the evaluation again: evaluate.py reads <res>/manual_review.json if --manual is not given.
The suggestion is an aid, never a decision: ok stays null until the evaluator sets it.
"""
import argparse, json, sys
from pathlib import Path

MODEL_LINES = 70  # lines of each model file that are copied into the guide


def load(res):
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


def cohesion_evidence(m, T):
    fns = [f for f in m["ast"]["functions"] if not f["test"]]
    high = sorted((f for f in fns if f["fanout"] > T["fanout_max"]), key=lambda f: -f["fanout"])
    prod = [f for f in m["ast"]["files"] if not f["test"]]
    fi = fan_in(m)
    largest = sorted(prod, key=lambda f: -f["loc"])[:5]
    small = [f["path"] for f in prod if f["loc"] < 10]
    gods = [f"{f['path']} (LOC {f['loc']}, fan-in {fi.get(f['path'], 0)})" for f in prod
            if f["loc"] >= T["god_loc_min"] and fi.get(f["path"], 0) >= T["god_fanin_min"]]
    suggested = not gods and (len(small) / len(prod) <= 0.3 if prod else True)
    md = ["- Functions with fan-out > %d: %d of %d" % (T["fanout_max"], len(high), len(fns))]
    md += [f"  - `{f['file']}:{f['line']}` {f['name']} (fan-out {f['fanout']}, {f['loc']} LOC)" for f in high[:10]]
    md += [f"- 'God' modules (LOC ≥ {T['god_loc_min']} and fan-in ≥ {T['god_fanin_min']}): " + (", ".join(gods) or "none"),
           "- Largest files: " + ", ".join(f"`{f['path']}` ({f['loc']})" for f in largest),
           f"- Production files with < 10 LOC (possible fragmentation): {len(small)} of {len(prod)}"
           + (": " + ", ".join(f"`{p}`" for p in small[:8]) if small else "")]
    return md, suggested


def model_evidence(m, app):
    """Table of the extracted relational schema and the code of the files that decided it. `sug` is filled by the evaluator."""
    T = m["schema"]["tables"]
    table = ["| Table | Source | Columns | Primary key | Foreign keys | Unique | Checks | Indexes |", "|---|---|---|---|---|---|---|---|"]
    for name, t in T.items():
        fks = ", ".join(f"{'+'.join(f['columns'])}→{f['ref_table']}" for f in t["foreign_keys"]) or "—"
        table.append(f"| {name} | {t['source']} | {len(t['columns'])} | {', '.join(t['primary_key']) or '**none**'} | {fks} | {len(t['unique'])} | "
                     f"{len(t['checks'])} | {len(t['indexes'])} |")
    sources = []
    for f in sorted({t["file"].split(":")[0] for t in T.values() if t.get("file")}):
        p = app / f
        if p.exists():
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            lang = "sql" if f.lower().endswith(".sql") else "js"
            sources.append(f"<details><summary><code>{f}</code> ({len(lines)} lines)</summary>\n\n```{lang}\n" + "\n".join(lines[:MODEL_LINES]) + "\n```\n</details>")
    return table, sources, {"C1": None, "C3": None, "C4": None}


def contracts_evidence(m, rub):
    deps = set()
    for p in m["packages"]["packages"]:
        deps |= set(p["dependencies"]) | set(p["devDependencies"])
    libs = sorted(deps & set(rub["libs_validation"]))
    has = bool(m["contract"]["files"])
    return libs, has, len(m["ast"]["routes"])


def layers_point(res):
    """Returns the 'layers' point of the scorecard if its C2 was left pending manual review, or None."""
    f = res / "scorecard.json"
    if not f.exists():
        return None
    p = next((x for x in json.loads(f.read_text(encoding="utf-8"))["points"] if x["id"] == "layers"), None)
    return p if p and "C2" in p.get("pending_criteria", []) else None


def main():
    for s_ in (sys.stdout, sys.stderr):  # Windows console (cp1252): avoids UnicodeEncodeError with →, ·, ≥
        s_.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("res", help="results folder of a run (with metrics.json)")
    a = ap.parse_args()
    res = Path(a.res).resolve()
    m, rub = load(res)
    app = Path(m["app"])
    T = rub["thresholds"]["cohesion"]

    coh_md, coh_sug = cohesion_evidence(m, T)
    table, sources, ms = model_evidence(m, app)
    libs, has_contract, n_routes = contracts_evidence(m, rub)
    contract_sug = bool(libs) and has_contract

    layers = layers_point(res)
    layers_md = []
    if layers:
        layers_md = ["## Layers · C2 — violations ≤ 5% of inter-layer dependencies", "", layers["finding"], "",
                     "Evidence (detected violations):", ""] + [f"- {e}" for e in layers["evidence"]] + [
                     "", "Review `detected_layers.json` (each file carries its layer and the directory that decided it) and decide:",
                     "- **true** if the separation is real (e.g. the doubtful dependencies are legitimate in this architecture, or the layers are connected through dependency injection).",
                     "- **false** if there is improper coupling between layers.",
                     "Alternative: define the classification in a `.layers.json` inside the app and evaluate again.", ""]
    L = [f"# Manual review — {res.name}", "",
         "Fill in `ok: true/false` in `manual_review.draft.json` (save it as `manual_review.json`). The suggestions are indicative.", ""] + layers_md + [
         "## Cohesion · C3 — checklist with no findings", "",
         "Criterion: there is no 'god' module, no mixing of unrelated responsibilities in one module, and no excessive fragmentation.", ""] + coh_md + [
         "", f"**Suggestion:** {'true' if coh_sug else 'false'} (no 'god' module and no high fragmentation). Mixed responsibilities must be judged by reading the modules with the highest fan-out.", "",
         "## Data model", "", f"{len(m['schema']['tables'])} table(s) detected.", ""] + table + ["",
         "| Criterion | Statement | Suggestion |", "|---|---|---|",
         f"| C1 | Explicit entities and relations | {ms['C1']} |",
         "| C2 | Reference or embedding consistent with access (is what is queried together stored together?) | — evaluator decides |",
         f"| C3 | Schema validation (required/validate in each schema) | {ms['C3']} |",
         f"| C4 | Indexes on query and relation fields | {ms['C4']} |",
         "| C5 | No unjustified redundancy or inconsistent types | — evaluator decides |", "",
         "Model code:", ""] + sources + ["",
         "## Contracts · C4 — input validation consistent with the contract", "",
         f"- Machine-readable contract: {'yes' if has_contract else 'no'}; implemented routes: {n_routes}.",
         f"- Declared validation libraries: {', '.join(libs) or 'none'}.",
         f"**Suggestion:** {'true' if contract_sug else 'false'}" + ("" if has_contract else " (without a contract there is nothing to compare the validation against)."), ""]
    (res / "manual_review.md").write_text("\n".join(L), encoding="utf-8")

    def item(sug, note):
        return {"ok": None, "suggested": sug, "note": note}
    draft = {"_instructions": "Change ok to true/false, save as manual_review.json and run the evaluation again.",
             **({"layers": {"C2": item(None, "")}} if layers else {}),
             "cohesion": {"C3": item(coh_sug, "")},
             "data_model": {"C1": item(ms["C1"], ""), "C2": item(None, ""), "C3": item(ms["C3"], ""), "C4": item(ms["C4"], ""), "C5": item(None, "")},
             "contracts": {"C4": item(contract_sug, "")}}
    (res / "manual_review.draft.json").write_text(json.dumps(draft, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{res.name}: manual_review.md and manual_review.draft.json")


if __name__ == "__main__":
    main()
