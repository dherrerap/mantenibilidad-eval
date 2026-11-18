#!/usr/bin/env python3
"""
judge.py — Uses a language model (the "judge") to decide the criteria that no automatic measurement can resolve, so that the
evaluation ends in a result and not in a range.

What it decides: the pending design-judgment criteria (layers C2, cohesion C3, data model C1–C6, contracts C4). It does not
decide those that depend on a missing measurement (DV8, network, test execution): those stay pending until it is available.

How: the pending criteria of one point are asked together (one prompt per point, so that the same fact, e.g. a copy documented as
a snapshot, is judged the same way in every criterion it touches), with the statements and the evidence (code included). The prompt
is sent --votes times and each criterion takes its majority. The evidence is assembled by priority: the schema files and the design
documents go in whole, the rest fills the remaining room, and anything cut is listed at the end so the judge can answer "I don't know". Each decision is saved in <res>/judge.json with its justification, votes and confidence.
evaluate.py uses it with lower priority than manual review: manual.json / manual_review.json always take precedence.

Validity rules (enforced, not suggestions):
  - The judge must be a different model from the one that generated the application (meta.json); --allow-same-model overrides this and is recorded.
  - Odd number of votes. An "I don't know" vote (ok null) does not count; with no majority the criterion stays pending.
  - A sample of the decisions is saved in judge.json ("audit") for a person to review.

Usage:
  python judge.py results/<run> --model claude-opus-5-5 [--votes 3] [--cmd "claude -p --model {model}"] [--audit 0.2]

--cmd is the command that receives the prompt on standard input and writes the answer on standard output; {model} is
replaced by --model. By default it uses the Claude Code CLI: `claude` on the PATH or, if it is not there, the one an editor
extension installs (~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary, the most recent version first).
"""
import argparse, datetime, glob, hashlib, json, os, random, re, shlex, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import manual_template as mt  # noqa: E402

DEFAULT_CMD = "claude -p --model {model}"
JUDGEABLE = {"layers": {"C2"}, "cohesion": {"C3"}, "data_model": {"C1", "C2", "C3", "C4", "C5", "C6"}, "contracts": {"C4"}}
MAX_EVIDENCE = 60000  # characters per prompt (essential parts first; see assemble)
SCHEMA_LINES = 400   # schema files are shown whole up to this many lines
GUIDE = {
    ("layers", "C2"): "ok=true if the separation of responsibilities between layers is real: the flagged dependencies are legitimate in "
                      "this architecture, or the layers are connected through dependency injection. ok=false if there is improper coupling.",
    ("cohesion", "C3"): "ok=true only if there is NO 'god' module (very large and heavily referenced), NO shared modules that mix "
                        "unrelated responsibilities and NO excessive fragmentation. Read the code of the modules with the highest fan-out.",
    ("data_model", "C2"): "ok=true if the tables are normalized up to 3NF in a way that fits how the code reads and writes them (no repeating groups, "
                          "no attribute that depends on a non-key attribute) and every denormalized or derived column is justified. ok=false for N+1 "
                          "reads or unjustified duplication. {justified}",
    ("data_model", "C5"): "ok=true if there is no unjustified duplicated data and no columns with the same meaning but different types across tables. "
                          "{justified}",
    ("contracts", "C4"): "ok=true if the input validation of the routes is consistent with what the contract declares.",
}


# One policy for every criterion that asks whether a copy is justified, so that C2 and C5 cannot disagree on the same column
JUSTIFIED = ("A copy or derived column counts as justified when the README, the ER document, a design document or a schema comment "
             "states why it is kept (e.g. a point-in-time snapshot of a price or a coupon code at checkout, or a stored total kept "
             "consistent by a CHECK constraint or computed in one place); it is unjustified when nothing in the evidence explains it.")
GUIDE = {k: v.replace("{justified}", JUSTIFIED) for k, v in GUIDE.items()}
DESIGN_DOC = re.compile(r"snapshot|denormali|redundan|derived|copy of|copied|normal form|3nf", re.I)


MISSING_MODEL = {"", "n/a", "na", "none", "null", "unknown", "?"}


def find_claude():
    """Path of the Claude Code CLI: the PATH first, then the binary bundled with the editor extensions (newest version first)."""
    exe = shutil.which("claude")
    if exe:
        return exe
    name = "claude.exe" if os.name == "nt" else "claude"
    home = Path.home()
    found = []
    for ext in (".vscode", ".vscode-insiders", ".cursor", ".windsurf"):
        found += glob.glob(str(home / ext / "extensions" / "anthropic.claude-code-*" / "resources" / "native-binary" / name))
    def ver(f):
        v = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", f)
        return tuple(map(int, v.groups())) if v else (0, 0, 0)
    return max(found, key=ver) if found else None


def judge_command(cmd_text, model):
    """argv of the judge command. The default command is resolved to the CLI that find_claude locates."""
    cmd = [x.replace("{model}", model) for x in shlex.split(cmd_text, posix=False)]
    if cmd_text == DEFAULT_CMD and not shutil.which(cmd[0]):
        exe = find_claude()
        if exe:
            cmd[0] = exe
    return cmd


def norm_model(name):
    """Comparable form of a model name: lower case, without provider prefix (anthropic/, us.anthropic.), bracket suffix ([1m]),
    date suffix (-20250514) or version suffix (-v1:0)."""
    s = str(name or "").strip().lower()
    s = s.rsplit("/", 1)[-1]
    s = re.sub(r"^(?:[a-z]{2}\.)?(?:anthropic|openai)\.", "", s)
    s = re.sub(r"\[.*?\]$", "", s)
    s = re.sub(r"-v\d+(?::\d+)?$", "", s)
    s = re.sub(r"-\d{8}$", "", s)
    return s


def same_model(generator, judge):
    """True when the judge is (or may be) the generator: equal after normalization, or one is a family alias without a version
    (sonnet, opus, gpt-5…) contained in the other."""
    g, j = norm_model(generator), norm_model(judge)
    if not g or not j:
        return False
    if g == j:
        return True
    short, long_ = sorted((g, j), key=len)
    return not re.search(r"\d", short) and re.search(rf"(^|[-.]){re.escape(short)}($|[-.])", long_) is not None


def assemble(parts, limit=None):
    """parts = [(text, essential)]. The essential ones go in whole and in order; the others fill the room left, the last one cut.
    Whatever is cut or left out is listed at the end: the judge must know when the evidence is incomplete."""
    limit = limit or MAX_EVIDENCE
    room = limit - sum(len(t) for t, e in parts if e)
    out, cut = [], []
    for t, e in parts:
        if e:
            out.append(t)
        elif len(t) <= room:
            out.append(t); room -= len(t)
        elif room > 300:
            out.append(t[:room] + " […]"); cut.append(t.splitlines()[0][:100] + " (cut)"); room = 0
        else:
            cut.append(t.splitlines()[0][:100] + " (left out)")
    text = "\n".join(out)
    if len(text) > limit:  # even the essential parts do not fit
        text = text[:limit] + " […]"; cut.append("the end of the essential evidence (cut)")
    if cut:
        text += "\n\nNOTE: THE EVIDENCE IS INCOMPLETE. Cut or left out for length: " + "; ".join(cut)
    return text


def design_docs(app, skip=()):
    """docs/**/*.md that discuss normalization, copies or snapshots: where a denormalization is usually justified."""
    root = Path(app)
    out = []
    for f in sorted(root.glob("docs/**/*.md")):
        rel = f.relative_to(root).as_posix()
        if rel in skip or "node_modules" in rel:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if DESIGN_DOC.search(text):
            out.append(f"### {rel} (design document)\n" + text[:6000])
    return out


def read(app, path, n=80):
    p = Path(app) / path
    if not p.exists():
        return f"({path} not found)"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(f"{i + 1:>4} {l}" for i, l in enumerate(lines[:n]))
    return f"### {path} ({len(lines)} lines{'; first %d' % n if len(lines) > n else ''})\n{body}"


def evidence(pid, cid, res, m, point):
    """Evidence for the criteria of `pid` (`cid`: one criterion or a list of them; they share the evidence of the point)."""
    app = m["app"]; rub = mt.load(res)[1]
    parts = [f"Automatic finding: {point['finding']}"] + [f"- {e}" for e in point["evidence"]]
    optional = []  # second-priority evidence: it fills the room the essential one leaves
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
        if not files:
            # No inter-layer dependency was found (typical with dependency injection): without code there is nothing to judge, so show where
            # the wiring happens (files that belong to no layer, e.g. a composition root) and one file of each layer.
            prod = [f["path"] for f in m["ast"]["files"] if not f["test"] and not f["frontend"]]
            wiring = [p for p in prod if p not in layers and re.search(r"(compos|wiring|container|app|server|index|main)", Path(p).stem, re.I)][:3]
            per_layer = {}
            for p, v in layers.items():
                per_layer.setdefault(v["layer"], []).append(p)
            parts.append("No dependency between layers was detected. Wiring and one example per layer follow, to judge from the code whether the layers "
                         "are really separated (dependencies injected through constructors/contracts) or only look separated.")
            for f in wiring + [sorted(v)[0] for k, v in sorted(per_layer.items()) if k in ("presentation", "business", "data")]:
                parts.append(read(app, f, 70))
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
        optional.append("Production files (LOC): " + ", ".join(f"{f['path']} ({f['loc']})" for f in m["ast"]["files"] if not f["test"]))
    elif pid == "data_model":
        table, sources, _ = mt.model_evidence(m, Path(app))
        parts += table
        # The criteria ask whether denormalization is justified and whether the ER corresponds to the schema: show those documents first.
        er = m.get("er") or {}
        if er.get("text"):
            parts.append(f"### {er['file']} (the ER document delivered with the app)\n" + er["text"][:12000])
        else:
            parts.append("The app delivers no ER document.")
        for f in sorted({t["file"].split(":")[0] for t in m["schema"]["tables"].values() if t.get("file")}):
            parts.append(read(app, f, SCHEMA_LINES))
        parts += design_docs(app, skip={er.get("file")})
        optional.append("### README (first 6000 characters)\n" + ((m.get("readme") or "(no README)")[:6000]))
        optional.append("Queries in the code (model, filter fields, sort, in loop): " + json.dumps([[q["model"], q["fields"], q["sort"], q["inLoop"]] for q in m["ast"].get("queryFields", [])], ensure_ascii=False))
        optional.append("Implemented routes: " + ", ".join(f"{r['method']} {r['path']}" for r in m["ast"]["routes"][:25]))
    elif pid == "contracts":
        parts.append("Routes and whether they validate their input: " + ", ".join(f"{r['method']} {r['path']} ({'validates' if r.get('validated') else 'unvalidated'})" for r in m["ast"]["routes"]))
        parts.append(f"Contract: {m['contract'].get('files')}; properties: {m['contract'].get('properties')}")
        parts.append("Validated fields: " + json.dumps(m["ast"].get("validationFields", []), ensure_ascii=False))
    return assemble([(t, True) for t in parts] + [(t, False) for t in optional])


def build_prompt(pid, cids, statements, ev):
    """One prompt for the pending criteria `cids` of point `pid` (`statements`: cid → statement). A single criterion may be a str."""
    cids = [cids] if isinstance(cids, str) else list(cids)
    statements = statements if isinstance(statements, dict) else {cids[0]: statements}
    crit = "\n".join(f"- {pid}.{c}: {statements[c]}\n  How to decide: {GUIDE.get((pid, c), '')}" for c in cids)
    shape = ", ".join(f'"{c}": {{"ok": true | false | null, "justification": "...", "confidence": "high" | "medium" | "low"}}' for c in cids)
    return f"""You are a software architecture reviewer evaluating the maintainability of a PERN application (PostgreSQL, Express, React, Node).
Decide the following checklist criteria, using the evidence that follows. There is no other information: do not invent code you cannot see.

CRITERIA:
{crit}

Decide them together and consistently: when one fact (a column, a module, a dependency) bears on several criteria, judge it the same way in all of them.

EVIDENCE:
{ev}

Answer ONLY with a JSON object, with no text before or after it and no code blocks, with one entry per criterion:
{{{shape}}}
Each justification has at most 3 sentences citing file:line from the evidence.
Use null only if the evidence is not enough to decide; if the evidence says it is incomplete and the decision depends on what is missing
(a file shown only partially, a part cut for length), answer null. If you hesitate between true and false because the criterion is not
fully met, answer false."""


def _vote(d):
    if isinstance(d, dict) and "ok" in d and d["ok"] in (True, False, None):
        return {"ok": d["ok"], "justification": str(d.get("justification", ""))[:600], "confidence": d.get("confidence", "medium")}
    return None


def parse(text, cids=None):
    """Without `cids`: the first JSON object with an 'ok' key (a vote), or None. With `cids`: {cid: vote or None} from the first JSON
    object with an entry for any of them (a flat vote is accepted when a single criterion was asked), or None if there is none."""
    dec, text = json.JSONDecoder(), text or ""
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            d = dec.raw_decode(text, i)[0]
        except ValueError:
            continue
        if cids is None:
            if _vote(d):
                return _vote(d)
        elif isinstance(d, dict) and any(c in d for c in cids):
            return {c: _vote(d.get(c)) for c in cids}
        elif len(cids) == 1 and _vote(d):
            return {cids[0]: _vote(d)}
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
    generator = str(meta.get("model") or "n/a")
    unknown = generator.strip().lower() in MISSING_MODEL
    if unknown and not a.allow_same_model:
        sys.exit("The model that generated the app is not recorded (meta.json): it cannot be checked that the judge is a different "
                 "model. Evaluate with --model, or pass --allow-same-model to take that risk (it is recorded in judge.json).")
    same = (not unknown) and same_model(generator, a.model)
    if same and not a.allow_same_model:
        sys.exit(f"The judge ({a.model}) is the same model that generated the app ({generator}): there is a bias in favor of its own style. "
                 "Use another model, or --allow-same-model (it is recorded in judge.json).")
    m = json.loads((res / "metrics.json").read_text(encoding="utf-8"))
    manual_f = res / "manual_review.json"
    manual_done = {}
    if manual_f.exists():
        for pid, crits in json.loads(manual_f.read_text(encoding="utf-8")).items():
            if isinstance(crits, dict):
                manual_done[pid] = {c: v for c, v in crits.items() if (v.get("ok") if isinstance(v, dict) else v) is not None}
    cmd = judge_command(a.cmd, a.model)
    pend = pending(res, manual_done)
    if not pend:
        print("No judgeable pending criteria."); return 0
    decisions, prompt_hash = {}, hashlib.sha256()
    groups = {}
    for p, cid in pend:  # one prompt per point: its criteria share the evidence and must be judged consistently
        groups.setdefault(p["id"], (p, []))[1].append(cid)
    for pid, (p, cids) in groups.items():
        prompt = build_prompt(pid, cids, {c: p["criteria"][c]["desc"] for c in cids}, evidence(pid, cids, res, m, p))
        prompt_hash.update(prompt.encode("utf-8"))
        ballots = []
        for _ in range(a.votes):
            try:
                rc, so, se = query(cmd, prompt, a.timeout)
            except (OSError, subprocess.TimeoutExpired) as e:
                sys.exit(f"Could not run the judge ({' '.join(cmd)}): {e}")
            ballots.append(parse(so, cids) if rc == 0 else None)
        for cid in cids:
            votes = [b.get(cid) if b else None for b in ballots]
            d = majority(votes)
            print(f"  {pid}.{cid}: " + (f"{'true' if d['ok'] else 'false'} ({d['votes']}, confidence {d['confidence']})" if d else f"no decision (votes {[v and v['ok'] for v in votes]})"))
            if d:
                decisions.setdefault(pid, {})[cid] = d
    decided = [(pid, cid) for pid, cs in decisions.items() for cid in cs]
    random.Random(hashlib.sha256((res.name + a.model).encode()).hexdigest()).shuffle(decided)
    n_audit = max(1, round(len(decided) * a.audit)) if decided else 0
    # inconclusive decisions are always audited: not unanimous, or low confidence
    forced = [(pid, cid) for pid, cid in decided if not decisions[pid][cid]["unanimous"] or decisions[pid][cid]["confidence"] == "low"]
    sample = list(dict.fromkeys(forced + decided[:n_audit]))
    output = {"meta": {"judge_model": a.model, "generator_model": generator, "same_model": same, "generator_unknown": unknown, "command": a.cmd, "votes": a.votes,
                       "date": datetime.datetime.now().isoformat(timespec="seconds"), "prompts_sha256": prompt_hash.hexdigest()},
              "decisions": decisions, "audit": [f"{pid}.{cid}" for pid, cid in sample]}
    (res / "judge.json").write_text(json.dumps(output, indent=1, ensure_ascii=False), encoding="utf-8")
    undecided = len(pend) - len(decided)
    print(f"Judge {a.model}: {len(decided)} decision(s), {undecided} undecided. To audit: {', '.join(output['audit']) or '—'} → {res / 'judge.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
