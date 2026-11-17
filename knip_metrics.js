#!/usr/bin/env node
/**
 * knip_metrics.js — Runs Knip on one package directory of the app WITHOUT executing any of the app's files, and dumps the unused
 * files, dependencies and exports as JSON.
 *
 * usage: node knip_metrics.js <request.json> <out.json>
 *   request.json: {"dir": <package dir>, "root": <app dir>, "nested": [<package dirs inside dir, relative to it>],
 *                  "entry": [<extra entry globs>], "config_file": <where to write the Knip configuration>}
 *
 * Knip normally imports the JS/TS configuration files of the tools it recognizes (vite.config.js, jest.config.js…), which would run
 * code written by the model under evaluation. Two layers prevent it:
 *  1. For every plugin the package enables, its JS/TS configuration patterns are moved from `config` (loaded) to `entry` (parsed
 *     statically, like any source file); JSON, YAML, TOML, rc files and package.json are still read as data. The plugin's own entry
 *     patterns are kept.
 *  2. Knip runs under no_exec_guard.mjs, which makes any attempt to execute a file of the app fail (Knip then logs a load error and
 *     keeps its static analysis). The errors are reported in `config_load_errors`.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { pathToFileURL } = require("url");

const HERE = __dirname;
const EXTS = "js,mjs,cjs,jsx,ts,tsx,mts,cts";
const UNSAFE = /\.(c|m)?[jt]sx?$/; // configuration files that Knip would execute

/** "a.{js,ts}" → ["a.js", "a.ts"] (nested groups included). */
function expand(p) {
  const m = p.match(/\{([^{}]*)\}/);
  if (!m) return [p];
  return m[1].split(",").flatMap((alt) => expand(p.slice(0, m.index) + alt + p.slice(m.index + m[0].length)));
}

async function pluginOverrides(dir, manifest) {
  const { Plugins } = await import(pathToFileURL(path.join(HERE, "node_modules/knip/dist/plugins/index.js")).href);
  const deps = new Set(["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]
    .flatMap((k) => Object.keys(manifest[k] || {})));
  const out = {};
  for (const [name, p] of Object.entries(Plugins)) {
    let enabled = false;
    try {
      enabled = typeof p.isEnabled === "function" && !!(await p.isEnabled({ cwd: dir, manifest, dependencies: deps, config: {} }));
    } catch {
      enabled = false;
    }
    if (!enabled || !Array.isArray(p.config)) continue;
    const all = p.config.flatMap(expand);
    const unsafe = all.filter((x) => UNSAFE.test(x));
    if (!unsafe.length) continue;
    // an override enables the plugin, which is why only the plugins the package already enables are touched
    out[name] = { config: all.filter((x) => !UNSAFE.test(x)), entry: [...(p.entry || []), ...unsafe] };
  }
  return out;
}

async function main() {
  const [reqFile, outFile] = process.argv.slice(2);
  const req = JSON.parse(fs.readFileSync(reqFile, "utf8"));
  const dir = path.resolve(req.dir);
  const manifest = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  const plugins = await pluginOverrides(dir, manifest);
  const outside = (req.nested || []).map((n) => `!${n}/**`); // nested packages are analyzed on their own
  const config = {
    // Knip's default entries, plus the extra entry globs of rubric.json (dead_code)
    entry: [`{index,cli,main}.{${EXTS}}`, `src/{index,cli,main}.{${EXTS}}`, ...(req.entry || []), ...outside],
    project: [`**/*.{${EXTS}}`, ...outside],
    ...plugins,
  };
  fs.writeFileSync(req.config_file, JSON.stringify(config, null, 1));
  const knip = path.join(HERE, "node_modules/knip/bin/knip.js");
  const r = spawnSync(process.execPath,
    ["--import", pathToFileURL(path.join(HERE, "no_exec_guard.mjs")).href, knip, "-c", req.config_file, "--directory", dir,
      "--reporter", "json", "--no-exit-code", "--no-progress", "--no-config-hints"],
    { encoding: "utf8", maxBuffer: 256 * 1024 * 1024, env: { ...process.env, NO_EXEC_ROOT: path.resolve(req.root) }, timeout: 600000 });
  let report;
  try {
    report = JSON.parse(r.stdout);
  } catch {
    fs.writeFileSync(outFile, JSON.stringify({ ok: false, error: ((r.stderr || "") + (r.stdout || "") || String(r.error || `exit ${r.status}`)).slice(-2000) }));
    return;
  }
  const res = { ok: true, version: require(path.join(HERE, "node_modules/knip/package.json")).version, overridden_plugins: Object.keys(plugins),
    files: [], dependencies: [], devDependencies: [], unlisted: [], unresolved: [], binaries: [], exports: [],
    config_load_errors: (r.stderr || "").split(/\r?\n/).filter((l) => /^ERROR: Error loading /.test(l)).map((l) => l.slice(7)) };
  for (const i of report.issues || []) {
    for (const f of i.files || []) res.files.push(f.name);
    for (const k of ["dependencies", "devDependencies", "binaries"]) for (const d of i[k] || []) res[k].push(d.name);
    for (const k of ["unlisted", "unresolved"]) for (const d of i[k] || []) res[k].push({ file: i.file, name: d.name });
    for (const k of ["exports", "types"]) for (const e of i[k] || []) res.exports.push({ file: i.file, name: e.name, line: e.line, kind: k });
  }
  fs.writeFileSync(outFile, JSON.stringify(res));
}

main().catch((e) => {
  fs.writeFileSync(process.argv[3], JSON.stringify({ ok: false, error: String((e && e.stack) || e).slice(-2000) }));
  process.exit(1);
});
