#!/usr/bin/env python3
"""
contract_conformance.py — Runtime conformance of an API to its OpenAPI contract, measured with Prism (@stoplight/prism-cli) as a
validating proxy while the acceptance suite runs (acceptance_check.py --app).

Static checks (contracts.C1–C4) only tell whether a contract exists and whether its paths match the routes in the code; this one tells
whether the responses the running API actually returns are the ones the contract documents. Informational: it changes no level.

Prism runs in proxy mode with --errors=false: it forwards every request to the backend unchanged and reports in the `sl-violations`
header of each response what does not match the contract. Each call of the suite is classified as:
  undocumented route    the contract has no operation for that method and path
  undocumented status   the operation exists but does not declare the status code returned
  invalid response      the response body or headers do not match the declared schema
  invalid request       the request does not match it: the suite sends invalid input ON PURPOSE to check the 400s, so this is not
                        a defect of the app and does not lower the conformance
A call conforms when its route is documented and its response has no violation. Conformance = conforming calls / calls.

Prism ignores a relative server URL (`servers: [{url: /api}]`), so it is given a copy of the contract with that prefix applied to every
path. Standard library only; Prism and the `yaml` package come from this folder's node_modules.
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRISM = HERE / "node_modules" / "@stoplight" / "prism-cli" / "dist" / "index.js"
RESULT_FILE = "contract_conformance.json"

FLATTEN_JS = r"""
const Y = require('yaml'), fs = require('fs');
const [src, dst] = process.argv.slice(1);
const t = fs.readFileSync(src, 'utf8');
const d = src.endsWith('.json') ? JSON.parse(t) : Y.parse(t);
const bases = (d.servers || []).map((s) => { try { return new URL(String(s.url || ''), 'http://h').pathname.replace(/\/+$/, ''); } catch (e) { return ''; } });
if (d.basePath) bases.push(String(d.basePath).replace(/\/+$/, ''));
const base = bases.find((b) => b) || '';
const paths = {};
for (const [p, v] of Object.entries(d.paths || {})) paths[base + p] = v;
d.paths = paths; delete d.servers; delete d.basePath;
fs.writeFileSync(dst, JSON.stringify(d));
console.log(JSON.stringify({ base }));
"""


def available():
    return PRISM.exists()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def flatten(contract, dst):
    """Copy of the contract with its base path (servers[].url or basePath) applied to every path; returns the base path."""
    p = subprocess.run(["node", "-e", FLATTEN_JS, str(contract), str(dst)], cwd=HERE, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("could not read the contract: " + (p.stderr or p.stdout).strip()[-300:])
    return json.loads(p.stdout or "{}").get("base", "")


class Proxy:
    """Prism proxy in front of `upstream`, validating against `contract`: `with Proxy(...) as base:` gives the proxy URL."""

    def __init__(self, contract, upstream, log=None, wait=60):
        self.contract, self.upstream, self.log, self.wait = Path(contract), upstream, log, wait
        self.proc = self.tmp = None

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        flat = Path(self.tmp.name) / "contract.json"
        self.base_path = flatten(self.contract, flat)
        port = free_port()
        self.proc = subprocess.Popen(["node", str(PRISM), "proxy", str(flat), self.upstream, "-p", str(port), "--errors=false", "-v", "warn"],
                                     cwd=HERE, stdout=self.log or subprocess.DEVNULL, stderr=subprocess.STDOUT)
        end = time.time() + self.wait
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Prism exited with code {self.proc.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return f"http://127.0.0.1:{port}"
            except OSError:
                time.sleep(0.3)
        raise RuntimeError(f"Prism did not open port {port} within {self.wait} s")

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.tmp:
            self.tmp.cleanup()


def classify(violations):
    """Kinds of the violations of one call: route, status, response, request (see the module docstring)."""
    kinds = set()
    for v in violations or []:
        where = (v.get("location") or [""])[0]; msg = v.get("message", "")
        if where == "request" and "route not found" in msg.lower():
            kinds.add("route")
        elif where == "response" and msg.startswith("Unable to match the returned status code"):
            kinds.add("status")
        elif where == "response":
            kinds.add("response")
        elif where == "request":
            kinds.add("request")
    return kinds


def summarize(calls, contract, base_path=""):
    """calls: [{"method", "path", "status", "violations"}] recorded by acceptance_check.call → the conformance result."""
    rows = []
    for c in calls:
        k = classify(c.get("violations"))
        rows.append({**c, "kinds": sorted(k), "conforms": not (k & {"route", "status", "response"})})
    def examples(kind):
        seen = []
        for r in rows:
            if kind in r["kinds"]:
                msg = next((v.get("message") for v in r["violations"] if (v.get("location") or [""])[0] == ("request" if kind in ("route", "request") else "response")), "")
                key = f"{r['method']} {r['path']} → {r['status']}: {msg}"[:200]
                if key not in seen:
                    seen.append(key)
        return seen
    n = len(rows); ok = sum(r["conforms"] for r in rows)
    return {"ok": True, "tool": "Prism (@stoplight/prism-cli proxy)", "contract": str(contract), "base_path": base_path, "calls": n,
            "conforming": ok, "conformance_pct": round(100.0 * ok / n, 1) if n else None,
            "undocumented_routes": examples("route"), "undocumented_status": examples("status"), "invalid_responses": examples("response"),
            "invalid_requests": sum("request" in r["kinds"] for r in rows), "detail": rows}


def without_prism(reason, contract=None):
    return {"ok": False, "tool": "Prism (@stoplight/prism-cli proxy)", "contract": None if contract is None else str(contract), "error": reason}


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
