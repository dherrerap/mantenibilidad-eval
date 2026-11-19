// pg_runtime.mjs — Helpers shared by pg_analysis.mjs (real-database analysis) and run_experiment.mjs (acceptance gate): free ports,
// readiness, killing a process tree, database names and URLs, masking of passwords, and Docker Compose. Port of pg_runtime.py.
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { get, isDict, loadJson, readText, sorted, splitlines, str } from "./lib/py.mjs";
import { freePort } from "./pg_temp.mjs";

export { freePort };
const WIN = process.platform === "win32";
const NPM_CLI = path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js");

/** argv that runs npm with this node (no .cmd shim on Windows). */
export const npmCmd = (...args) => (fs.existsSync(NPM_CLI) ? [process.execPath, NPM_CLI, ...args] : ["npm", ...args]);

export function waitForPort(port, seconds, host = "127.0.0.1") {
  const end = Date.now() + seconds * 1000;
  return new Promise((resolve) => {
    const tryOnce = () => {
      const s = net.connect(port, host);
      s.setTimeout(1000);
      s.once("connect", () => { s.destroy(); resolve(true); });
      const retry = () => { s.destroy(); if (Date.now() < end) setTimeout(tryOnce, 1000); else resolve(false); };
      s.once("error", retry);
      s.once("timeout", retry);
    };
    tryOnce();
  });
}

/** Starts `cmd` in its own process group (so the whole tree can be killed later), without a shell; output appended to `logFd`. */
export function startProcess(cmd, cwd, env, logFd) {
  return spawn(cmd[0], cmd.slice(1), { cwd, env, stdio: ["ignore", logFd, logFd], detached: !WIN, windowsHide: true });
}

/** Ends the process and its children (npm start spawns node). */
export function killTree(proc) {
  if (proc.exitCode !== null || proc.signalCode !== null) return;
  if (WIN) { spawnSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" }); return; }
  try { process.kill(-proc.pid, "SIGTERM"); } catch { return; }
  const t = Date.now();
  while (Date.now() - t < 10000) { try { process.kill(-proc.pid, 0); } catch { return; } spawnSync("sleep", ["0.2"]); }
  try { process.kill(-proc.pid, "SIGKILL"); } catch { /* gone */ }
}

const SECRET_NAME = /(SECRET|SIGNING_KEY|JWT_KEY)/i;

/** Random 64-character values for JWT_SECRET and every *SECRET* variable of the backend's .env.example the environment does not set. */
export function backendSecrets(backend, env = {}) {
  const names = new Set(["JWT_SECRET"]);
  const ex = path.join(backend, ".env.example");
  if (fs.existsSync(ex))
    for (const line of splitlines(readText(ex))) {
      const m = /^\s*(?:export\s+)?([A-Za-z_]\w*)\s*=/.exec(line);
      if (m && SECRET_NAME.test(m[1])) names.add(m[1]);
    }
  return Object.fromEntries(sorted([...names]).filter((n) => !env[n]).map((n) => [n, randomBytes(32).toString("hex")]));
}

/** `claude-n1-ecommerce-r1` -> `eval_claude_n1_ecommerce_r1`: the only kind of database name the evaluator creates or drops. */
export const evalDbName = (runId) => "eval_" + str(runId).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 50);
export const validEvalDb = (name) => /^eval_[a-z0-9_]{1,50}$/.test(str(name));

/** urllib.parse.quote(s, safe) for the parts of a connection string. */
const quote = (s, safe = "/") => [...Buffer.from(String(s), "utf8")].map((b) => {
  const c = String.fromCharCode(b);
  return /[A-Za-z0-9_.~-]/.test(c) || safe.includes(c) ? c : "%" + b.toString(16).toUpperCase().padStart(2, "0");
}).join("");

/** The connection string `baseUrl` pointed at database `db` (credentials and query string kept). */
export function dbUrl(baseUrl, db) {
  const m = /^([^:]+):\/\/([^/?#]*)([^?#]*)(\?[^#]*)?/.exec(baseUrl);
  return `${m[1]}://${m[2]}/${quote(db)}${m[4] || ""}`;
}

export const buildUrl = (user, password, host, port, db) => `postgresql://${quote(user, "")}:${quote(password, "")}@${host}:${port}/${quote(db)}`;

export function passwordOf(url) {
  const m = /^[^:]+:\/\/([^@/?#]*)@/.exec(url || "");
  if (!m || !m[1].includes(":")) return "";
  try { return decodeURIComponent(m[1].slice(m[1].indexOf(":") + 1)); } catch { return ""; }
}

/** The passwords of the given connection strings replaced by ***. */
export function mask(text, ...urls) {
  for (const u of urls) { const pw = u ? passwordOf(u) : ""; if (pw) text = text.split(pw).join("***"); }
  return text;
}

const R2_MARKERS = ["r2-additional-requirements.md", "PROMPT-R2.md"];
/** True when the additional requirements (phase r2) were handed to the agent in this project. */
export const hasR2 = (project) => R2_MARKERS.some((f) => { try { return fs.statSync(path.join(project, f)).isFile(); } catch { return false; } });
export const R2_GATE_SKIP = "the project already implements r2-additional-requirements.md and this domain has no r2 acceptance suite " +
  "(only ecommerce has one; the original suite does not apply, because r2 changes prices, shipping and roles); run the gate after phase initial";

// ───────────────────────── Docker Compose (acceptance gate) ─────────────────────────
const COMPOSE_NAMES = ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"];
const PG_IMAGE = /(^|\/)(postgres|postgis\/postgis|bitnami\/postgresql|timescale\/timescaledb)(:|@|$)/i;

export const findCompose = (project) => COMPOSE_NAMES.map((n) => path.join(project, n)).find((p) => { try { return fs.statSync(p).isFile(); } catch { return false; } }) ?? null;

function which(name) {
  const exts = WIN ? ["", ...(process.env.PATHEXT || ".EXE").split(";")] : [""];
  for (const d of (process.env.PATH || "").split(path.delimiter)) for (const e of exts) { const p = path.join(d, name + e); try { if (fs.statSync(p).isFile()) return p; } catch { /* next */ } }
  return null;
}

/** [compose command, null] when Docker and Docker Compose work, else [null, reason]. Nothing is started. */
export function dockerStatus() {
  if (!which("docker")) return [null, "Docker is not installed or not on PATH"];
  const ok = (args) => spawnSync("docker", args, { stdio: "ignore", timeout: 60000, shell: WIN }).status === 0;
  if (!ok(["info"])) return [null, "the Docker daemon is not running (docker info failed)"];
  if (ok(["compose", "version"])) return [["docker", "compose"], null];
  if (which("docker-compose")) return [["docker-compose"], null];
  return [null, "Docker Compose is not available (neither `docker compose` nor `docker-compose`)"];
}

/** Environment of a service of `docker compose config --format json` (a dict; older versions print a list of K=V). */
export function serviceEnv(service) {
  let env = get(service, "environment") || {};
  if (Array.isArray(env)) env = Object.fromEntries(env.filter((x) => x.includes("=")).map((x) => [x.slice(0, x.indexOf("=")), x.slice(x.indexOf("=") + 1)]));
  return Object.fromEntries(Object.entries(env).map(([k, v]) => [k, v === null || v === undefined ? "" : str(v)]));
}

export function pickPostgresService(config) {
  const services = get(config || {}, "services") || {};
  for (const [name, svc] of Object.entries(services)) if (PG_IMAGE.test(str(get(svc, "image") || ""))) return name;
  for (const [name, svc] of Object.entries(services)) if (["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRESQL_PASSWORD"].some((k) => k in serviceEnv(svc))) return name;
  return null;
}

/** [user, password, default database] the container is created with (the official image defaults when unset). */
export function pgCredentials(service) {
  const env = serviceEnv(service);
  const user = env.POSTGRES_USER || env.POSTGRESQL_USERNAME || "postgres";
  return [user, env.POSTGRES_PASSWORD || env.POSTGRESQL_PASSWORD || "", env.POSTGRES_DB || env.POSTGRESQL_DATABASE || user];
}

export function parsePublishedPort(text) {
  const m = [...str(text).matchAll(/:(\d+)\s*$/gm)];
  return m.length ? Number(m[0][1]) : null;
}

/** `docker compose -f <file> -p <project> …`; output appended to the log file. */
export class Compose {
  constructor(cmd, file, project, logPath) { Object.assign(this, { cmd: [...cmd], file, project, logPath }); }

  run(args, timeout = 300) {
    const full = [...this.cmd, "-f", this.file, "-p", this.project, ...args];
    const p = spawnSync(full[0], full.slice(1), { cwd: path.dirname(this.file), encoding: "utf8", timeout: timeout * 1000, shell: WIN, windowsHide: true });
    if (p.error && p.error.code === "ETIMEDOUT") return [124, "", "timeout"];
    if (p.error) return [127, "", String(p.error.message)];
    fs.appendFileSync(this.logPath, "$ " + args.join(" ") + "\n" + (p.stdout || "") + (p.stderr || "") + "\n", "utf8");
    return [p.status, p.stdout || "", p.stderr || ""];
  }

  config() {
    const [rc, out, err] = this.run(["config", "--format", "json"], 60);
    if (rc !== 0) throw new Error("docker compose config failed (Docker Compose v2 is required): " + (err || out).slice(-300));
    return loadJson(out);
  }

  up(service) { return this.run(["up", "-d", service], 900); }

  port(service, containerPort = 5432) {
    const [rc, out] = this.run(["port", service, String(containerPort)], 60);
    return rc === 0 ? parsePublishedPort(out) : null;
  }

  async waitReady(service, user, seconds = 90) {
    const end = Date.now() + seconds * 1000;
    while (Date.now() < end) {
      if (this.run(["exec", "-T", service, "pg_isready", "-h", "127.0.0.1", "-U", user, "-d", "postgres"], 30)[0] === 0) return true;
      await new Promise((r) => setTimeout(r, 2000));
    }
    return false;
  }

  createDatabase(service, user, db) {
    if (!validEvalDb(db)) throw new Error(db);
    return this.run(["exec", "-T", service, "psql", "-U", user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", `CREATE DATABASE "${db}"`], 60);
  }

  down() { return this.run(["down", "-v", "--remove-orphans"], 180); }
}

