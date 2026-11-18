// tokens.mjs — The part of token_usage.py the outputs read: a run's token record, its per-phase summary and the number format.
import fs from "node:fs";
import { F, fixed, get, loadJson, pyRound, str, truthy } from "../lib/py.mjs";

export const RESULT_FILE = "token_usage.json";  // copy inside results/<run>/

export function load(p) {
  try { return loadJson(fs.readFileSync(p, "utf8")); } catch (e) { if (e.code === "ENOENT") return null; throw e; }
}

/** Per-phase totals and the ratios of each later phase to the initial one (null when a phase is missing). */
export function summary(data) {
  if (!truthy(data)) return null;
  const ph = Object.fromEntries(Object.entries(get(data, "phases", {})).map(([k, v]) => [k, v.totals]));
  const out = { phases: ph };
  const ini = get(ph, "initial");
  for (const [k, t] of Object.entries(ph)) {
    if (k === "initial") continue;
    out[`${k}_vs_initial`] = Object.fromEntries(["total_tokens", "input_tokens", "output_tokens"].map((f) => [f, ini && truthy(get(ini, f)) ? F(pyRound(t[f] / ini[f], 3)) : null]));
  }
  return out;
}

export function fmt(n) {
  if (n === null || n === undefined) return "n/a";
  return n >= 1e6 ? `${fixed(n / 1e6, 2)} M` : n >= 1e3 ? `${fixed(n / 1e3, 1)} k` : str(n);
}
