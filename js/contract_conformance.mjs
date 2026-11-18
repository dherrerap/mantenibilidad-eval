// contract_conformance.mjs — Runtime conformance of an API to its OpenAPI contract, measured with Prism as a validating proxy while the
// acceptance suite runs. Port of contract_conformance.py (see it for the classification of the calls).
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { F, get, pyRound, pySlice, sorted, str } from "./lib/py.mjs";
import { HERE } from "./evaluator/common.mjs";
import { freePort } from "./pg_temp.mjs";

const require = createRequire(import.meta.url);
const PRISM = path.join(HERE, "node_modules", "@stoplight", "prism-cli", "dist", "index.js");
export const RESULT_FILE = "contract_conformance.json";
export const available = () => fs.existsSync(PRISM);

/** Copy of the contract with its base path (servers[].url or basePath) applied to every path; returns the base path. */
export function flatten(contract, dst) {
  let d;
  try {
    const t = fs.readFileSync(contract, "utf8");
    d = String(contract).endsWith(".json") ? JSON.parse(t) : require(path.join(HERE, "node_modules", "yaml")).parse(t);
  } catch (e) { throw new Error("could not read the contract: " + String(e.message).slice(-300)); }
  const bases = (d.servers || []).map((s) => { try { return new URL(String(s.url || ""), "http://h").pathname.replace(/\/+$/, ""); } catch { return ""; } });
  if (d.basePath) bases.push(String(d.basePath).replace(/\/+$/, ""));
  const base = bases.find((b) => b) || "";
  const paths = {};
  for (const [p, v] of Object.entries(d.paths || {})) paths[base + p] = v;
  d.paths = paths; delete d.servers; delete d.basePath;
  fs.writeFileSync(dst, JSON.stringify(d));
  return base;
}

const connects = (port) => new Promise((resolve) => {
  const s = net.connect(port, "127.0.0.1");
  s.once("connect", () => { s.destroy(); resolve(true); });
  s.once("error", () => { s.destroy(); resolve(false); });
});

/** Prism proxy in front of `upstream`, validating against `contract`: `await p.open()` gives the proxy URL, `p.close()` stops it. */
export class Proxy {
  constructor(contract, upstream, wait = 60) { Object.assign(this, { contract, upstream, wait, proc: null, tmp: null, base_path: "" }); }

  async open() {
    this.tmp = fs.mkdtempSync(path.join(os.tmpdir(), "eval-prism-"));
    const flat = path.join(this.tmp, "contract.json");
    this.base_path = flatten(this.contract, flat);
    const port = freePort();
    this.proc = spawn(process.execPath, [PRISM, "proxy", flat, this.upstream, "-p", String(port), "--errors=false", "-v", "warn"], { cwd: HERE, stdio: "ignore", windowsHide: true });
    const end = Date.now() + this.wait * 1000;
    while (Date.now() < end) {
      if (this.proc.exitCode !== null) throw new Error(`Prism exited with code ${this.proc.exitCode}`);
      if (await connects(port)) return `http://127.0.0.1:${port}`;
      await new Promise((r) => setTimeout(r, 300));
    }
    throw new Error(`Prism did not open port ${port} within ${this.wait} s`);
  }

  close() {
    if (this.proc && this.proc.exitCode === null) this.proc.kill();
    if (this.tmp) fs.rmSync(this.tmp, { recursive: true, force: true });
  }
}

/** Kinds of the violations of one call: route, status, response, request. */
export function classify(violations) {
  const kinds = new Set();
  for (const v of violations || []) {
    const where = (get(v, "location") || [""])[0], msg = get(v, "message", "") ?? "";
    if (where === "request" && msg.toLowerCase().includes("route not found")) kinds.add("route");
    else if (where === "response" && msg.startsWith("Unable to match the returned status code")) kinds.add("status");
    else if (where === "response") kinds.add("response");
    else if (where === "request") kinds.add("request");
  }
  return kinds;
}

/** calls: [{method, path, status, violations}] recorded by the acceptance suite → the conformance result. */
export function summarize(calls, contract, basePath = "") {
  const rows = calls.map((c) => {
    const k = classify(get(c, "violations"));
    return { ...c, kinds: sorted([...k]), conforms: !["route", "status", "response"].some((x) => k.has(x)) };
  });
  const examples = (kind) => {
    const seen = [];
    for (const r of rows) {
      if (!r.kinds.includes(kind)) continue;
      const side = kind === "route" || kind === "request" ? "request" : "response";
      const msg = (r.violations.find((v) => (get(v, "location") || [""])[0] === side) || {}).message ?? "";
      const key = pySlice(`${r.method} ${r.path} → ${r.status}: ${msg}`, 0, 200);
      if (!seen.includes(key)) seen.push(key);
    }
    return seen;
  };
  const n = rows.length, ok = rows.filter((r) => r.conforms).length;
  return { ok: true, tool: "Prism (@stoplight/prism-cli proxy)", contract: str(contract), base_path: basePath, calls: n, conforming: ok,
    conformance_pct: n ? F(pyRound((100.0 * ok) / n, 1)) : null, undocumented_routes: examples("route"), undocumented_status: examples("status"),
    invalid_responses: examples("response"), invalid_requests: rows.filter((r) => r.kinds.includes("request")).length, detail: rows };
}

export const withoutPrism = (reason, contract = null) => ({ ok: false, tool: "Prism (@stoplight/prism-cli proxy)", contract: contract === null ? null : str(contract), error: reason });
