#!/usr/bin/env node
// judge.mjs — A language model (the "judge") decides the design-judgment criteria no automatic measurement can resolve. Port of
// judge.py (see it for the method and the validity rules): the same evidence, prompts, votes, audit sample and judge.json.
//   node js/judge.mjs results/<run> --model claude-opus-5-5 [--votes 3] [--cmd "claude -p --model {model}"] [--audit 0.2]
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dumps, get, isDict, loadJson, pyLen, pyRound, pySlice, readText, repr, sorted, splitlines, str, truthy } from "./lib/py.mjs";
import { PyRandom } from "./lib/pyrandom.mjs";
import { nowIso } from "./evaluator/common.mjs";
import { cohesionEvidence, load as mtLoad, modelEvidence } from "./manual_template.mjs";

export const DEFAULT_CMD = "claude -p --model {model}";
const JUDGEABLE = { layers: ["C2"], cohesion: ["C3"], data_model: ["C1", "C2", "C3", "C4", "C5", "C6"], contracts: ["C4"] };
const MAX_EVIDENCE = 60000, SCHEMA_LINES = 400;
export const JUSTIFIED = "A copy or derived column counts as justified when the README, the ER document, a design document or a schema comment " +
  "states why it is kept (e.g. a point-in-time snapshot of a price or a coupon code at checkout, or a stored total kept " +
  "consistent by a CHECK constraint or computed in one place); it is unjustified when nothing in the evidence explains it.";
const GUIDE = {
  "layers.C2": "ok=true if the separation of responsibilities between layers is real: the flagged dependencies are legitimate in " +
    "this architecture, or the layers are connected through dependency injection. ok=false if there is improper coupling.",
  "cohesion.C3": "ok=true only if there is NO 'god' module (very large and heavily referenced), NO shared modules that mix " +
    "unrelated responsibilities and NO excessive fragmentation. Read the code of the modules with the highest fan-out.",
  "data_model.C2": "ok=true if the tables are normalized up to 3NF in a way that fits how the code reads and writes them (no repeating groups, " +
    "no attribute that depends on a non-key attribute) and every denormalized or derived column is justified. ok=false for N+1 " +
    "reads or unjustified duplication. " + JUSTIFIED,
  "data_model.C5": "ok=true if there is no unjustified duplicated data and no columns with the same meaning but different types across tables. " + JUSTIFIED,
  "contracts.C4": "ok=true if the input validation of the routes is consistent with what the contract declares.",
};
const DESIGN_DOC = /snapshot|denormali|redundan|derived|copy of|copied|normal form|3nf/i;
const MISSING_MODEL = new Set(["", "n/a", "na", "none", "null", "unknown", "?"]);
const WIN = process.platform === "win32";

function which(name) {
  const exts = WIN ? (process.env.PATHEXT || ".EXE").split(";") : [""];
  for (const d of (process.env.PATH || "").split(path.delimiter)) for (const e of ["", ...exts]) {
    const p = path.join(d, name + e);
    try { if (fs.statSync(p).isFile()) return p; } catch { /* next */ }
  }
  return null;
}

/** The Claude Code CLI: the PATH first, then the binary bundled with the editor extensions (newest version first). */
export function findClaude() {
  const exe = which("claude");
  if (exe) return exe;
  const name = WIN ? "claude.exe" : "claude", found = [];
  for (const ext of [".vscode", ".vscode-insiders", ".cursor", ".windsurf"]) {
    const d = path.join(os.homedir(), ext, "extensions");
    let entries = [];
    try { entries = fs.readdirSync(d); } catch { continue; }
    for (const e of entries) if (e.startsWith("anthropic.claude-code-")) { const p = path.join(d, e, "resources", "native-binary", name); if (fs.existsSync(p)) found.push(p); }
  }
  const ver = (f) => { const v = /claude-code-(\d+)\.(\d+)\.(\d+)/.exec(f); return v ? v.slice(1).map(Number) : [0, 0, 0]; };
  return found.length ? sorted(found, ver).at(-1) : null;
}

/** shlex.split(posix=False): whitespace-separated, a double-quoted part kept together (its quotes dropped for the process). */
const splitCmd = (t) => (t.match(/"[^"]*"|\S+/g) || []).map((x) => x.replace(/^"(.*)"$/, "$1"));

export function judgeCommand(cmdText, model) {
  const cmd = splitCmd(cmdText).map((x) => x.replaceAll("{model}", model));
  if (cmdText === DEFAULT_CMD && !which(cmd[0])) { const exe = findClaude(); if (exe) cmd[0] = exe; }
  return cmd;
}

export function normModel(name) {
  let s = str(name ?? "").trim().toLowerCase();
  s = s.split("/").at(-1);
  s = s.replace(/^(?:[a-z]{2}\.)?(?:anthropic|openai)\./, "").replace(/\[.*?\]$/, "").replace(/-v\d+(?::\d+)?$/, "").replace(/-\d{8}$/, "");
  return s;
}

export function sameModel(generator, judge) {
  const g = normModel(generator), j = normModel(judge);
  if (!g || !j) return false;
  if (g === j) return true;
  const [short, long] = sorted([g, j], (x) => x.length);
  const esc = short.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return !/\d/.test(short) && new RegExp(`(^|[-.])${esc}($|[-.])`).test(long);
}

/** parts = [[text, essential]]: essential parts whole and in order, the others fill the room left; what is cut is listed. */
export function assemble(parts, limit = MAX_EVIDENCE) {
  let room = limit - parts.filter(([, e]) => e).reduce((a, [t]) => a + pyLen(t), 0);
  const out = [], cut = [];
  const head = (t) => pySlice(splitlines(t)[0] ?? "", 0, 100);
  for (const [t, e] of parts) {
    if (e) out.push(t);
    else if (pyLen(t) <= room) { out.push(t); room -= pyLen(t); }
    else if (room > 300) { out.push(pySlice(t, 0, room) + " […]"); cut.push(head(t) + " (cut)"); room = 0; }
    else cut.push(head(t) + " (left out)");
  }
  let text = out.join("\n");
  if (pyLen(text) > limit) { text = pySlice(text, 0, limit) + " […]"; cut.push("the end of the essential evidence (cut)"); }
  if (cut.length) text += "\n\nNOTE: THE EVIDENCE IS INCOMPLETE. Cut or left out for length: " + cut.join("; ");
  return text;
}

function mdFiles(dir, base) {
  const out = [];
  let es;
  try { es = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of es) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...mdFiles(p, base));
    else if ((WIN ? /\.md$/i : /\.md$/).test(e.name)) out.push(p);
  }
  return out;
}

/** docs/**\/*.md that discuss normalization, copies or snapshots. */
function designDocs(app, skip) {
  const key = (p) => path.relative(app, p).split(path.sep).map((x) => (WIN ? x.toLowerCase() : x));
  const out = [];
  for (const f of sorted(mdFiles(path.join(app, "docs"), app), key)) {
    const rel = path.relative(app, f).split(path.sep).join("/");
    if (skip.has(rel) || rel.includes("node_modules")) continue;
    const text = readText(f);
    if (DESIGN_DOC.test(text)) out.push(`### ${rel} (design document)\n` + pySlice(text, 0, 6000));
  }
  return out;
}

function read(app, p, n = 80) {
  const f = path.join(app, p);
  if (!fs.existsSync(f)) return `(${p} not found)`;
  const lines = splitlines(readText(f));
  const body = lines.slice(0, n).map((l, i) => `${String(i + 1).padStart(4)} ${l}`).join("\n");
  return `### ${p} (${lines.length} lines${lines.length > n ? `; first ${n}` : ""})\n${body}`;
}

const stemOf = (p) => { const b = path.posix.basename(p), i = b.lastIndexOf("."); return i > 0 ? b.slice(0, i) : b; };

export function evidence(pid, cid, res, m, point) {
  const app = m.app, rub = mtLoad(res)[1];
  const parts = [`Automatic finding: ${point.finding}`, ...point.evidence.map((e) => `- ${e}`)];
  const optional = [];
  if (pid === "layers") {
    const lf = path.join(res, "detected_layers.json");
    const layers = fs.existsSync(lf) ? loadJson(fs.readFileSync(lf, "utf8")) : {};
    const count = {};
    for (const v of Object.values(layers)) count[v.layer] = (count[v.layer] ?? 0) + 1;
    parts.push(`Files per detected layer: ${repr(count)}`);
    const files = point.evidence.flatMap((e) => [...e.matchAll(/[\w./-]+\.[jt]sx?(?: \(\w+\))/g)].map((x) => x[0].split(" ")[0]));
    for (const f of [...new Set(files)]) {
      parts.push(read(app, f, 60));
      if (parts.length > 8) break;
    }
    if (!files.length) {
      const prod = m.ast.files.filter((f) => !f.test && !f.frontend).map((f) => f.path);
      const wiring = prod.filter((p) => !(p in layers) && /(compos|wiring|container|app|server|index|main)/i.test(stemOf(p))).slice(0, 3);
      const perLayer = {};
      for (const [p, v] of Object.entries(layers)) (perLayer[v.layer] ??= []).push(p);
      parts.push("No dependency between layers was detected. Wiring and one example per layer follow, to judge from the code whether the layers " +
        "are really separated (dependencies injected through constructors/contracts) or only look separated.");
      const examples = sorted(Object.entries(perLayer)).filter(([k]) => ["presentation", "business", "data"].includes(k)).map(([, v]) => sorted(v)[0]);
      for (const f of [...wiring, ...examples]) parts.push(read(app, f, 70));
    }
  } else if (pid === "cohesion") {
    const [md] = cohesionEvidence(m, rub.thresholds.cohesion);
    parts.push(...md);
    const fns = sorted(m.ast.functions.filter((f) => !f.test), (f) => -f.fanout);
    const seen = [];
    for (const f of fns) {
      if (!seen.includes(f.file)) seen.push(f.file);
      if (seen.length >= 3) break;
    }
    parts.push(...seen.map((f) => read(app, f, 90)));
    optional.push("Production files (LOC): " + m.ast.files.filter((f) => !f.test).map((f) => `${f.path} (${f.loc})`).join(", "));
  } else if (pid === "data_model") {
    const [table] = modelEvidence(m, app);
    parts.push(...table);
    const er = get(m, "er") || {};
    if (truthy(get(er, "text"))) parts.push(`### ${er.file} (the ER document delivered with the app)\n` + pySlice(er.text, 0, 12000));
    else parts.push("The app delivers no ER document.");
    for (const f of sorted([...new Set(Object.values(m.schema.tables).filter((t) => get(t, "file")).map((t) => t.file.split(":")[0]))])) parts.push(read(app, f, SCHEMA_LINES));
    parts.push(...designDocs(app, new Set([get(er, "file")])));
    optional.push("### README (first 6000 characters)\n" + pySlice(get(m, "readme") || "(no README)", 0, 6000));
    optional.push("Queries in the code (model, filter fields, sort, in loop): " + dumps(get(m.ast, "queryFields", []).map((q) => [q.model, q.fields, q.sort, q.inLoop])));
    optional.push("Implemented routes: " + m.ast.routes.slice(0, 25).map((r) => `${r.method} ${r.path}`).join(", "));
  } else if (pid === "contracts") {
    parts.push("Routes and whether they validate their input: " + m.ast.routes.map((r) => `${r.method} ${r.path} (${truthy(get(r, "validated")) ? "validates" : "unvalidated"})`).join(", "));
    parts.push(`Contract: ${str(get(m.contract, "files"))}; properties: ${str(get(m.contract, "properties"))}`);
    parts.push("Validated fields: " + dumps(get(m.ast, "validationFields", [])));
  }
  return assemble([...parts.map((t) => [t, true]), ...optional.map((t) => [t, false])]);
}

export function buildPrompt(pid, cids, statements, ev) {
  cids = typeof cids === "string" ? [cids] : [...cids];
  statements = isDict(statements) ? statements : { [cids[0]]: statements };
  const crit = cids.map((c) => `- ${pid}.${c}: ${statements[c]}\n  How to decide: ${GUIDE[`${pid}.${c}`] ?? ""}`).join("\n");
  const shape = cids.map((c) => `"${c}": {"ok": true | false | null, "justification": "...", "confidence": "high" | "medium" | "low"}`).join(", ");
  return `You are a software architecture reviewer evaluating the maintainability of a PERN application (PostgreSQL, Express, React, Node).
Decide the following checklist criteria, using the evidence that follows. There is no other information: do not invent code you cannot see.

CRITERIA:
${crit}

Decide them together and consistently: when one fact (a column, a module, a dependency) bears on several criteria, judge it the same way in all of them.

EVIDENCE:
${ev}

Answer ONLY with a JSON object, with no text before or after it and no code blocks, with one entry per criterion:
{${shape}}
Each justification has at most 3 sentences citing file:line from the evidence.
Use null only if the evidence is not enough to decide; if the evidence says it is incomplete and the decision depends on what is missing
(a file shown only partially, a part cut for length), answer null. If you hesitate between true and false because the criterion is not
fully met, answer false.`;
}

const vote = (d) => (isDict(d) && "ok" in d && [true, false, null].includes(d.ok)
  ? { ok: d.ok, justification: pySlice(str(get(d, "justification", "")), 0, 600), confidence: get(d, "confidence", "medium") } : null);

/** The first JSON value that starts at position i of `text` (json.JSONDecoder.raw_decode), or undefined. */
function rawDecode(text, i) {
  let depth = 0, inStr = false, esc = false;
  for (let k = i; k < text.length; k++) {
    const c = text[k];
    if (inStr) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === '"') inStr = false; continue; }
    if (c === '"') inStr = true;
    else if (c === "{" || c === "[") depth++;
    else if (c === "}" || c === "]") {
      depth--;
      if (depth === 0) { try { return loadJson(text.slice(i, k + 1)); } catch { return undefined; } }
    }
  }
  return undefined;
}

/** Without cids: the first JSON object with an 'ok' key (a vote). With cids: {cid: vote or null} from the first object with an
 *  entry for any of them (a flat vote when a single criterion was asked); null if there is none. */
export function parse(text, cids = null) {
  text = text || "";
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== "{") continue;
    const d = rawDecode(text, i);
    if (d === undefined) continue;
    if (cids === null) { if (vote(d)) return vote(d); }
    else if (isDict(d) && cids.some((c) => c in d)) return Object.fromEntries(cids.map((c) => [c, vote(get(d, c))]));
    else if (cids.length === 1 && vote(d)) return { [cids[0]]: vote(d) };
  }
  return null;
}

export function query(cmd, prompt, timeout) {
  const p = spawnSync(cmd[0], cmd.slice(1), { input: prompt, encoding: "utf8", timeout: timeout * 1000, maxBuffer: 64 * 1024 * 1024, windowsHide: true });
  if (p.error) throw p.error;
  return [p.status, p.stdout ?? "", p.stderr ?? ""];
}

export function majority(votes) {
  const valid = votes.filter((v) => v && v.ok !== null);
  const yes = valid.filter((v) => v.ok).length, no = valid.length - yes;
  let ok;
  if (yes * 2 > votes.length) ok = true;  // strict majority over ALL votes
  else if (no * 2 > votes.length) ok = false;
  else return null;
  const chosen = valid.find((v) => v.ok === ok);
  return { ok, justification: chosen.justification, confidence: chosen.confidence, votes: votes.map((v) => (v ? v.ok : null)), unanimous: yes === valid.length || no === valid.length };
}

/** Judgeable criteria still undecided after the deterministic evaluation and the manual review. */
export function pending(res, manualDone) {
  const pts = loadJson(fs.readFileSync(path.join(res, "scorecard.json"), "utf8")).points;
  const out = [];
  for (const p of pts) {
    const previous = Object.entries(p.criteria).filter(([, v]) => str(get(v, "source", "")).startsWith("judge")).map(([c]) => c);
    for (const cid of [...get(p, "pending_criteria", []), ...previous])
      if ((JUDGEABLE[p.id] || []).includes(cid) && !(cid in (manualDone[p.id] || {}))) out.push([p, cid]);
  }
  return out;
}

/** Runs the judge on a run; returns the lines to print, writes <res>/judge.json. Throws with the message of a refusal. */
export function runJudge(resArg, { model, cmd = DEFAULT_CMD, votes = 3, audit = 0.2, timeout = 300, allow_same_model = false }) {
  const log = [];
  if (votes % 2 === 0 || votes < 1) throw new Error("--votes must be odd (1, 3, 5…).");
  const res = path.resolve(resArg);
  const meta = loadJson(fs.readFileSync(path.join(res, "meta.json"), "utf8"));
  const generator = str(get(meta, "model") || "n/a");
  const unknown = MISSING_MODEL.has(generator.trim().toLowerCase());
  if (unknown && !allow_same_model) throw new Error("The model that generated the app is not recorded (meta.json): it cannot be checked that the judge is a different " +
    "model. Evaluate with --model, or pass --allow-same-model to take that risk (it is recorded in judge.json).");
  const same = !unknown && sameModel(generator, model);
  if (same && !allow_same_model) throw new Error(`The judge (${model}) is the same model that generated the app (${generator}): there is a bias in favor of its own style. ` +
    "Use another model, or --allow-same-model (it is recorded in judge.json).");
  const m = loadJson(fs.readFileSync(path.join(res, "metrics.json"), "utf8"));
  const manualDone = {};
  const mf = path.join(res, "manual_review.json");
  if (fs.existsSync(mf))
    for (const [pid, crits] of Object.entries(loadJson(fs.readFileSync(mf, "utf8"))))
      if (isDict(crits)) manualDone[pid] = Object.fromEntries(Object.entries(crits).filter(([, v]) => (isDict(v) ? get(v, "ok") : v) !== null));
  const argv = judgeCommand(cmd, model);
  const pend = pending(res, manualDone);
  if (!pend.length) return ["No judgeable pending criteria."];
  const decisions = {}, hash = createHash("sha256"), groups = new Map();
  for (const [p, cid] of pend) { if (!groups.has(p.id)) groups.set(p.id, [p, []]); groups.get(p.id)[1].push(cid); }
  for (const [pid, [p, cids]] of groups) {
    const prompt = buildPrompt(pid, cids, Object.fromEntries(cids.map((c) => [c, p.criteria[c].desc])), evidence(pid, cids, res, m, p));
    hash.update(prompt, "utf8");
    const ballots = [];
    for (let i = 0; i < votes; i++) {
      let rc, so;
      try { [rc, so] = query(argv, prompt, timeout); } catch (e) { throw new Error(`Could not run the judge (${argv.join(" ")}): ${e.message}`); }
      ballots.push(rc === 0 ? parse(so, cids) : null);
    }
    for (const cid of cids) {
      const vs = ballots.map((b) => (b ? b[cid] : null));
      const d = majority(vs);
      log.push(`  ${pid}.${cid}: ` + (d ? `${d.ok ? "true" : "false"} (${repr(d.votes)}, confidence ${str(d.confidence)})` : `no decision (votes ${repr(vs.map((v) => (v ? v.ok : null)))})`));
      if (d) (decisions[pid] ??= {})[cid] = d;
    }
  }
  const decided = Object.entries(decisions).flatMap(([pid, cs]) => Object.keys(cs).map((cid) => [pid, cid]));
  new PyRandom(createHash("sha256").update(path.basename(res) + model, "utf8").digest("hex")).shuffle(decided);
  const nAudit = decided.length ? Math.max(1, pyRound(decided.length * audit)) : 0;
  const forced = decided.filter(([pid, cid]) => !decisions[pid][cid].unanimous || decisions[pid][cid].confidence === "low");  // inconclusive: always audited
  const sample = [...new Map([...forced, ...decided.slice(0, nAudit)].map((x) => [x.join("."), x])).values()];
  const output = { meta: { judge_model: model, generator_model: generator, same_model: same, generator_unknown: unknown, command: cmd, votes,
    date: nowIso(), prompts_sha256: hash.digest("hex") }, decisions, audit: sample.map(([pid, cid]) => `${pid}.${cid}`) };
  fs.writeFileSync(path.join(res, "judge.json"), dumps(output, 1), "utf8");
  log.push(`Judge ${model}: ${decided.length} decision(s), ${pend.length - decided.length} undecided. To audit: ${output.audit.join(", ") || "—"} → ${path.join(res, "judge.json")}`);
  return log;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2), o = {};
  let res = null;
  for (let i = 0; i < args.length; i++) {
    const x = args[i];
    if (!x.startsWith("--")) { res = x; continue; }
    const k = x.slice(2).replaceAll("-", "_");
    if (k === "allow_same_model") o[k] = true;
    else o[k] = ["votes", "timeout"].includes(k) ? Number.parseInt(args[++i], 10) : k === "audit" ? Number.parseFloat(args[++i]) : args[++i];
  }
  if (!res || !o.model) { console.error("usage: node js/judge.mjs results/<run> --model <judge model> [--votes 3] [--cmd …] [--audit 0.2]"); process.exit(2); }
  try { for (const l of runJudge(res, o)) console.log(l); } catch (e) { console.error(e.message); process.exit(1); }
}
