// sys.mjs — What the collectors need from the system: walking an app like os.walk, relative paths, running a command like
// evaluator/common.py `sh`, glob_to_re, and the network (replaceable, so that the differential test replays the responses the
// Python run received).
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { sorted } from "../lib/py.mjs";

export const SKIP_DIRS = new Set(["node_modules", "dist", "build", "coverage", ".git", ".next", "out"]);
export const WIN = process.platform === "win32";

/** os.walk(app) top-down, files of a folder (in the order the OS lists them) before its subfolders; skipped folders as in Python.
 *  A symbolic link to a folder is listed but not followed, as os.walk does by default. */
export function* walk(app) {
  let entries;
  try { entries = fs.readdirSync(app, { withFileTypes: true }); } catch { return; }
  const dirs = [];
  for (const e of entries) {
    let isDir = e.isDirectory();
    if (e.isSymbolicLink()) {
      try { isDir = fs.statSync(path.join(app, e.name)).isDirectory(); } catch { isDir = false; }
      if (isDir) continue;  // listed in dirs by os.walk, but not walked into
    }
    if (isDir) { if (!SKIP_DIRS.has(e.name) && !e.name.startsWith(".git")) dirs.push(e.name); }
    else yield path.join(app, e.name);
  }
  for (const d of dirs) yield* walk(path.join(app, d));
}

const real = (p) => { try { return fs.realpathSync.native(p); } catch { return path.resolve(p); } };

/** Path of `p` relative to `app`, POSIX separators (both resolved, as Path.resolve()). */
export const rel = (p, app) => path.relative(real(app), real(p)).split(path.sep).join("/");

/** Python's ordering of Path objects: by parts, without regard to case on Windows. */
export const pathKey = (p) => path.resolve(p).split(path.sep).filter(Boolean).map((x) => (WIN ? x.toLowerCase() : x));
export const sortPaths = (ps) => sorted(ps, pathKey);

const NPM_CLI = path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js");

/** [returncode, stdout, stderr] of a command. "npm" runs through npm-cli.js with this node (no .cmd shim on Windows); a timeout
 *  gives 124 and a missing program 127, as in Python. */
export function sh(cmd, { cwd, timeout = 600, env } = {}) {
  let [exe, ...args] = cmd;
  if (exe === "npm" && fs.existsSync(NPM_CLI)) [exe, args] = [process.execPath, [NPM_CLI, ...args]];
  else if (exe === "node") exe = process.execPath;
  // NODE_TEST_CONTEXT (set when the evaluator itself runs under node --test) would make the app's own `node --test` report to the
  // parent runner instead of running its suite on its own, with no coverage
  env = { ...(env || process.env) };
  delete env.NODE_TEST_CONTEXT;
  const p = spawnSync(exe, args, { cwd, env, timeout: timeout * 1000, encoding: "utf8", maxBuffer: 512 * 1024 * 1024, windowsHide: true,
    shell: WIN && !/\.(exe|com)$/i.test(exe) && exe !== process.execPath });
  if (p.error && p.error.code === "ETIMEDOUT") return [124, "", "timeout"];
  if (p.error && p.error.code === "ENOENT") return [127, "", String(p.error.message)];
  if (p.signal === "SIGTERM" && p.status === null) return [124, "", "timeout"];
  return [p.status ?? 1, p.stdout ?? "", p.stderr ?? ""];
}

/** glob_to_re of evaluator/common.py: ** / for any folders, ** for anything, * within a segment. */
export function globToRe(g) {
  const esc = g.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp("^" + esc.replaceAll("\\*\\*/", "(?:.*/)?").replaceAll("\\*\\*", ".*").replaceAll("\\*", "[^/]*") + "$");
}

/** The network the collectors use (npm registry through the npm CLI, OSV, endoflife.date). The differential test replaces it. */
export const net = {
  async getJson(url, timeout = 60) {
    const r = await fetch(url, { signal: AbortSignal.timeout(timeout * 1000) });
    if (!r.ok) throw new Error(`HTTP Error ${r.status}: ${r.statusText}`);
    return r.json();
  },
  async postJson(url, body, timeout = 60) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(timeout * 1000) });
    if (!r.ok) throw new Error(`HTTP Error ${r.status}: ${r.statusText}`);
    return r.json();
  },
};
