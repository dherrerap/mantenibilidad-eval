// packages.mjs — package.json manifests, the version each direct dependency installs, its latest version, libyear and deprecation
// (npm registry), known vulnerabilities (OSV), supported runtimes (endoflife.date) and PostgreSQL images. Port of
// evaluator/collectors/{packages,osv}.py. Everything time-dependent is computed as of `as_of`.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { readText, F, get, loadJson, or, pyRound, sorted, str, truthy } from "../../lib/py.mjs";
import { RUBRIC } from "../common.mjs";
import { coerceVersion } from "../helpers.mjs";
import { net, rel, sortPaths, walk } from "../sys.mjs";

export const findPackages = (app) => sortPaths([...new Set([...walk(app)].filter((p) => path.basename(p) === "package.json").map((p) => path.dirname(p)))]);

function readPkg(d) {
  try { return loadJson(fs.readFileSync(path.join(d, "package.json"), "utf8")); } catch { return {}; }
}

const endOf = (asOf) => `${asOf}T23:59:59Z`;
const semverKey = (v) => { const m = /^(\d+)\.(\d+)\.(\d+)$/.exec(str(or(v, ""))); return m ? m.slice(1).map(Number) : null; };
const today = () => new Date().toISOString().slice(0, 10);

/** Version a lockfile installs for a direct dependency (lockfileVersion 2/3 `packages`, or 1 `dependencies`). */
export const directVersion = (lock, name) => or(get(or(get(or(get(lock, "packages"), {}), `node_modules/${name}`), {}), "version"),
  get(or(get(or(get(lock, "dependencies"), {}), name), {}), "version"));

/** Every package a lockfile installs: [{name, version, dev}]. */
export function lockPackages(lock) {
  const out = [];
  for (const [key, v] of Object.entries(or(get(lock, "packages"), {})))
    if (key && truthy(get(v, "version")) && !truthy(get(v, "link")) && key.includes("node_modules/"))
      out.push({ name: or(get(v, "name"), key.split("node_modules/").at(-1)), version: v.version, dev: truthy(get(v, "dev")) });
  if (!truthy(get(lock, "packages"))) {  // lockfileVersion 1
    const walkV1 = (deps) => {
      for (const [name, v] of Object.entries(deps || {})) {
        if (truthy(get(v, "version"))) out.push({ name, version: v.version, dev: truthy(get(v, "dev")) });
        walkV1(get(v, "dependencies"));
      }
    };
    walkV1(get(lock, "dependencies"));
  }
  return out;
}

function run(cmd, args, cwd, timeout) {  // async version of sys.sh for the parallel registry queries
  const npmCli = path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js");
  if (cmd === "npm" && fs.existsSync(npmCli)) [cmd, args] = [process.execPath, [npmCli, ...args]];
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { cwd, windowsHide: true, shell: process.platform === "win32" && cmd !== process.execPath });
    let so = "", se = "";
    const t = setTimeout(() => { p.kill(); resolve([124, so, "timeout"]); }, timeout * 1000);
    p.stdout.on("data", (b) => { so += b; });
    p.stderr.on("data", (b) => { se += b; });
    p.on("error", (e) => { clearTimeout(t); resolve([127, "", String(e.message)]); });
    p.on("close", (code) => { clearTimeout(t); resolve([code ?? 1, so, se]); });
  });
}

/** The npm registry as the collectors use it. The differential test replaces both functions with what the Python run received. */
export const registry = {
  async npmJson(args) {
    const [rc, so] = await run("npm", ["view", ...args, "--json"], undefined, 60);
    if (rc !== 0 || !so.trim()) return null;
    try { return loadJson(so); } catch { return null; }
  },
  /** [lockfile, source]: the app's own package-lock.json when it pins every direct dependency, otherwise what npm resolves with the
   *  registry as it was at `asOf` (--before, scripts not run); [null, null] without a network. */
  async resolveLock(d, asOf) {
    const pkg = readPkg(d);
    const names = new Set([...Object.keys(get(pkg, "dependencies", {})), ...Object.keys(get(pkg, "devDependencies", {}))]);
    const own = path.join(d, "package-lock.json");
    if (fs.existsSync(own)) {
      try {
        const lock = loadJson(fs.readFileSync(own, "utf8"));
        if ([...names].every((n) => directVersion(lock, n))) return [lock, "lockfile"];
      } catch { /* resolve it */ }
    }
    const t = fs.mkdtempSync(path.join(os.tmpdir(), "eval-lock-"));
    try {
      fs.copyFileSync(path.join(d, "package.json"), path.join(t, "package.json"));
      await run("npm", ["install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund", `--before=${endOf(asOf)}`], t, 300);
      try { return [loadJson(fs.readFileSync(path.join(t, "package-lock.json"), "utf8")), `npm as of ${asOf}`]; } catch { return [null, null]; }
    } finally { fs.rmSync(t, { recursive: true, force: true }); }
  },
};

/** A direct dependency with its registry data as of `asOf`: latest stable version, release dates, libyear and deprecation. */
async function dependency(item, asOf) {
  const end = endOf(asOf);
  const times = or(await registry.npmJson([item.pkg, "time"]), {});
  const stable = Object.entries(times).filter(([v, t]) => semverKey(v) && str(t) <= end).map(([v, t]) => [semverKey(v), v, t]);
  const latest = stable.length ? sorted(stable).at(-1)[1] : null;
  const used = item.resolved;
  Object.assign(item, { latest, latest_date: get(times, latest), resolved_date: get(times, used), libyear: null, deprecated: null });
  item.after_as_of = Boolean(item.resolved_date && item.resolved_date > end);  // a version published after as_of
  if (item.resolved_date && item.latest_date && !item.after_as_of) {
    const days = Math.floor((Date.parse(item.latest_date) - Date.parse(item.resolved_date)) / 86400000);  // timedelta.days floors
    item.libyear = F(pyRound(Math.max(days, 0) / 365.25, 2));
  }
  if (truthy(used)) item.deprecated = or(await registry.npmJson([`${item.pkg}@${used}`, "deprecated"]), null);
  return item;
}

async function mapLimit(xs, n, fn) {
  const out = new Array(xs.length);
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, xs.length) }, async () => { while (i < xs.length) { const k = i++; out[k] = await fn(xs[k]); } }));
  return out;
}

export async function analyzePackages(app, offline, includeDevUnused, asOf = null) {
  asOf = asOf || today();
  const res = { packages: [], direct: 0, unused_dev_incl: includeDevUnused, as_of: asOf, npm: { ok: false, items: [] }, vulnerabilities: { ok: false, source: "OSV", as_of: asOf } };
  let items = [];
  const installed = [];
  for (const d of findPackages(app)) {
    const pkg = readPkg(d);
    const deps = { ...get(pkg, "dependencies", {}) }, dev = { ...get(pkg, "devDependencies", {}) };
    const rd = rel(d, app) || ".";
    res.packages.push({ dir: rd, name: get(pkg, "name"), dependencies: deps, devDependencies: dev, scripts: get(pkg, "scripts", {}), engines: get(pkg, "engines", {}), main: get(pkg, "main") });
    res.direct += Object.keys(deps).length + (truthy(includeDevUnused) ? Object.keys(dev).length : 0);
    if (offline) continue;
    const [lock, source] = await registry.resolveLock(d, asOf);
    res.packages.at(-1).lock_source = source;
    if (lock) installed.push(...lockPackages(lock));
    for (const [group, specs] of [["dependencies", deps], ["devDependencies", dev]])
      for (const [name, spec] of Object.entries(specs)) {
        const v = lock ? directVersion(lock, name) : null;
        items.push({ pkg: name, spec, dir: rd, dev: group === "devDependencies", resolved: or(v, coerceVersion(spec)), resolved_source: truthy(v) ? source : "range lower bound" });
      }
  }
  if (offline || !items.length) return res;
  items = await mapLimit(items, 8, (i) => dependency(i, asOf));
  res.npm = { ok: items.some((i) => truthy(i.latest)), items };
  if (installed.length) res.vulnerabilities = await vulnerabilities(installed, asOf);
  return res;
}

/** Supported major versions per endoflife.date as of `asOf` (released by then, not yet at end of life); {} offline. */
export async function fetchEol(offline, asOf = null) {
  if (offline) return {};
  const day = asOf || today(), res = {};
  for (const [key, product] of Object.entries(RUBRIC.supported_runtimes.eol_products)) {
    try {
      const cycles = await net.getJson(`https://endoflife.date/api/${product}.json`, 15);
      res[key] = sorted([...new Set(cycles.filter((c) => (c.eol === false || (typeof c.eol === "string" && c.eol > day)) && str(or(get(c, "releaseDate"), "")) <= day)
        .map((c) => Number.parseInt(String(c.cycle).split(".")[0], 10)))]);
    } catch { continue; }
  }
  return res;
}

const COMPOSE_NAMES = new Set(["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]);
const PG_IMAGE = /(^|\/)(postgres|postgis\/postgis|bitnami\/postgresql|timescale\/timescaledb)(:|@|$)/i;

/** PostgreSQL images of the docker-compose files and their major version: [{file, image, major}]. */
export function postgresImages(app) {
  const out = [];
  for (const p of walk(app)) {
    if (!COMPOSE_NAMES.has(path.basename(p))) continue;
    for (const m of readText(p).matchAll(/^\s*image:\s*["']?([^\s"'#]+)/gm)) {
      const img = m[1];
      if (!PG_IMAGE.test(img)) continue;
      const tag = img.split("/").at(-1).includes(":") ? img.slice(img.indexOf(":") + 1) : "";
      const mm = /^(\d+)/.exec(tag);
      out.push({ file: rel(p, app), image: img, major: mm ? Number.parseInt(mm[1], 10) : null });
    }
  }
  return out;
}

// ───────────────────────── OSV ─────────────────────────
const API = "https://api.osv.dev/v1", BATCH = 500;

async function queryIds(pkgs) {
  const out = new Map();
  let pending = pkgs.map(([n, v]) => ({ package: { name: n, ecosystem: "npm" }, version: v }));
  while (pending.length) {
    const nxt = [];
    for (let i = 0; i < pending.length; i += BATCH) {
      const chunk = pending.slice(i, i + BATCH);
      const res = (await net.postJson(`${API}/querybatch`, { queries: chunk })).results;
      chunk.forEach((q, k) => {
        const r = res[k], key = JSON.stringify([q.package.name, q.version]);
        if (!out.has(key)) out.set(key, []);
        out.get(key).push(...get(r, "vulns", []).map((v) => v.id));
        if (truthy(get(r, "next_page_token"))) nxt.push({ ...q, page_token: r.next_page_token });
      });
    }
    pending = nxt;
  }
  return out;
}

function severity(rec) {
  const s = get(or(get(rec, "database_specific"), {}), "severity");
  if (truthy(s)) return str(s).toUpperCase();
  return rec.id.startsWith("MAL-") ? "CRITICAL" : null;
}

const knownSince = (rec) => sorted([or(get(rec, "published"), ""), or(get(or(get(rec, "database_specific"), {}), "github_reviewed_at"), "")]).at(-1);

/** The (package, advisory) pairs in force at `asOf` for every installed package. */
export async function vulnerabilities(pkgs, asOf) {
  const end = `${asOf}T23:59:59Z`;
  let ids, recs;
  try {
    ids = await queryIds(sorted([...new Map(pkgs.map((p) => [JSON.stringify([p.name, p.version]), [p.name, p.version]])).values()]));
    const uniq = sorted([...new Set([...ids.values()].flat())]);
    const got = await mapLimit(uniq, 8, (i) => net.getJson(`${API}/vulns/${i}`));
    recs = Object.fromEntries(uniq.map((i, k) => [i, got[k]]));
  } catch (e) {
    return { ok: false, source: "OSV", as_of: asOf, error: String(e.message || e).slice(0, 300) };
  }
  const dev = new Map();
  for (const p of pkgs) {  // production if any lockfile installs it outside devDependencies
    const k = JSON.stringify([p.name, p.version]);
    dev.set(k, (dev.has(k) ? dev.get(k) : true) && truthy(get(p, "dev")));
  }
  const items = [];
  let later = 0;
  for (const [key, vs] of ids) {
    const [name, version] = JSON.parse(key);
    for (const i of sorted([...new Set(vs)])) {
      const rec = recs[i];
      if (knownSince(rec) > end) { later += 1; continue; }  // not yet in the database at as_of
      if (truthy(get(rec, "withdrawn")) && rec.withdrawn <= end) continue;
      items.push({ pkg: name, version, id: i, aliases: get(rec, "aliases", []), severity: severity(rec), published: get(rec, "published"),
        dev: dev.has(key) ? dev.get(key) : false, summary: or(get(rec, "summary"), "").slice(0, 120) });
    }
  }
  const count = (s) => items.filter((x) => x.severity === s).length;
  return { ok: true, source: "OSV", as_of: asOf, queried: ids.size, items, high: count("HIGH"), critical: count("CRITICAL"), unknown_severity: count(null), published_after_as_of: later };
}
