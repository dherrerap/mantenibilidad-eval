#!/usr/bin/env python3
"""
token_usage.py — Tokens consumed by the AI agent in each phase of an application's life.

The experiment has two generation phases per application:
  initial   creation of the project from technical-<level>.md + requirements-<domain>.md (combiner-prompt.md)
  r2        implementation of the additional requirements (r2-additional-requirements.md, r2-prompt.md) on top of it

Each phase is recorded in token-usage/<app>.json (outside apps/, so the agent never sees it) from the agent's own usage
records. `cli.py evaluate` copies it to results/<run>/token_usage.json and the report and the comparison show it. Tokens are
not part of the maintainability score: they are an efficiency indicator reported next to it.

Accepted sources (the format is detected automatically):
  - Claude Code session transcript (~/.claude/projects/<project>/<session>.jsonl, and the subagent transcripts in
    <session>/subagents/agent-*.jsonl). Messages are de-duplicated by message id: Claude Code writes one line per
    content block with the same usage repeated.
  - Claude Code result of `claude -p --output-format json` (what run_experiment.py saves in agent.log).
  - Codex session rollout (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl): the last cumulative `token_count` event.
  - Codex `codex exec --json` output: the `usage` of the `turn.completed` events.
  - Manual figures (--input/--output …), for an agent or interface that only shows totals.

Normalization (so that Claude and Codex are comparable):
  input_tokens        all input tokens processed, INCLUDING the cache reads and writes
                      (Claude: input + cache_creation + cache_read; Codex: input_tokens, which already includes cached_input_tokens)
  cache_read_tokens   part of input_tokens served from the prompt cache
  cache_write_tokens  part of input_tokens written to the cache (Claude cache_creation_input_tokens)
  output_tokens       generated tokens, INCLUDING reasoning/thinking
  reasoning_tokens    part of output_tokens that is reasoning/thinking (when the source reports it)
  total_tokens        input_tokens + output_tokens

USAGE
  python token_usage.py scan [--apps-dir apps]          lists the agent sessions found on this machine, the app and phase
                                                        each one seems to belong to, and the `record` command to save it
  python token_usage.py record apps/claude-n1 --phase initial --from <transcript.jsonl> [<more files> …] [--with-subagents]
  python token_usage.py record apps/claude-n1 --phase r2 --input 1200000 --output 45000 --note "from /cost"
  python token_usage.py show [apps/claude-n1 …]
"""
import argparse, datetime, json, os, re, sys
from pathlib import Path

PHASES_RE = re.compile(r"^(initial|r\d+)$")
FIELDS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "requests")
DEFAULT_DIR = "token-usage"
RESULT_FILE = "token_usage.json"  # copy inside results/<run>/
R2_MARKERS = ("r2-additional-requirements", "PROMPT-R2", "r2-prompt")


# ───────────────────────── helpers ─────────────────────────
def empty():
    return {k: 0 for k in FIELDS}


def add(a, b):
    for k in FIELDS:
        a[k] = a.get(k, 0) + (b.get(k) or 0)
    return a


def finish(t):
    t["total_tokens"] = t["input_tokens"] + t["output_tokens"]
    return t


def read_lines(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str))
    return ""


def span(stamps):
    stamps = sorted(s for s in stamps if s)
    return (stamps[0], stamps[-1]) if stamps else (None, None)


# ───────────────────────── parsers ─────────────────────────
def claude_usage(u):
    """Normalizes one Claude API `usage` object."""
    t = empty()
    cw, cr = u.get("cache_creation_input_tokens") or 0, u.get("cache_read_input_tokens") or 0
    t["input_tokens"] = (u.get("input_tokens") or 0) + cw + cr
    t["cache_read_tokens"], t["cache_write_tokens"] = cr, cw
    t["output_tokens"] = u.get("output_tokens") or 0
    t["reasoning_tokens"] = (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0
    t["requests"] = 1
    return finish(t)


def parse_claude_transcript(lines, path):
    seen, t, models, stamps, prompts, sid, cwd = set(), empty(), set(), [], [], None, None
    for o in lines:
        stamps.append(o.get("timestamp"))
        sid = sid or o.get("sessionId")
        cwd = cwd or o.get("cwd")
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        if o.get("type") == "user" and msg.get("role") == "user" and len(prompts) < 3:
            txt = text_of(msg.get("content"))
            if txt and not txt.startswith("<"):
                prompts.append(txt)
        if o.get("type") != "assistant" or not isinstance(msg.get("usage"), dict):
            continue
        key = msg.get("id") or o.get("requestId") or o.get("uuid")
        if key in seen:
            continue
        seen.add(key)
        if msg.get("model") and not str(msg["model"]).startswith("<"):
            models.add(msg["model"])
        add(t, claude_usage(msg["usage"]))
    meta = Path(str(path)[:-len(".jsonl")] + ".meta.json")
    desc = None
    if meta.exists():
        try:
            desc = json.loads(meta.read_text(encoding="utf-8")).get("description")
        except (OSError, json.JSONDecodeError):
            pass
    start, end = span(stamps)
    return {"format": "claude-transcript", "session_id": sid, "subagent": "subagents" in Path(path).parts, "description": desc, "cwd": cwd,
            "models": sorted(models), "started": start, "ended": end, "prompt": (prompts[0] if prompts else "")[:2000], **finish(t)}


def parse_claude_result(o):
    """`claude -p --output-format json`: modelUsage (every model, subagents included) or, failing that, usage."""
    t, models = empty(), []
    mu = o.get("modelUsage") or {}
    if mu:
        for model, u in mu.items():
            models.append(model)
            add(t, claude_usage({"input_tokens": u.get("inputTokens"), "output_tokens": u.get("outputTokens"),
                                 "cache_read_input_tokens": u.get("cacheReadInputTokens"),
                                 "cache_creation_input_tokens": u.get("cacheCreationInputTokens")}))
        t["requests"] = o.get("num_turns") or 0
    elif isinstance(o.get("usage"), dict):
        add(t, claude_usage(o["usage"])); t["requests"] = o.get("num_turns") or 1
    return {"format": "claude-result", "session_id": o.get("session_id"), "models": models, "started": None, "ended": None,
            "cost_usd": o.get("total_cost_usd"), "duration_ms": o.get("duration_ms"), **finish(t)}


def codex_usage(u):
    t = empty()
    t["input_tokens"] = u.get("input_tokens") or 0
    t["cache_read_tokens"] = u.get("cached_input_tokens") or 0
    t["cache_write_tokens"] = u.get("cache_write_input_tokens") or 0
    t["output_tokens"] = u.get("output_tokens") or 0
    t["reasoning_tokens"] = u.get("reasoning_output_tokens") or 0
    return finish(t)


def parse_codex_rollout(lines):
    last, n, stamps, prompts, meta, models = None, 0, [], [], {}, set()
    for o in lines:
        stamps.append(o.get("timestamp"))
        p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        if o.get("type") == "session_meta":
            meta = p
        elif o.get("type") == "turn_context" and p.get("model"):
            models.add(p["model"])
        elif o.get("type") == "event_msg" and p.get("type") == "token_count" and isinstance(p.get("info"), dict):
            tot = p["info"].get("total_token_usage")
            if tot:
                last, n = tot, n + 1
        elif o.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user" and len(prompts) < 3:
            txt = text_of(p.get("content"))
            if txt and not txt.lstrip().startswith("<"):
                prompts.append(txt)
    t = codex_usage(last or {})
    t["requests"] = n
    start, end = span(stamps)
    return {"format": "codex-rollout", "session_id": meta.get("id"), "subagent": bool(meta.get("parent_thread_id")), "description": None,
            "cwd": meta.get("cwd"),
            "models": sorted(models), "started": start, "ended": end, "prompt": (prompts[0] if prompts else "")[:2000], **t}


def parse_codex_exec(lines):
    t, sid = empty(), None
    for o in lines:
        sid = sid or o.get("thread_id")
        if o.get("type") == "turn.completed" and isinstance(o.get("usage"), dict):
            add(t, codex_usage(o["usage"])); t["requests"] += 1
    return {"format": "codex-exec", "session_id": sid, "models": [], "started": None, "ended": None, **finish(t)}


def parse_file(path):
    """Detects the format of an agent usage record and returns one normalized session (or raises ValueError)."""
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if raw.startswith("{") and "\n" not in raw:
        try:
            o = json.loads(raw)
            if o.get("type") == "result":
                return {**parse_claude_result(o), "file": str(path)}
        except json.JSONDecodeError:
            pass
    lines = read_lines(path)
    # agent.log of `claude -p --output-format json` may carry other output before the JSON line
    for o in reversed(lines):
        if o.get("type") == "result" and ("modelUsage" in o or "usage" in o) and "sessionId" not in o:
            return {**parse_claude_result(o), "file": str(path)}
    types = {o.get("type") for o in lines}
    if "session_meta" in types or any(o.get("type") == "event_msg" for o in lines):
        return {**parse_codex_rollout(lines), "file": str(path)}
    if "turn.completed" in types:
        return {**parse_codex_exec(lines), "file": str(path)}
    if any(o.get("type") == "assistant" and isinstance((o.get("message") or {}).get("usage"), dict) for o in lines):
        return {**parse_claude_transcript(lines, path), "file": str(path)}
    raise ValueError(f"{path}: no token usage found (expected a Claude Code transcript or result JSON, or a Codex rollout or exec --json output)")


def subagent_files(path):
    """Subagent transcripts of a Claude Code session: <session>/subagents/agent-*.jsonl next to <session>.jsonl."""
    d = Path(str(path)[:-len(".jsonl")]) / "subagents" if str(path).endswith(".jsonl") else None
    return sorted(d.glob("*.jsonl")) if d and d.is_dir() else []


def manual_session(a):
    t = empty()
    t.update({"input_tokens": a.input or 0, "cache_read_tokens": a.cache_read or 0, "cache_write_tokens": a.cache_write or 0,
              "output_tokens": a.output or 0, "reasoning_tokens": a.reasoning or 0, "requests": a.requests or 0})
    return {"format": "manual", "file": None, "session_id": None, "models": [a.model] if a.model else [], "started": None, "ended": None,
            **({"cost_usd": a.cost} if a.cost is not None else {}), **finish(t)}


# ───────────────────────── storage ─────────────────────────
def usage_path(app, usage_dir=DEFAULT_DIR):
    return Path(usage_dir) / f"{Path(app).name}.json"


def load(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def phase_totals(sessions):
    t = empty()
    for s in sessions:
        add(t, s)
    return finish(t)


def record_phase(path, app_name, phase, sessions, note=None, append=False):
    """Saves (or, with append, extends) the phase of an app in its token-usage file and returns the whole record."""
    if not PHASES_RE.match(phase):
        raise ValueError(f"invalid phase {phase!r}: use 'initial', 'r2', 'r3' …")
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    data = load(path) or {"app": app_name, "phases": {}}
    prev = data["phases"].get(phase, {}).get("sessions", []) if append else []
    keep = {(s.get("file"), s.get("session_id")) for s in prev}
    sessions = prev + [s for s in sessions if (s.get("file"), s.get("session_id")) not in keep or s.get("format") == "manual"]
    for s in sessions:
        s.pop("prompt", None)
    cost = [s["cost_usd"] for s in sessions if s.get("cost_usd") is not None]
    data["phases"][phase] = {"recorded": datetime.datetime.now().isoformat(timespec="seconds"), "note": note,
                             "models": sorted({m for s in sessions for m in s.get("models", [])}),
                             "totals": {**phase_totals(sessions), **({"cost_usd": round(sum(cost), 4)} if cost else {})},
                             "sessions": sessions}
    data["phases"] = dict(sorted(data["phases"].items(), key=lambda kv: (kv[0] != "initial", kv[0])))
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def summary(data):
    """Per-phase totals and the ratios of each later phase to the initial one (None when a phase is missing)."""
    if not data:
        return None
    ph = {k: v["totals"] for k, v in data.get("phases", {}).items()}
    out = {"phases": ph}
    ini = ph.get("initial")
    for k, t in ph.items():
        if k != "initial":
            out[f"{k}_vs_initial"] = {f: (round(t[f] / ini[f], 3) if ini and ini.get(f) else None)
                                      for f in ("total_tokens", "input_tokens", "output_tokens")}
    return out


def fmt(n):
    if n is None:
        return "n/a"
    return f"{n / 1e6:.2f} M" if n >= 1e6 else (f"{n / 1e3:.1f} k" if n >= 1e3 else str(n))


# ───────────────────────── scan ─────────────────────────
def guess(session, apps):
    """App and phase a session seems to belong to: the app whose folder the session ran in (a `codex exec` or `claude -p` launched in
    apps/<app> by an orchestrator), otherwise the app its prompt names (or, failing that, its whole transcript)."""
    txt = session.get("prompt") or ""
    here = Path(str(session.get("cwd") or "").replace("\\", "/")).name
    if here in apps:
        phase = "r2" if any(m.lower() in txt.lower() for m in R2_MARKERS) else "initial"
        return here, phase, [here]
    if session.get("description"):
        txt = session["description"] + "\n" + txt
    def hits(t):
        c = {a: len(re.findall(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", t)) for a in apps}
        return {a: n for a, n in c.items() if n}
    found, weak = hits(txt), False
    if not found:  # Codex does not store the task of a subagent as a user message: fall back to the whole transcript
        try:
            whole = Path(session["file"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            whole = ""
        found, weak = hits(whole), True; txt = txt or whole[:200000]
    top = sorted(found.values())
    app = max(found, key=found.get) if len(found) == 1 or (found and top[-1] > 2 * top[-2]) else None
    if weak and not session.get("subagent"):
        app = None  # a main session that does not name the app in its prompt (an orchestrator, an evaluation…) is not attributable
    phase = "r2" if any(m.lower() in txt.lower() for m in R2_MARKERS) or re.match(r"\s*R2\b", session.get("description") or "") else "initial"
    return app, phase, sorted(found)


def candidate_files(claude_dir, codex_dir):
    files = []
    if claude_dir and Path(claude_dir).is_dir():
        files += sorted(Path(claude_dir).glob("*/*.jsonl")) + sorted(Path(claude_dir).glob("*/*/subagents/*.jsonl"))
    if codex_dir and Path(codex_dir).is_dir():
        files += sorted(Path(codex_dir).rglob("rollout-*.jsonl"))
    return files


def cmd_scan(a):
    apps = sorted(d.name for d in Path(a.apps_dir).iterdir() if d.is_dir()) if Path(a.apps_dir).is_dir() else []
    if not apps:
        print(f"No applications in {a.apps_dir}: the sessions cannot be attributed."); return 1
    rows = []
    for f in candidate_files(a.claude_dir, a.codex_dir):
        try:
            s = parse_file(f)
        except (ValueError, OSError):
            continue
        if not s["total_tokens"]:
            continue
        app, phase, found = guess(s, apps)
        if app or found:
            rows.append((s, app, phase, found))
    if not rows:
        print("No session mentions any of the applications."); return 0
    rows.sort(key=lambda r: (r[1] or "~", r[2], r[0].get("started") or ""))
    print("Sessions that mention the applications (VERIFY each one before recording it; a session that orchestrated several apps\n"
          "is not attributable to any of them, only the subagent sessions are):\n")
    for s, app, phase, found in rows:
        kind = ("subagent " if s.get("subagent") else "") + s["format"]
        print(f"- {app or 'AMBIGUOUS (' + ', '.join(found) + ')'} · {phase} · {kind} · {s.get('started') or '?'} · "
              f"{fmt(s['total_tokens'])} tokens (out {fmt(s['output_tokens'])})" + (f" · \"{s['description']}\"" if s.get("description") else ""))
        print(f"    {s['file']}")
    print("\nSuggested commands (one per app and phase; review them first):\n")
    groups = {}
    for s, app, phase, _ in rows:
        if app:
            groups.setdefault((app, phase), []).append(s["file"])
    for (app, phase), fs in sorted(groups.items()):
        print(f'python token_usage.py record {Path(a.apps_dir) / app} --phase {phase} --from ' + " ".join(f'"{f}"' for f in fs))
    return 0


# ───────────────────────── record / show ─────────────────────────
def cmd_record(a):
    sessions = []
    for f in a.sources or []:
        try:
            sessions.append(parse_file(f))
            if a.with_subagents:
                sessions += [parse_file(x) for x in subagent_files(f)]
        except (ValueError, OSError) as e:
            print(f"ERROR: {e}"); return 1
    if any(v is not None for v in (a.input, a.output)):
        sessions.append(manual_session(a))
    if not sessions:
        print("Nothing to record: pass --from <file> … or --input/--output."); return 1
    path = usage_path(a.app, a.usage_dir)
    data = record_phase(path, Path(a.app).name, a.phase, sessions, a.note, a.append)
    t = data["phases"][a.phase]["totals"]
    print(f"{Path(a.app).name} · {a.phase}: {fmt(t['total_tokens'])} tokens (input {fmt(t['input_tokens'])}, of which cache read "
          f"{fmt(t['cache_read_tokens'])}; output {fmt(t['output_tokens'])}) from {len(data['phases'][a.phase]['sessions'])} session(s) → {path}")
    return 0


def cmd_show(a):
    files = [usage_path(x, a.usage_dir) for x in a.apps] if a.apps else sorted(Path(a.usage_dir).glob("*.json"))
    if not files:
        print(f"No token records in {a.usage_dir}/."); return 0
    print("| App | Phase | Input | Cache read | Output | Total | Requests | vs initial |\n|---|---|---|---|---|---|---|---|")
    for f in files:
        data = load(f)
        if not data:
            print(f"| {f.stem} | — | | | | | | |"); continue
        sm = summary(data)
        for ph, t in sm["phases"].items():
            r = (sm.get(f"{ph}_vs_initial") or {}).get("total_tokens")
            print(f"| {data['app']} | {ph} | {fmt(t['input_tokens'])} | {fmt(t['cache_read_tokens'])} | {fmt(t['output_tokens'])} | "
                  f"{fmt(t['total_tokens'])} | {t['requests']} | {'' if ph == 'initial' else ('n/a' if r is None else f'×{r}')} |")
    return 0


def main(argv=None):
    for s_ in (sys.stdout, sys.stderr):
        s_.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    home = Path.home()
    s = sp.add_parser("scan", help="find the agent sessions of each app on this machine")
    s.add_argument("--apps-dir", default="apps")
    s.add_argument("--claude-dir", default=os.environ.get("CLAUDE_PROJECTS_DIR", str(home / ".claude" / "projects")))
    s.add_argument("--codex-dir", default=os.environ.get("CODEX_SESSIONS_DIR", str(home / ".codex" / "sessions")))
    s.set_defaults(fn=cmd_scan)
    r = sp.add_parser("record", help="record the tokens of one phase of an app")
    r.add_argument("app"); r.add_argument("--phase", required=True, help="initial | r2")
    r.add_argument("--from", dest="sources", nargs="+", help="transcripts / result files of the agent")
    r.add_argument("--with-subagents", action="store_true", help="also add the subagent transcripts of each Claude Code session passed")
    r.add_argument("--append", action="store_true", help="add to the sessions already recorded for the phase instead of replacing them")
    for k in ("input", "output", "cache_read", "cache_write", "reasoning", "requests"):
        r.add_argument("--" + k.replace("_", "-"), dest=k, type=int)
    r.add_argument("--cost", type=float, help="cost in USD, if the agent reports it"); r.add_argument("--model")
    r.add_argument("--note"); r.add_argument("--usage-dir", default=DEFAULT_DIR)
    r.set_defaults(fn=cmd_record)
    w = sp.add_parser("show", help="table of the recorded tokens"); w.add_argument("apps", nargs="*"); w.add_argument("--usage-dir", default=DEFAULT_DIR)
    w.set_defaults(fn=cmd_show)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
