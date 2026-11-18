// Differential test of the JavaScript collectors: for every app recorded by tests/golden/record_collect.py, collect() in JavaScript,
// with the network answers the Python run received, must give the same metrics.json: same keys in the same order, same values, and
// the same int/float kind. It runs every tool on every app, so it is slow and separate from `npm run test:js`:
//   npm run test:js:collect            (or: node --test tests/js/collect.slow.mjs)
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { isDict, loadJson, num } from "../../js/lib/py.mjs";
import { collect } from "../../js/evaluator/collectors/index.mjs";
import { registry } from "../../js/evaluator/collectors/packages.mjs";
import { net, rel } from "../../js/evaluator/sys.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const DIR = path.join(ROOT, "results", "_golden", "collect");
const IGNORED = new Set(["$.date"]);  // the time of the run

let SUBST = null;  // [JS app folder, Python app folder] when the app was copied for the run
const fixPath = (v) => (SUBST && typeof v === "string" ? v.split(SUBST[0]).join(SUBST[1]).split(SUBST[0].replaceAll("\\", "/")).join(SUBST[1].replaceAll("\\", "/")) : v);

function same(a, b, where = "$") {
  if (IGNORED.has(where) || /^\$\.tests_run\.packages\[\d+\]\.tail$/.test(where)) return;  // the runner's output carries durations
  if (Array.isArray(a) || Array.isArray(b)) {
    assert.ok(Array.isArray(a) && Array.isArray(b), `${where}: array vs ${JSON.stringify(a)?.slice(0, 120)}`);
    assert.equal(a.length, b.length, `${where}: length ${a.length} vs ${b.length}\n  js:     ${JSON.stringify(a).slice(0, 300)}\n  python: ${JSON.stringify(b).slice(0, 300)}`);
    a.forEach((x, i) => same(x, b[i], `${where}[${i}]`));
  } else if (isDict(a) && isDict(b)) {
    assert.deepEqual(Object.keys(a), Object.keys(b), `${where}: keys`);
    for (const k of Object.keys(a)) same(a[k], b[k], `${where}.${k}`);
  } else {
    assert.equal(fixPath(num(a)), num(b), `${where}`);
    if (typeof num(a) === "number") assert.equal(a instanceof Number, b instanceof Number, `${where}: int/float (${a} vs ${b})`);
  }
}

function replay(g, app) {
  const n = g.network, key = (x) => JSON.stringify(x);
  registry.npmJson = async (args) => {
    const r = n.npm.find((x) => key(x.args) === key(args));
    if (!r) throw new Error(`npm view not recorded: ${args.join(" ")}`);
    return r.result;
  };
  registry.resolveLock = async (d, asOf) => {
    const r = n.lock.find((x) => x.dir === (rel(d, app) || ".") && x.as_of === asOf);
    if (!r) throw new Error(`lockfile not recorded: ${d}`);
    return [r.lock, r.source];
  };
  net.postJson = async (url, body) => {
    const r = n.post.find((x) => x.url === url && key(x.body) === key(body));
    if (!r) throw new Error(`OSV POST not recorded: ${url}`);
    return r.result;
  };
  net.getJson = async (url) => {
    const r = n.get.find((x) => x.url === url) || n.url.find((x) => x.url === url);
    if (!r) throw new Error(`GET not recorded: ${url}`);
    if (r.error) throw new Error(r.error);
    return r.body !== undefined ? loadJson(r.body) : r.result;
  };
}

const files = fs.existsSync(DIR) ? fs.readdirSync(DIR).filter((f) => f.endsWith(".json")).sort() : [];
if (!files.length) test("collect goldens", { skip: "run python python/golden/record_collect.py first" }, () => {});
for (const f of files) {
  test(`collect ${f.replace(/\.json$/, "")}`, { timeout: 15 * 60 * 1000 }, async () => {
    const g = loadJson(fs.readFileSync(path.join(DIR, f), "utf8"));
    let app = g.app, copy = null;
    if (g.source) {  // recorded on a copy of a fixture (its tests write into it): run on a fresh copy too
      copy = fs.mkdtempSync(path.join(os.tmpdir(), "eval-js-golden-"));
      app = path.join(copy, path.basename(g.source));
      fs.cpSync(path.join(ROOT, g.source), app, { recursive: true });
      app = fs.realpathSync.native(app);
      SUBST = [app, g.app];
    } else if (!fs.existsSync(app)) return;  // the app is not on this machine
    replay(g, app);
    const out = fs.mkdtempSync(path.join(os.tmpdir(), "eval-js-collect-"));
    try {
      const m = await collect(app, out, g.opts);
      same(m, g.metrics);
    } finally {
      SUBST = null;
      fs.rmSync(out, { recursive: true, force: true });
      if (copy) fs.rmSync(copy, { recursive: true, force: true });
    }
  });
}
