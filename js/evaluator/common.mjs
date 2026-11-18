// common.mjs — Shared state of the evaluator: the rubric, the levels and small numeric helpers. Port of evaluator/common.py
// (the parts the scoring uses; the subprocess and file-walking helpers come with the collectors).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { F, floatRepr, loadJson, num, sorted, str } from "../lib/py.mjs";

export const HERE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");  // repository root
export const RUBRIC = loadJson(fs.readFileSync(path.join(HERE, "rubric.json"), "utf8"));  // floats stay floats, as in Python
export const LEVELS = ["Fails", "Partial", "Meets"];

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
  readText(app, rel) { return fs.readFileSync(path.join(app, rel), "utf8"); },
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
    return sorted(out, key).map((p) => { try { return fs.readFileSync(p, "utf8"); } catch { return null; } }).filter((t) => t !== null).join("\n");
  },
};
