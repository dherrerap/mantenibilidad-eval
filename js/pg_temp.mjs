#!/usr/bin/env node
// pg_temp.mjs — A disposable PostgreSQL server for --postgres when PG_ADMIN_URL is not set. Port of pg_temp.py: the cluster lives in
// a new temporary folder, listens only on 127.0.0.1 on a free port, its superuser `evaluator` has a random password (scram-sha-256)
// and the whole folder is deleted when it stops.
//   const srv = startServer(); …srv.url…; srv.stop();      (srv is null when there are no PostgreSQL binaries)
//   node js/pg_temp.mjs                                      (starts one, prints where from, and stops it: a check)
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { sorted } from "./lib/py.mjs";

const USER = "evaluator";
const EXE = process.platform === "win32" ? ".exe" : "";
const major = (p) => { const m = /(?:PostgreSQL[/\\]|postgresql[@/])(\d+)/.exec(p); return m ? Number(m[1]) : 0; };
const has = (d) => d && ["initdb", "pg_ctl"].every((b) => fs.existsSync(path.join(d, b + EXE)));

function globDirs(pattern) {  // the few patterns of find_bin: one "*" in a path segment
  const parts = pattern.split("/");
  let cur = [parts[0] === "" ? "/" : parts[0] + "/"];
  for (const seg of parts.slice(1)) {
    const next = [];
    for (const c of cur) {
      if (!seg.includes("*")) { const p = path.join(c, seg); if (fs.existsSync(p)) next.push(p); continue; }
      const re = new RegExp("^" + seg.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replaceAll("*", ".*") + "$");
      let es = [];
      try { es = fs.readdirSync(c); } catch { /* none */ }
      for (const e of es) if (re.test(e)) next.push(path.join(c, e));
    }
    cur = next;
  }
  return cur;
}

/** Folder with initdb and pg_ctl: PG_BIN, the PATH, then the usual install folders (highest major first); null if none. */
export function findBin() {
  const cands = [process.env.PG_BIN || ""];
  for (const d of (process.env.PATH || "").split(path.delimiter)) if (fs.existsSync(path.join(d, "pg_ctl" + EXE))) { cands.push(d); break; }
  const patterns = ["C:/Program Files/PostgreSQL/*/bin", "/usr/lib/postgresql/*/bin", "/usr/local/pgsql/bin", "/opt/homebrew/opt/postgresql@*/bin",
    "/usr/local/opt/postgresql@*/bin", "/Applications/Postgres.app/Contents/Versions/*/bin"];
  cands.push(...sorted(patterns.flatMap(globDirs), (p) => -major(p)));
  return cands.find(has) || null;
}

export function freePort() {
  // a synchronous probe: bind port 0 in a child process and read the port it got
  const p = spawnSync(process.execPath, ["-e", "const s=require('net').createServer();s.listen(0,'127.0.0.1',()=>{console.log(s.address().port);s.close()})"], { encoding: "utf8" });
  return Number(p.stdout.trim());
}

function run(cmd) {
  const p = spawnSync(cmd[0], cmd.slice(1), { encoding: "utf8", timeout: 120000, windowsHide: true });
  if (p.status !== 0) throw new Error(`${path.basename(cmd[0])} failed: ` + ((p.stderr || p.stdout || "").trim().split(/\r?\n/).at(-1) || "no output"));
  return p.stdout;
}

/** Starts a disposable server: {url, stop()}; null when there are no PostgreSQL binaries. */
export function startServer(binDir = null) {
  binDir = binDir || findBin();
  if (!binDir) return null;
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "eval-pg-"));
  const data = path.join(root, "data"), pw = randomBytes(18).toString("base64url"), pwfile = path.join(root, "pw");
  fs.writeFileSync(pwfile, pw, "utf8");
  const port = freePort();
  let started = false;
  const pgCtl = path.join(binDir, "pg_ctl" + EXE);
  const stop = () => {
    if (started) { try { run([pgCtl, "-D", data, "-m", "fast", "-w", "stop"]); } catch { /* already stopped */ } started = false; }
    fs.rmSync(root, { recursive: true, force: true });
  };
  try {
    run([path.join(binDir, "initdb" + EXE), "-D", data, "-U", USER, "--pwfile", pwfile, "-A", "scram-sha-256", "-E", "UTF8", "--locale=C", "--no-sync"]);
    fs.rmSync(pwfile);
    // no pipes: the server inherits pg_ctl's handles and keeps them open (Windows); its messages go to server.log
    const log = path.join(root, "server.log");
    const rc = spawnSync(pgCtl, ["-D", data, "-l", log, "-w", "-t", "60", "-o", `-p ${port} -c listen_addresses=127.0.0.1 -c fsync=off`, "start"],
      { stdio: "ignore", timeout: 120000, windowsHide: true }).status;
    started = true;  // stop is attempted even if the wait failed: the server may be up
    if (rc !== 0) {
      const tail = fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split(/\r?\n/) : [];
      throw new Error("pg_ctl start failed: " + (tail.at(-1) || `exit ${rc}`));
    }
  } catch (e) { stop(); throw e; }
  return { url: `postgres://${USER}:${pw}@127.0.0.1:${port}/postgres`, port, stop, bin: binDir };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const b = findBin();
  if (!b) { console.error("No PostgreSQL server binaries (initdb, pg_ctl) found: install PostgreSQL or set PG_BIN."); process.exit(1); }
  const s = startServer(b);
  s.stop();
  console.log(`PostgreSQL from ${b}: started on 127.0.0.1:${s.port} and stopped. --postgres can use it without PG_ADMIN_URL.`);
}

