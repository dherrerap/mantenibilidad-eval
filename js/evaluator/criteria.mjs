// criteria.mjs — How a criterion is built, how manual review and the judge fill it, and how a level (or a range of levels, when
// criteria are pending) follows from the criteria (Table 26). Port of evaluator/criteria.py.
import { get, isDict, or, str, truthy } from "../lib/py.mjs";
import { RUBRIC } from "./common.mjs";

export const C = (ok, desc, value = null, source = "auto", suggested = null) => ({ ok, desc, value, source, suggested });
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

export function applyManual(pid, crits, manual) {
  for (const [cid, v] of Object.entries(or(get(manual, pid), {}))) {
    if (!has(crits, cid) || cid === "note") continue;
    const ok = isDict(v) ? get(v, "ok") : v;
    if (ok === null || ok === undefined) continue;
    crits[cid].ok = truthy(ok);
    crits[cid].source = "manual";
    if (isDict(v) && truthy(get(v, "note"))) crits[cid].value = v.note;
  }
  // the judge (judge.py) only fills what is still pending: manual review and automatic measurements take precedence
  const jz = or(get(manual, "_judge"), {});
  for (const [cid, d] of Object.entries(or(get(get(jz, "decisions", {}), pid), {}))) {
    if (has(crits, cid) && crits[cid].ok === null && get(d, "ok") !== null) {
      crits[cid].ok = truthy(d.ok);
      crits[cid].source = `judge (${str(get(get(jz, "meta", {}), "judge_model", "?"))})`;
      crits[cid].value = or(get(d, "justification"), crits[cid].value);
    }
  }
}

/** Heuristic-source criterion: only counts if heuristics are accepted. */
export function heur(crit, opts) {
  if (crit.suggested !== null) {
    crit.source = "heuristic";
    crit.ok = truthy(opts.accept_heuristics) ? crit.suggested : null;
  }
  return crit;
}

/** [level, level_min, level_max]; null in a criterion = pending. */
export function levelFrom(crits, must = []) {
  const pm = RUBRIC.partial_min_fraction;
  const lvl = (vals) => {
    if (must.some((k) => has(vals, k) && !vals[k])) return "Fails";
    const n = Object.keys(vals).length, k = Object.values(vals).filter(Boolean).length;
    return k === n ? "Meets" : k / n >= pm ? "Partial" : "Fails";
  };
  const lo = lvl(Object.fromEntries(Object.entries(crits).map(([k, v]) => [k, truthy(v.ok)])));
  const hi = lvl(Object.fromEntries(Object.entries(crits).map(([k, v]) => [k, v.ok === null ? true : truthy(v.ok)])));
  return [lo === hi ? lo : null, lo, hi];
}

export const levelFromPct = (value, meetsOk, partialOk) => (meetsOk(value) ? "Meets" : partialOk(value) ? "Partial" : "Fails");

export const pdict = (pid) => ({ id: pid, ...RUBRIC.points[pid] });
