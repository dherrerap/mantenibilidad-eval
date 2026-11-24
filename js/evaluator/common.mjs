// common.mjs — Shared state of the evaluator: the rubric, the levels and small numeric helpers. Port of evaluator/common.py
// (the parts the scoring uses; the subprocess and file-walking helpers come with the collectors).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readText, F, floatRepr, loadJson, num, sorted, str } from "../lib/py.mjs";

export const HERE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");  // repository root
export const RUBRIC = loadJson(fs.readFileSync(path.join(HERE, "rubric.json"), "utf8"));  // floats stay floats, as in Python
export const LEVELS = ["Fails", "Partial", "Meets"];

/** Weight of every decision point inside every subcharacteristic it feeds (`point_weights` in rubric.json), as {pid: weight}; a point the
 * rubric gives no weight weighs 1, which makes each subcharacteristic the plain mean of its points. Checks the whole map: every key must
 * be a point of the rubric (or start with "_", like `_comment`) and every value a positive number. Read at call time, so a test or a
 * script can change the rubric in memory; it is also checked once when this module loads, so a bad rubric fails before any collector runs. */
export function pointWeights() {
  const pw = RUBRIC.point_weights || {}, out = {};
  for (const [k, v] of Object.entries(pw)) {
    if (k.startsWith("_")) continue;
    if (!Object.hasOwn(RUBRIC.points, k)) throw new Error(`rubric.json point_weights.${k} is not a decision point of the rubric`);
    const w = num(v);
    if (!(Number.isFinite(w) && w > 0)) throw new Error(`rubric.json point_weights.${k} must be a positive number`);
  }
  for (const pid of Object.keys(RUBRIC.points)) out[pid] = Object.hasOwn(pw, pid) ? num(pw[pid]) : 1;
  return out;
}
pointWeights();

/** Weight of one decision point (see pointWeights()). */
export const pointWeight = (pid) => pointWeights()[pid] ?? 1;

/** Weighted mean of `key` over `points` with the weights `w` ({pid: weight}, from pointWeights()); null when there are no points. The one
 * aggregation rule of a subcharacteristic, shared by scoring.profile() and sensitivity.overall(). */
export function weightedMean(points, key, w) {
  if (!points.length) return null;
  const tw = points.reduce((a, p) => a + (w[p.id] ?? 1), 0);
  return points.reduce((a, p) => a + (w[p.id] ?? 1) * num(p[key]), 0) / tw;
}

/** None if b is 0, else a percentage (a Python float). */
export const pct = (a, b) => (!num(b) ? null : F((100.0 * num(a)) / num(b)));

/** statistics.median: the middle element (keeps its type) for an odd count, the mean of the two middle ones (a float) for an even one. */
export function median(xs) {
  if (!xs.length) return null;
  const s = sorted(xs), n = s.length;
  return n % 2 ? s[(n - 1) / 2] : F((num(s[n / 2 - 1]) + num(s[n / 2])) / 2);
}

/** f"{x}" of a value that is a float in Python. */
export const fstr = (x) => (x === null || x === undefined ? "None" : typeof x === "number" || x instanceof Number ? floatRepr(x) : str(x));

/** File helpers the points need (the error middleware's file, the design documents). The differential test replaces them with
 *  what the Python run read, since the apps of the test suite live in temporary folders. */
export const appFs = {
  readText(app, rel) { return readText(path.join(app, rel)); },
  designText(app) {
    if (!app) return "";
    const docs = path.join(app, "docs");
    const out = [];
    const walk = (d) => {
      let names;
      try { names = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
      for (const e of names) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) { if (e.name !== "node_modules") walk(p); }
        else if (/\.md$/i.test(e.name)) out.push(p);
      }
    };
    try { if (!fs.statSync(app).isDirectory()) return ""; } catch { return ""; }
    walk(docs);
    const key = (p) => path.relative(app, p).split(path.sep).map((x) => (process.platform === "win32" ? x.toLowerCase() : x));
    return sorted(out, key).map((p) => { try { return readText(p); } catch { return null; } }).filter((t) => t !== null).join("\n");
  },
};

const MISSING_MODEL_VALUES = new Set(["", "n/a", "na", "none", "null", "unknown", "?"]);
export const MODEL_WARNING = "The generator model was not recorded (`--model`). It is a variable of the experiment: without it the result cannot be attributed to " +
  "a model, compared with other models or reproduced.";
/** True when the generator model was not given (null, empty, n/a, unknown…). */
export const modelMissing = (model) => model === null || model === undefined || MISSING_MODEL_VALUES.has(str(model).trim().toLowerCase());

/** Local ISO date and time to the second, as Python's datetime.now().isoformat(timespec="seconds"). */
export function nowIso(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

