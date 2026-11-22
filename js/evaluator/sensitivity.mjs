// sensitivity.mjs — Sensitivity of the overall score to the weighting scheme (see evaluator/sensitivity.py for the scenarios).
// Port of evaluator/sensitivity.py.
import { F, fixed, get, gfmt, num, pyRound, sorted, str, truthy } from "../lib/py.mjs";
import { RUBRIC, pointWeight } from "./common.mjs";

const GROUP_KEYS = ["level", "agent"];

/** [[name, description, spec]], spec = {weights} | {flat: true} | {weights, drop: pid}. */
export function scenarios() {
  const W = RUBRIC.subcharacteristic_weights, ks = Object.keys(W);
  const out = [["panel", "panel weights " + Object.values(W).map((w) => gfmt(100 * w)).join("/"), { weights: W }],
    ["uniform", "25% per subcharacteristic", { weights: Object.fromEntries(ks.map((s) => [s, F(1 / ks.length)])) }]];
  for (const [name, ws] of Object.entries(get(get(RUBRIC, "sensitivity", {}), "weight_sets") || {})) {
    if (name.startsWith("_")) continue;
    const tot = ks.reduce((a, s) => a + num(get(ws, s, 0)), 0);
    if (tot > 0) out.push([name, "weight set " + name, { weights: Object.fromEntries(ks.map((s) => [s, F(num(get(ws, s, 0)) / tot)])) }]);
  }
  out.push(["equal_points", "every evaluable point with the same weight", { flat: true }]);
  for (const pid of Object.keys(RUBRIC.points)) out.push([`without_${pid}`, `panel weights without ${pid}`, { weights: W, drop: pid }]);
  return out;
}

/** [min, max] of the overall score of a run under `spec`; [null, null] if not computable. */
export function overall(points, spec) {
  const ps = points.filter((p) => get(p, "score_min") !== null && p.id !== get(spec, "drop"));
  if (truthy(get(spec, "flat"))) {
    if (!ps.length) return [null, null];
    return ["score_min", "score_max"].map((k) => F(pyRound((100 * ps.reduce((a, p) => a + num(p[k]), 0)) / ps.length, 1)));
  }
  let lo = 0.0, hi = 0.0;
  for (const [s, w] of Object.entries(spec.weights)) {
    const sub = ps.filter((p) => p.subcharacteristics.includes(s));
    if (!sub.length) {
      if (w > 0) return [null, null];
      continue;
    }
    const tw = sub.reduce((a, p) => a + pointWeight(p.id), 0);  // same weighted mean as scoring.profile()
    lo += (num(w) * 100 * sub.reduce((a, p) => a + pointWeight(p.id) * num(p.score_min), 0)) / tw;
    hi += (num(w) * 100 * sub.reduce((a, p) => a + pointWeight(p.id) * num(p.score_max), 0)) / tw;
  }
  return [F(pyRound(lo, 1)), F(pyRound(hi, 1))];
}

/** {key: rank}, 1 = highest value; ties share the mean rank (an int when whole, else a float). */
export function ranks(values) {
  const order = sorted(Object.keys(values), (k) => -num(values[k]));
  const out = {};
  let i = 0;
  while (i < order.length) {
    let j = i;
    while (j + 1 < order.length && num(values[order[j + 1]]) === num(values[order[i]])) j += 1;
    const r = (i + j) / 2 + 1;
    for (const k of order.slice(i, j + 1)) out[k] = Number.isInteger(r) ? r : F(r);
    i = j + 1;
  }
  return out;
}

export function kendallTauB(a, b) {
  const ks = Object.keys(a).filter((k) => Object.prototype.hasOwnProperty.call(b, k));
  if (ks.length < 2) return null;
  let conc = 0, disc = 0, ta = 0, tb = 0;
  const sgn = (p, q) => (p > q) - (p < q);
  for (let i = 0; i < ks.length; i++)
    for (let j = i + 1; j < ks.length; j++) {
      const x = sgn(num(a[ks[i]]), num(a[ks[j]])), y = sgn(num(b[ks[i]]), num(b[ks[j]]));
      if (x === 0 && y === 0) continue;
      if (x === 0) ta += 1;
      else if (y === 0) tb += 1;
      else if (x === y) conc += 1;
      else disc += 1;
    }
  const den = ((conc + disc + ta) * (conc + disc + tb)) ** 0.5;
  return den === 0 ? null : F(pyRound((conc - disc) / den, 3));
}

function groupOrder(mids, meta, key) {
  const g = new Map();
  for (const [r, v] of Object.entries(mids)) {
    const k = get(meta[r], key) || "?";
    if (!g.has(k)) g.set(k, []);
    g.get(k).push(num(v));
  }
  return sorted([...g].map(([k, v]) => [k, F(pyRound(v.reduce((a, x) => a + x, 0) / v.length, 1))]), (x) => [-num(x[1]), x[0]]);
}

/** max(abs(rk[r] - ref[r]) for r in common), default 0: a float as soon as either rank is one (a shared rank such as 2.5). */
function maxShift(common, rk, ref) {
  let best = 0, bestV = -1;
  for (const r of common) {
    const d = Math.abs(num(rk[r]) - num(ref[r]));
    if (d > bestV) { bestV = d; best = rk[r] instanceof Number || ref[r] instanceof Number ? F(d) : d; }
  }
  return best;
}

/** runs: [[meta, points]] -> the scenarios, the per-run summary and the stability verdicts. */
export function sensitivity(runs) {
  const meta = Object.fromEntries(runs.map(([m]) => [m.run_id, m]));
  const out = { scenarios: [], runs: {}, groups: {} };
  let refMid = null, refRank = null, refGroups = null;
  for (const [name, desc, spec] of scenarios()) {
    const scores = Object.fromEntries(runs.map(([m, pts]) => [m.run_id, overall(pts, spec)]));
    const mids = Object.fromEntries(Object.entries(scores).filter(([, [lo]]) => lo !== null).map(([r, [lo, hi]]) => [r, F(pyRound((num(lo) + num(hi)) / 2, 2))]));
    const rk = ranks(mids);
    const groups = Object.fromEntries(GROUP_KEYS.map((k) => [k, groupOrder(mids, meta, k)]));
    const sc = { name, description: desc, scores: Object.fromEntries(Object.entries(scores).map(([r, v]) => [r, [...v]])), ranks: rk, groups };
    if (name === "panel") [refMid, refRank, refGroups] = [mids, rk, groups];
    else {
      const common = Object.keys(rk).filter((r) => Object.prototype.hasOwnProperty.call(refRank, r));
      const top = (x) => new Set(Object.keys(x).filter((r) => num(x[r]) === 1));
      const ta = top(rk), tr = top(refRank);
      Object.assign(sc, { tau_b: kendallTauB(refMid, mids), same_top: common.length > 0 && ta.size === tr.size && [...ta].every((r) => tr.has(r)),
        max_rank_shift: maxShift(common, rk, refRank),
        groups_same_order: Object.fromEntries(GROUP_KEYS.map((k) => [k, groups[k].map(([g]) => g).join("\u0000") === refGroups[k].map(([g]) => g).join("\u0000")])) });
    }
    out.scenarios.push(sc);
  }
  for (const [m] of runs) {
    const r = m.run_id;
    const rs = out.scenarios.filter((s) => Object.prototype.hasOwnProperty.call(s.ranks, r)).map((s) => s.ranks[r]);
    const sv = out.scenarios.flatMap((s) => s.scores[r]).filter((v) => v !== null);
    const best = rs.length ? rs.reduce((a, x) => (num(x) < num(a) ? x : a)) : null, worst = rs.length ? rs.reduce((a, x) => (num(x) > num(a) ? x : a)) : null;
    out.runs[r] = { panel_rank: get(refRank, r), best_rank: best, worst_rank: worst,
      score_low: sv.length ? sv.reduce((a, x) => (num(x) < num(a) ? x : a)) : null, score_high: sv.length ? sv.reduce((a, x) => (num(x) > num(a) ? x : a)) : null };
  }
  const alt = out.scenarios.filter((s) => s.name !== "panel");
  const taus = alt.map((s) => s.tau_b).filter((t) => t !== null);
  out.stable = { top: alt.every((s) => s.same_top), ...Object.fromEntries(GROUP_KEYS.map((k) => [k, alt.every((s) => s.groups_same_order[k])])),
    min_tau_b: taus.length ? taus.reduce((a, x) => (num(x) < num(a) ? x : a)) : null };
  out.changes = { top: alt.filter((s) => !s.same_top).map((s) => s.name), ...Object.fromEntries(GROUP_KEYS.map((k) => [k, alt.filter((s) => !s.groups_same_order[k]).map((s) => s.name)])) };
  return out;
}

const fmtScore = ([lo, hi]) => (lo === null ? "n/a" : num(lo) === num(hi) ? fixed(lo, 1) : `${fixed(lo, 1)}–${fixed(hi, 1)}`);
const fmtRank = (x) => (x === null || x === undefined ? "—" : gfmt(x));

export function sensitivityMd(s, heading = "##") {
  const runs = Object.keys(s.runs), alt = s.scenarios.filter((x) => x.name !== "panel");
  const L = [`${heading} Weight sensitivity`, "",
    "The panel weights have a non-significant concordance (Kendall's W = 0.0875), so every run is scored again under other weights: " +
    "uniform 25%, every point with the same weight, each point removed in turn" +
    (alt.some((x) => !["uniform", "equal_points", "without_"].some((p) => x.name.startsWith(p))) ? ", and the weight sets of `sensitivity.weight_sets` in `rubric.json`" : "") +
    ". Ranks use the midpoint of each score range (1 = best). τ = Kendall's tau-b against the panel ranking.", ""];
  if (runs.length < 2) return [...L, "A single run: there is no ranking to compare. Scores per scenario are in `_comparison/sensitivity.json`.", ""];
  const st = s.stable, ch = s.changes;
  const verdict = (ok, names) => (ok ? "holds in every scenario" : "changes under " + names.map((n) => `\`${n}\``).join(", "));
  L.push(`- **Best run**: ${verdict(st.top, ch.top)}.`, `- **Order of the levels** by mean score: ${verdict(st.level, ch.level)}.`,
    `- **Order of the agents** by mean score: ${verdict(st.agent, ch.agent)}.`, `- **Lowest τ** against the panel ranking: ${st.min_tau_b === null ? "n/a" : str(st.min_tau_b)}.`, "",
    "| Scenario | " + runs.join(" | ") + " | τ | Best run same | Levels | Agents |", "|---|" + "---|".repeat(runs.length + 4));
  const yn = (b) => (b ? "yes" : "**no**");
  for (const x of s.scenarios) {
    const cells = runs.map((r) => `${fmtScore(x.scores[r])} (#${fmtRank(get(x.ranks, r))})`);
    if (x.name === "panel") L.push("| **panel** | " + cells.join(" | ") + " | — | — | " + x.groups.level.map(([g]) => g).join(" > ") + " | " + x.groups.agent.map(([g]) => g).join(" > ") + " |");
    else L.push(`| ${x.name} | ` + cells.join(" | ") + ` | ${x.tau_b === null ? "n/a" : str(x.tau_b)} | ${yn(x.same_top)} | ${yn(x.groups_same_order.level)} | ${yn(x.groups_same_order.agent)} |`);
  }
  L.push("", "| Run | Panel rank | Rank across scenarios | Overall across scenarios |", "|---|---|---|---|");
  for (const [r, v] of Object.entries(s.runs)) L.push(`| ${r} | ${fmtRank(v.panel_rank)} | ${fmtRank(v.best_rank)}–${fmtRank(v.worst_rank)} | ${fmtScore([v.score_low, v.score_high])} |`);
  return [...L, ""];
}
