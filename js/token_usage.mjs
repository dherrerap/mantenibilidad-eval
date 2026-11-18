#!/usr/bin/env node
// token_usage.mjs — Tokens consumed by the AI agent in each phase of an application's life (initial, r2). Port of token_usage.py:
// same sources (Claude Code transcripts and results, Codex rollouts and `codex exec --json`, manual figures), same normalization
// (input includes the cache, output includes reasoning) and the same token-usage/<app>.json records. See token_usage.py for details.
//   node js/token_usage.mjs scan [--apps-dir apps] [--claude-dir …] [--codex-dir …]
//   node js/token_usage.mjs record apps/claude-n1 --phase initial --from <transcript.jsonl> [<more files> …] [--with-subagents] [--append]
//   node js/token_usage.mjs record apps/claude-n1 --phase r2 --input 1200000 --output 45000 --note "from /cost"
//   node js/token_usage.mjs show [apps/claude-n1 …]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { F, dumps, fixed, get, isDict, loadJson, or, pyRound, readText, sorted, str, truthy } from "./lib/py.mjs";
import { nowIso } from "./evaluator/common.mjs";

const PHASES_RE = /^(initial|r\d+)$/;
const FIELDS = ["input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "total_tokens", "requests"];
export const DEFAULT_DIR = "token-usage";
export const RESULT_FILE = "token_usage.json";
const R2_MARKERS = ["r2-additional-requirements", "PROMPT-R2", "r2-prompt"];
const WIN = process.platform === "win32";

// ───────────────────────── helpers ─────────────────────────
const empty = () => Object.fromEntries(FIELDS.map((k) => [k, 0]));
function add(a, b) {
  for (const k of FIELDS) a[k] = (a[k] ?? 0) + or(get(b, k), 0);
  return a;
}
function finish(t) {
  t.total_tokens = t.input_tokens + t.output_tokens;
  return t;
}

/** JSON objects of a JSON-lines file (lines that start with "{" and parse). */
export function readLines(p) {
  const out = [];
  for (const raw of fs.readFileSync(p, "utf8").split(/\r\n|\n|\r/)) {
    const line = raw.trim();
    if (!line.startsWith("{")) continue;
    try { out.push(loadJson(line)); } catch { /* not JSON */ }
  }
  return out;
}

function textOf(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.filter((c) => isDict(c) && typeof c.text === "string").map((c) => c.text).join("\n");
  return "";
}

function span(stamps) {
  const s = sorted(stamps.filter((x) => truthy(x)));
  return s.length ? [s[0], s.at(-1)] : [null, null];
}

// ───────────────────────── parsers ─────────────────────────
/** One Claude API `usage` object, normalized. */
export function claudeUsage(u) {
  const t = empty();
  const cw = or(get(u, "cache_creation_input_tokens"), 0), cr = or(get(u, "cache_read_input_tokens"), 0);
  t.input_tokens = or(get(u, "input_tokens"), 0) + cw + cr;
  t.cache_read_tokens = cr; t.cache_write_tokens = cw;
  t.output_tokens = or(get(u, "output_tokens"), 0);
  t.reasoning_tokens = or(get(or(get(u, "output_tokens_details"), {}), "thinking_tokens"), 0);
  t.requests = 1;
  return finish(t);
}

const pathParts = (p) => path.resolve(String(p)).split(path.sep);

export function parseClaudeTranscript(lines, p) {
  const seen = new Set(), t = empty(), models = new Set(), stamps = [], prompts = [];
  let sid = null, cwd = null;
  for (const o of lines) {
    stamps.push(get(o, "timestamp"));
    sid = or(sid, get(o, "sessionId"));
    cwd = or(cwd, get(o, "cwd"));
    const msg = isDict(get(o, "message")) ? o.message : {};
    if (get(o, "type") === "user" && get(msg, "role") === "user" && prompts.length < 3) {
      const txt = textOf(get(msg, "content"));
      if (txt && !txt.startsWith("<")) prompts.push(txt);
    }
    if (get(o, "type") !== "assistant" || !isDict(get(msg, "usage"))) continue;
    const key = or(get(msg, "id"), get(o, "requestId"), get(o, "uuid"));
    if (seen.has(key)) continue;
    seen.add(key);
    if (truthy(get(msg, "model")) && !str(msg.model).startsWith("<")) models.add(msg.model);
    add(t, claudeUsage(msg.usage));
  }
  const meta = String(p).slice(0, -".jsonl".length) + ".meta.json";
  let desc = null;
  if (fs.existsSync(meta)) { try { desc = get(loadJson(fs.readFileSync(meta, "utf8")), "description"); } catch { /* unreadable */ } }
  const [start, end] = span(stamps);
  return { format: "claude-transcript", session_id: sid, subagent: pathParts(p).includes("subagents"), description: desc, cwd,
    models: sorted([...models]), started: start, ended: end, prompt: (prompts[0] || "").slice(0, 2000), ...finish(t) };
}

/** `claude -p --output-format json`: modelUsage (every model, subagents included) or, failing that, usage. */
export function parseClaudeResult(o) {
  const t = empty(), models = [];
  const mu = or(get(o, "modelUsage"), {});
  if (truthy(mu)) {
    for (const [model, u] of Object.entries(mu)) {
      models.push(model);
      add(t, claudeUsage({ input_tokens: get(u, "inputTokens"), output_tokens: get(u, "outputTokens"), cache_read_input_tokens: get(u, "cacheReadInputTokens"),
        cache_creation_input_tokens: get(u, "cacheCreationInputTokens") }));
    }
    t.requests = or(get(o, "num_turns"), 0);
  } else if (isDict(get(o, "usage"))) { add(t, claudeUsage(o.usage)); t.requests = or(get(o, "num_turns"), 1); }
  return { format: "claude-result", session_id: get(o, "session_id"), models, started: null, ended: null, cost_usd: get(o, "total_cost_usd"),
    duration_ms: get(o, "duration_ms"), ...finish(t) };
}

export function codexUsage(u) {
  const t = empty();
  t.input_tokens = or(get(u, "input_tokens"), 0);
  t.cache_read_tokens = or(get(u, "cached_input_tokens"), 0);
  t.cache_write_tokens = or(get(u, "cache_write_input_tokens"), 0);
  t.output_tokens = or(get(u, "output_tokens"), 0);
  t.reasoning_tokens = or(get(u, "reasoning_output_tokens"), 0);
  return finish(t);
}

export function parseCodexRollout(lines) {
  let last = null, n = 0, meta = {};
  const stamps = [], prompts = [], models = new Set();
  for (const o of lines) {
    stamps.push(get(o, "timestamp"));
    const p = isDict(get(o, "payload")) ? o.payload : {};
    const ty = get(o, "type");
    if (ty === "session_meta") meta = p;
    else if (ty === "turn_context" && truthy(get(p, "model"))) models.add(p.model);
    else if (ty === "event_msg" && get(p, "type") === "token_count" && isDict(get(p, "info"))) {
      const tot = get(p.info, "total_token_usage");
      if (truthy(tot)) { last = tot; n += 1; }
    } else if (ty === "response_item" && get(p, "type") === "message" && get(p, "role") === "user" && prompts.length < 3) {
      const txt = textOf(get(p, "content"));
      if (txt && !txt.trimStart().startsWith("<")) prompts.push(txt);
    }
  }
  const t = codexUsage(last || {});
  t.requests = n;
  const [start, end] = span(stamps);
  return { format: "codex-rollout", session_id: get(meta, "id"), subagent: truthy(get(meta, "parent_thread_id")), description: null, cwd: get(meta, "cwd"),
    models: sorted([...models]), started: start, ended: end, prompt: (prompts[0] || "").slice(0, 2000), ...t };
}

export function parseCodexExec(lines) {
  const t = empty();
  let sid = null;
  for (const o of lines) {
    sid = or(sid, get(o, "thread_id"));
    if (get(o, "type") === "turn.completed" && isDict(get(o, "usage"))) { add(t, codexUsage(o.usage)); t.requests += 1; }
  }
  return { format: "codex-exec", session_id: sid, models: [], started: null, ended: null, ...finish(t) };
}

/** Detects the format of an agent usage record and returns one normalized session (or throws). */
export function parseFile(p) {
  const raw = readText(p).trim();
  if (raw.startsWith("{") && !raw.includes("\n")) {
    try {
      const o = loadJson(raw);
      if (get(o, "type") === "result") return { ...parseClaudeResult(o), file: String(p) };
    } catch { /* not one JSON object */ }
  }
  const lines = readLines(p);
  for (const o of [...lines].reverse())  // agent.log of `claude -p --output-format json` may carry other output before the JSON line
    if (get(o, "type") === "result" && ("modelUsage" in o || "usage" in o) && !("sessionId" in o)) return { ...parseClaudeResult(o), file: String(p) };
  const types = new Set(lines.map((o) => get(o, "type")));
  if (types.has("session_meta") || lines.some((o) => get(o, "type") === "event_msg")) return { ...parseCodexRollout(lines), file: String(p) };
  if (types.has("turn.completed")) return { ...parseCodexExec(lines), file: String(p) };
  if (lines.some((o) => get(o, "type") === "assistant" && isDict(get(or(get(o, "message"), {}), "usage")))) return { ...parseClaudeTranscript(lines, p), file: String(p) };
  throw new Error(`${p}: no token usage found (expected a Claude Code transcript or result JSON, or a Codex rollout or exec --json output)`);
}

const sortP = (ps) => sorted(ps, (p) => path.resolve(p).split(path.sep).map((x) => (WIN ? x.toLowerCase() : x)));
const ls = (d) => { try { return fs.readdirSync(d, { withFileTypes: true }); } catch { return []; } };
const isDirP = (d) => { try { return fs.statSync(d).isDirectory(); } catch { return false; } };

/** Subagent transcripts of a Claude Code session: <session>/subagents/*.jsonl next to <session>.jsonl. */
export function subagentFiles(p) {
  if (!String(p).endsWith(".jsonl")) return [];
  const d = path.join(String(p).slice(0, -".jsonl".length), "subagents");
  return isDirP(d) ? sortP(ls(d).filter((e) => e.isFile() && e.name.endsWith(".jsonl")).map((e) => path.join(d, e.name))) : [];
}

function manualSession(a) {
  const t = empty();
  Object.assign(t, { input_tokens: a.input || 0, cache_read_tokens: a.cache_read || 0, cache_write_tokens: a.cache_write || 0, output_tokens: a.output || 0,
    reasoning_tokens: a.reasoning || 0, requests: a.requests || 0 });
  return { format: "manual", file: null, session_id: null, models: a.model ? [a.model] : [], started: null, ended: null, ...(a.cost !== undefined && a.cost !== null ? { cost_usd: F(a.cost) } : {}), ...finish(t) };
}

// ───────────────────────── storage ─────────────────────────
export const usagePath = (app, usageDir = DEFAULT_DIR) => path.join(usageDir, `${path.basename(path.resolve(app))}.json`);

export function load(p) {
  return fs.existsSync(p) ? loadJson(fs.readFileSync(p, "utf8")) : null;
}

function phaseTotals(sessions) {
  const t = empty();
  for (const s of sessions) add(t, s);
  return finish(t);
}

/** Saves (or, with append, extends) the phase of an app in its token-usage file and returns the whole record. */
export function recordPhase(p, appName, phase, sessions, note = null, append = false) {
  if (!PHASES_RE.test(phase)) throw new Error(`invalid phase '${phase}': use 'initial', 'r2', 'r3' …`);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const data = load(p) || { app: appName, phases: {} };
  const prev = append ? get(get(data.phases, phase, {}), "sessions", []) : [];
  const keep = new Set(prev.map((s) => JSON.stringify([get(s, "file"), get(s, "session_id")])));
  sessions = [...prev, ...sessions.filter((s) => !keep.has(JSON.stringify([get(s, "file"), get(s, "session_id")])) || get(s, "format") === "manual")];
  for (const s of sessions) delete s.prompt;
  const cost = sessions.filter((s) => get(s, "cost_usd") !== null).map((s) => Number(s.cost_usd));
  data.phases[phase] = { recorded: nowIso(), note, models: sorted([...new Set(sessions.flatMap((s) => get(s, "models", [])))]),
    totals: { ...phaseTotals(sessions), ...(cost.length ? { cost_usd: F(pyRound(cost.reduce((a, x) => a + x, 0), 4)) } : {}) }, sessions };
  data.phases = Object.fromEntries(sorted(Object.entries(data.phases), ([k]) => [k !== "initial", k]));
  fs.writeFileSync(p, dumps(data, 1), "utf8");
  return data;
}

/** Per-phase totals and the ratios of each later phase to the initial one (null when a phase is missing). */
export function summary(data) {
  if (!truthy(data)) return null;
  const ph = Object.fromEntries(Object.entries(get(data, "phases", {})).map(([k, v]) => [k, v.totals]));
  const out = { phases: ph };
  const ini = get(ph, "initial");
  for (const [k, t] of Object.entries(ph))
    if (k !== "initial")
      out[`${k}_vs_initial`] = Object.fromEntries(["total_tokens", "input_tokens", "output_tokens"].map((f) => [f, ini && truthy(get(ini, f)) ? F(pyRound(t[f] / ini[f], 3)) : null]));
  return out;
}

export function fmt(n) {
  if (n === null || n === undefined) return "n/a";
  return n >= 1e6 ? `${fixed(n / 1e6, 2)} M` : n >= 1e3 ? `${fixed(n / 1e3, 1)} k` : str(n);
}

// ───────────────────────── scan ─────────────────────────
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** App and phase a session seems to belong to (see token_usage.py guess). */
export function guess(session, apps) {
  let txt = or(get(session, "prompt"), "");
  const here = path.posix.basename(str(or(get(session, "cwd"), "")).replaceAll("\\", "/").replace(/\/+$/, ""));
  const isR2 = (t) => R2_MARKERS.some((m) => t.toLowerCase().includes(m.toLowerCase()));
  if (apps.includes(here)) return [here, isR2(txt) ? "r2" : "initial", [here]];
  if (truthy(get(session, "description"))) txt = session.description + "\n" + txt;
  const hits = (t) => Object.fromEntries(apps.map((a) => [a, (t.match(new RegExp(String.raw`(?<![\w-])` + escapeRe(a) + String.raw`(?![\w-])`, "g")) || []).length]).filter(([, n]) => n));
  let found = hits(txt), weak = false;
  if (!Object.keys(found).length) {  // Codex does not store the task of a subagent as a user message: fall back to the whole transcript
    let whole = "";
    try { whole = readText(session.file); } catch { whole = ""; }
    found = hits(whole); weak = true; txt = txt || whole.slice(0, 200000);
  }
  const top = sorted(Object.values(found));
  const keys = Object.keys(found);
  let app = keys.length === 1 || (keys.length && top.at(-1) > 2 * top.at(-2)) ? keys.reduce((a, k) => (found[k] > found[a] ? k : a)) : null;
  if (weak && !truthy(get(session, "subagent"))) app = null;  // a main session that does not name the app is not attributable
  const phase = isR2(txt) || /^\s*R2\b/.test(or(get(session, "description"), "")) ? "r2" : "initial";
  return [app, phase, sorted(keys)];
}

function* rglob(d, re) {
  for (const e of ls(d)) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) yield* rglob(p, re);
    else if (re.test(e.name)) yield p;
  }
}

export function candidateFiles(claudeDir, codexDir) {
  const files = [];
  if (claudeDir && isDirP(claudeDir)) {
    const top = [], sub = [];
    for (const proj of ls(claudeDir).filter((e) => e.isDirectory())) {
      const pd = path.join(claudeDir, proj.name);
      for (const e of ls(pd)) {
        if (e.isFile() && e.name.endsWith(".jsonl")) top.push(path.join(pd, e.name));
        if (e.isDirectory()) for (const s of ls(path.join(pd, e.name, "subagents"))) if (s.isFile() && s.name.endsWith(".jsonl")) sub.push(path.join(pd, e.name, "subagents", s.name));
      }
    }
    files.push(...sortP(top), ...sortP(sub));
  }
  if (codexDir && isDirP(codexDir)) files.push(...sortP([...rglob(codexDir, /^rollout-.*\.jsonl$/)]));
  return files;
}

function cmdScan(a) {
  const apps = isDirP(a.apps_dir) ? sorted(ls(a.apps_dir).filter((e) => e.isDirectory()).map((e) => e.name)) : [];
  if (!apps.length) { console.log(`No applications in ${a.apps_dir}: the sessions cannot be attributed.`); return 1; }
  const rows = [];
  for (const f of candidateFiles(a.claude_dir, a.codex_dir)) {
    let s;
    try { s = parseFile(f); } catch { continue; }
    if (!s.total_tokens) continue;
    const [app, phase, found] = guess(s, apps);
    if (app || found.length) rows.push([s, app, phase, found]);
  }
  if (!rows.length) { console.log("No session mentions any of the applications."); return 0; }
  const sortedRows = sorted(rows, (r) => [r[1] || "~", r[2], or(get(r[0], "started"), "")]);
  console.log("Sessions that mention the applications (VERIFY each one before recording it; a session that orchestrated several apps\n" +
    "is not attributable to any of them, only the subagent sessions are):\n");
  for (const [s, app, phase, found] of sortedRows) {
    const kind = (truthy(get(s, "subagent")) ? "subagent " : "") + s.format;
    console.log(`- ${app || "AMBIGUOUS (" + found.join(", ") + ")"} · ${phase} · ${kind} · ${or(get(s, "started"), "?")} · ` +
      `${fmt(s.total_tokens)} tokens (out ${fmt(s.output_tokens)})` + (truthy(get(s, "description")) ? ` · "${s.description}"` : ""));
    console.log(`    ${s.file}`);
  }
  console.log("\nSuggested commands (one per app and phase; review them first):\n");
  const groups = new Map();
  for (const [s, app, phase] of sortedRows) if (app) {
    const k = JSON.stringify([app, phase]);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(s.file);
  }
  for (const [k, fs_] of sorted([...groups])) {
    const [app, phase] = JSON.parse(k);
    console.log(`python token_usage.py record ${path.join(a.apps_dir, app)} --phase ${phase} --from ` + fs_.map((f) => `"${f}"`).join(" "));
  }
  return 0;
}

// ───────────────────────── record / show ─────────────────────────
function cmdRecord(a) {
  const sessions = [];
  for (const f of a.sources || []) {
    try {
      sessions.push(parseFile(f));
      if (a.with_subagents) sessions.push(...subagentFiles(f).map(parseFile));
    } catch (e) { console.log(`ERROR: ${e.message}`); return 1; }
  }
  if (a.input !== undefined || a.output !== undefined) sessions.push(manualSession(a));
  if (!sessions.length) { console.log("Nothing to record: pass --from <file> … or --input/--output."); return 1; }
  const p = usagePath(a.app, a.usage_dir);
  const data = recordPhase(p, path.basename(path.resolve(a.app)), a.phase, sessions, a.note ?? null, Boolean(a.append));
  const t = data.phases[a.phase].totals;
  console.log(`${path.basename(path.resolve(a.app))} · ${a.phase}: ${fmt(t.total_tokens)} tokens (input ${fmt(t.input_tokens)}, of which cache read ` +
    `${fmt(t.cache_read_tokens)}; output ${fmt(t.output_tokens)}) from ${data.phases[a.phase].sessions.length} session(s) → ${p}`);
  return 0;
}

function cmdShow(a) {
  const files = a.apps.length ? a.apps.map((x) => usagePath(x, a.usage_dir))
    : (isDirP(a.usage_dir) ? sortP(ls(a.usage_dir).filter((e) => e.isFile() && e.name.endsWith(".json")).map((e) => path.join(a.usage_dir, e.name))) : []);
  if (!files.length) { console.log(`No token records in ${a.usage_dir}/.`); return 0; }
  console.log("| App | Phase | Input | Cache read | Output | Total | Requests | vs initial |\n|---|---|---|---|---|---|---|---|");
  for (const f of files) {
    const data = load(f);
    if (!data) { console.log(`| ${path.basename(f, ".json")} | — | | | | | | |`); continue; }
    const sm = summary(data);
    for (const [ph, t] of Object.entries(sm.phases)) {
      const r = get(get(sm, `${ph}_vs_initial`) || {}, "total_tokens");
      console.log(`| ${data.app} | ${ph} | ${fmt(t.input_tokens)} | ${fmt(t.cache_read_tokens)} | ${fmt(t.output_tokens)} | ${fmt(t.total_tokens)} | ${str(t.requests)} | ` +
        `${ph === "initial" ? "" : r === null ? "n/a" : "×" + str(r)} |`);
    }
  }
  return 0;
}

export function main(argv) {
  const [cmd, ...rest] = argv;
  const a = { apps: [], sources: [] };
  const home = os.homedir();
  if (cmd === "scan") Object.assign(a, { apps_dir: "apps", claude_dir: process.env.CLAUDE_PROJECTS_DIR || path.join(home, ".claude", "projects"),
    codex_dir: process.env.CODEX_SESSIONS_DIR || path.join(home, ".codex", "sessions") });
  else if (cmd === "record" || cmd === "show") a.usage_dir = DEFAULT_DIR;
  else { console.error("usage: token_usage.mjs {scan,record,show} …"); return 2; }
  const ints = new Set(["input", "output", "cache_read", "cache_write", "reasoning", "requests"]);
  for (let i = 0; i < rest.length; i++) {
    const x = rest[i];
    if (!x.startsWith("--")) { if (cmd === "record" && !a.app) a.app = x; else a.apps.push(x); continue; }
    const k = x.slice(2).replaceAll("-", "_");
    if (k === "with_subagents" || k === "append") a[k] = true;
    else if (k === "from") { while (i + 1 < rest.length && !rest[i + 1].startsWith("--")) a.sources.push(rest[++i]); }
    else { const v = rest[++i]; a[k] = ints.has(k) ? Number.parseInt(v, 10) : k === "cost" ? Number.parseFloat(v) : v; }
  }
  if (cmd === "record" && (!a.app || !a.phase)) { console.error("usage: token_usage.mjs record <app> --phase initial|r2 …"); return 2; }
  return { scan: cmdScan, record: cmdRecord, show: cmdShow }[cmd](a);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = main(process.argv.slice(2));
