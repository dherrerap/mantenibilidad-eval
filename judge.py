#!/usr/bin/env python3
"""
judge.py — Uses a language model (the "judge") to decide the criteria that no automatic measurement can resolve, so that the
evaluation ends in a result and not in a range.

What it decides: the pending design-judgment criteria (layers C2, cohesion C3, data model C1–C5, contracts C4). It does not
decide those that depend on a missing measurement (DV8, network, test execution): those stay pending until it is available.

How: for each criterion it builds a prompt with the statement and the evidence (code included), sends it to the judge model
--votes times and takes the majority. Each decision is saved in <res>/judge.json with its justification, votes and confidence.
evaluate.py uses it with lower priority than manual review: manual.json / manual_review.json always take precedence.

Validity rules (enforced, not suggestions):
  - The judge must be a different model from the one that generated the application (meta.json); --allow-same-model overrides this and is recorded.
  - Odd number of votes. An "I don't know" vote (ok null) does not count; with no majority the criterion stays pending.
  - A sample of the decisions is saved in judge.json ("audit") for a person to review.

Usage:
  python judge.py results/<run> --model claude-opus-5-5 [--votes 3] [--cmd "claude -p --model {model}"] [--audit 0.2]

--cmd is the command that receives the prompt on standard input and writes the answer on standard output; {model} is
replaced by --model. By default it uses the Claude Code CLI.
"""
import argparse, datetime, hashlib, json, random, re, shlex, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import manual_template as mt  # noqa: E402

DEFAULT_CMD = "claude -p --model {model}"
JUDGEABLE = {"layers": {"C2"}, "cohesion": {"C3"}, "data_model": {"C1", "C2", "C3", "C4", "C5"}, "contracts": {"C4"}}
MAX_EVIDENCE = 14000  # characters per criterion
GUIDE = {
    ("layers", "C2"): "ok=true if the separation of responsibilities between layers is real: the flagged dependencies are legitimate in "
                      "this architecture, or the layers are connected through dependency injection. ok=false if there is improper coupling.",
    ("cohesion", "C3"): "ok=true only if there is NO 'god' module (very large and heavily referenced), NO shared modules that mix "
                        "unrelated responsibilities and NO excessive fragmentation. Read the code of the modules with the highest fan-out.",
    ("data_model", "C2"): "ok=true if what is queried together is stored together: data that always travels with its entity is embedded and "
                          "data that has a life of its own or grows without bound is referenced.",
    ("data_model", "C5"): "ok=true if there is no unjustified duplicated data and no fields with the same meaning but different types "
                          "across schemas.",
    ("contracts", "C4"): "ok=true if the input validation of the routes is consistent with what the contract declares.",
}


def read(app, path, n=80):
    p = Path(app) / path
    if not p.exists():
        return f"({path} not found)"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(f"{i + 1:>4} {l}" for i, l in enumerate(lines[:n]))
    return f"### {path} ({len(lines)} lines{'; first %d' % n if len(lines) > n else ''})\n{body}"


def evidence(pid, cid, res, m, point):
    app = m["app"]; rub = mt.load(res)[1]
    parts = [f"Automatic finding: {point['finding']}"] + [f"- {e}" for e in point["evidence"]]
    if pid == "layers":
        layers = json.loads((res / "detected_layers.json").read_text(encoding="utf-8")) if (res / "detected_layers.json").exists() else {}
        count = {}
        for v in layers.values():
            count[v["layer"]] = count.get(v["layer"], 0) + 1
        parts.append(f"Files per detected layer: {count}")
        files = []
        for e in point["evidence"]:
            files += [x.split(" ")[0] for x in re.findall(r"[\w./-]+\.[jt]sx?(?: \(\w+\))", e)]
        for f in dict.fromkeys(files).keys():
            parts.append(read(app, f, 60))
            if len(parts) > 8:
                break
    elif pid == "cohesion":
        md, _ = mt.cohesion_evidence(m, rub["thresholds"]["cohesion"])
        parts += md
        fns = sorted((f for f in m["ast"]["functions"] if not f["test"]), key=lambda f: -f["fanout"])
        seen = []
        for f in fns:
            if f["file"] not in seen:
                seen.append(f["file"])
            if len(seen) >= 3:
                break
        parts += [read(app, f, 90) for f in seen]
        parts.append("Production files (LOC): " + ", ".join(f"{f['path']} ({f['loc']})" for f in m["ast"]["files"] if not f["test"]))
    elif pid == "data_model":
        table, sources, _ = mt.model_evidence(m, Path(app))
        parts += table
        for f in sorted({t["file"].split(":")[0] for t in m["schema"]["tables"].values() if t.get("file")}):
            parts.append(read(app, f, 90))
        parts.append("Queries in the code (model, filter fields, sort, in loop): " + json.dumps([[q["model"], q["fields"], q["sort"], q["inLoop"]] for q in m["ast"].get("queryFields", [])], ensure_ascii=False))
        parts.append("Implemented routes: " + ", ".join(f"{r['method']} {r['path']}" for r in m["ast"]["routes"][:25]))
    elif pid == "contracts":
        parts.append("Routes and whether they validate their input: " + ", ".join(f"{r['method']} {r['path']} ({'validates' if r.get('validated') else 'unvalidated'})" for r in m["ast"]["routes"]))
        parts.append(f"Contract: {m['contract'].get('files')}; properties: {m['contract'].get('properties')}")
        parts.append("Validated fields: " + json.dumps(m["ast"].get("validationFields", []), ensure_ascii=False))
    return "\n".join(parts)[:MAX_EVIDENCE]


def build_prompt(pid, cid, statement, ev):
    guide = GUIDE.get((pid, cid), "")
    return f"""You are a software architecture reviewer evaluating the maintainability of a MERN application (MongoDB, Express, React, Node).
Decide ONE criterion from a checklist, using the evidence that follows. There is no other information: do not invent code you cannot see.

CRITERION ({pid}.{cid}): {statement}
How to decide: {guide}

EVIDENCE:
{ev}

Answer ONLY with a JSON object, with no text before or after it and no code blocks:
{{"ok": true | false | null, "justification": "at most 3 sentences citing file:line from the evidence", "confidence": "high" | "medium" | "low"}}
Use null only if the evidence is not enough to decide. If you hesitate between true and false because the criterion is not fully met, answer false."""


def parse(text):
    """Extracts the first JSON object with an 'ok' key from the response; None if there is none."""
    for cand in re.findall(r"\{.*?\}", text, re.S) + [text]:
        try:
            d = json.loads(cand)
        except ValueError:
            continue
        if isinstance(d, dict) and "ok" in d and d["ok"] in (True, False, None):
            return {"ok": d["ok"], "justification": str(d.get("justification", ""))[:600], "confidence": d.get("confidence", "medium")}
    return None


def query(cmd, prompt, timeout):
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def majority(votes):
    valid = [v for v in votes if v and v["ok"] is not None]
    yes = sum(v["ok"] for v in valid); no = len(valid) - yes
    # strict majority over ALL votes: one valid vote among three "I don't know" decides nothing
    if yes * 2 > len(votes): ok = True
    elif no * 2 > len(votes): ok = False
    else: return None
    chosen = next(v for v in valid if v["ok"] == ok)
    return {"ok": ok, "justification": chosen["justification"], "confidence": chosen["confidence"],
            "votes": [v["ok"] if v else None for v in votes], "unanimous": yes == len(valid) or no == len(valid)}


def pending(res, manual_done):
    """Judgeable criteria still undecided after the deterministic evaluation and the manual review."""
    scorecard = json.loads((res / "scorecard.json").read_text(encoding="utf-8"))["points"]
    out = []
    for p in scorecard:
        # pending, or previously decided by a judge (running the judge again replaces its decisions, it does not respect them)
        previous = [c for c, v in p["criteria"].items() if str(v.get("source", "")).startswith("judge")]
        for cid in list(p.get("pending_criteria", [])) + previous:
            if cid in JUDGEABLE.get(p["id"], ()) and cid not in manual_done.get(p["id"], {}):
                out.append((p, cid))
    return out


def main():
    for s_ in (sys.stdout, sys.stderr):
        s_.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("res", help="results folder of a run (already evaluated)")
    ap.add_argument("--model", required=True, help="judge model (different from the one that generated the app)")
    ap.add_argument("--cmd", default=DEFAULT_CMD, help="judge command; receives the prompt on stdin")
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--audit", type=float, default=0.2, help="fraction of decisions flagged for human review")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--allow-same-model", action="store_true")
    a = ap.parse_args()
    if a.votes % 2 == 0 or a.votes < 1:
        sys.exit("--votes must be odd (1, 3, 5…).")
    res = Path(a.res).resolve()
    meta = json.loads((res / "meta.json").read_text(encoding="utf-8"))
    generator = str(meta.get("model", "n/a"))
    same = generator.strip().lower() == a.model.strip().lower()
    if same and not a.allow_same_model:
        sys.exit(f"The judge ({a.model}) is the same model that generated the app: there is a bias in favor of its own style. "
                 "Use another model, or --allow-same-model (it is recorded in judge.json).")
    m = json.loads((res / "metrics.json").read_text(encoding="utf-8"))
    manual_f = res / "manual_review.json"
    manual_done = {}
    if manual_f.exists():
        for pid, crits in json.loads(manual_f.read_text(encoding="utf-8")).items():
            if isinstance(crits, dict):
                manual_done[pid] = {c: v for c, v in crits.items() if (v.get("ok") if isinstance(v, dict) else v) is not None}
    cmd = [x.replace("{model}", a.model) for x in shlex.split(a.cmd, posix=False)]
    pend = pending(res, manual_done)
    if not pend:
        print("No judgeable pending criteria."); return 0
    decisions, prompt_hash = {}, hashlib.sha256()
    for p, cid in pend:
        statement = p["criteria"][cid]["desc"]
        prompt = build_prompt(p["id"], cid, statement, evidence(p["id"], cid, res, m, p))
        prompt_hash.update(prompt.encode("utf-8"))
        votes = []
        for _ in range(a.votes):
            try:
                rc, so, se = query(cmd, prompt, a.timeout)
            except (OSError, subprocess.TimeoutExpired) as e:
                sys.exit(f"Could not run the judge ({' '.join(cmd)}): {e}")
            votes.append(parse(so) if rc == 0 else None)
        d = majority(votes)
        print(f"  {p['id']}.{cid}: " + (f"{'true' if d['ok'] else 'false'} ({d['votes']}, confidence {d['confidence']})" if d else f"no decision (votes {[v and v['ok'] for v in votes]})"))
        if d:
            decisions.setdefault(p["id"], {})[cid] = d
    decided = [(pid, cid) for pid, cs in decisions.items() for cid in cs]
    random.Random(hashlib.sha256((res.name + a.model).encode()).hexdigest()).shuffle(decided)
    n_audit = max(1, round(len(decided) * a.audit)) if decided else 0
    # inconclusive decisions are always audited: not unanimous, or low confidence
    forced = [(pid, cid) for pid, cid in decided if not decisions[pid][cid]["unanimous"] or decisions[pid][cid]["confidence"] == "low"]
    sample = list(dict.fromkeys(forced + decided[:n_audit]))
    output = {"meta": {"judge_model": a.model, "generator_model": generator, "same_model": same, "command": a.cmd, "votes": a.votes,
                       "date": datetime.datetime.now().isoformat(timespec="seconds"), "prompts_sha256": prompt_hash.hexdigest()},
              "decisions": decisions, "audit": [f"{pid}.{cid}" for pid, cid in sample]}
    (res / "judge.json").write_text(json.dumps(output, indent=1, ensure_ascii=False), encoding="utf-8")
    undecided = len(pend) - len(decided)
    print(f"Judge {a.model}: {len(decided)} decision(s), {undecided} undecided. To audit: {', '.join(output['audit']) or '—'} → {res / 'judge.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
