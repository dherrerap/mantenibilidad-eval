// Decision points Layers, Cohesion, Coupling and Cyclomatic complexity. Port of evaluator/points/{layers,cohesion,coupling,
// cyclomatic}.py.
import { F, fixed, get, gfmt, num, or, pyRound, sorted, str, truthy } from "../../lib/py.mjs";
import { RUBRIC, fstr, median, pct } from "../common.mjs";
import { C, applyManual, heur, levelFrom, levelFromPct } from "../criteria.mjs";
import { usable } from "../helpers.mjs";
import { cliques, fanIn } from "../graph.mjs";

const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

// ───────────────────────── Layers ─────────────────────────
export function evalLayers(m, manual, opts) {
  const T = RUBRIC.thresholds.layers, P = RUBRIC.default_layers.allowed;
  const amb = new Set(get(RUBRIC.default_layers, "ambiguous", []).map((x) => x.toLowerCase()));
  const layers = m.layers, origin = get(m, "layers_origin", {});
  const main = new Set(["presentation", "business", "data"]);
  const ident = sorted([...new Set(Object.values(layers))].filter((x) => main.has(x)));
  let cross = 0, viol = 0, doubtful = 0;
  const ev = [], core = [];
  const mods = new Map(get(m.graph, "modules", []).map((mod) => [mod.source, mod]));
  const allowed = (a, b) => P.some(([x, y]) => x === a && y === b);
  const sharedCore = (f) => {
    if (!amb.has(str(get(origin, f, "")).toLowerCase())) return false;
    const deps = get(mods.get(f) || {}, "deps", []);
    return !deps.some((d) => d.local && ["presentation", "data"].includes(get(layers, d.to)));
  };
  for (const mod of get(m.graph, "modules", [])) {
    const a = get(layers, mod.source);
    if (!main.has(a)) continue;
    for (const d of mod.deps) {
      const b = d.local ? get(layers, d.to) : null;
      if (!main.has(b) || a === b) continue;
      cross += 1;
      if (!allowed(a, b) && sharedCore(d.to)) {
        if (core.length < 8) core.push(`${mod.source} (${a}) → ${d.to} (shared core)`);
      } else if (!allowed(a, b)) {
        viol += 1;
        const dbt = amb.has(str(get(origin, mod.source, "")).toLowerCase()) || amb.has(str(get(origin, d.to, "")).toLowerCase());
        doubtful += dbt ? 1 : 0;
        if (ev.length < 8) ev.push(`${mod.source} (${a}) → ${d.to} (${b})` + (dbt ? " [doubtful classification]" : ""));
      }
    }
  }
  if (ident.length < T.min_identifiable_layers) {
    const crit = { C1: C(false, `Identifiable layers (≥${str(T.min_identifiable_layers)})`, ident), C2: C(false, "Violations ≤ 5% of inter-layer dependencies", "n/a") };
    return [crit, { layers: ident, inter_layer_dependencies: cross, violations: viol, violations_pct: F(0.0) }, ev,
      `Layers detected: ${ident.join(", ") || "none"}; not enough layers.`, ["Fails", "Fails", "Fails"]];
  }
  const levelWith = (v) => {
    const vp = cross ? pct(v, cross) : F(0.0);
    return [levelFromPct(num(vp), (x) => x <= T.meets_max_violations_pct, (x) => x <= T.partial_max_violations_pct), vp];
  };
  const [nAll, vpct] = levelWith(viol);
  const [nFirm] = levelWith(viol - doubtful);
  const crit = { C1: C(true, `Identifiable layers (≥${str(T.min_identifiable_layers)})`, ident) };
  const desc2 = "Violations ≤ 5% of inter-layer dependencies";
  let forced, finding;
  if (cross === 0) {
    const c2 = C(null, desc2, "0 inter-layer dependencies", "pending (manual)");
    applyManual("layers", { C2: c2 }, manual); crit.C2 = c2;
    forced = c2.ok ? ["Meets", "Meets", "Meets"] : c2.ok === false ? ["Fails", "Fails", "Fails"] : [null, "Fails", "Meets"];
    finding = `Layers detected: ${ident.join(", ")}; 0 inter-layer dependencies (possible dependency injection): no structural evidence; requires manual review (layers.C2).`;
  } else if (doubtful && nFirm !== nAll) {
    const c2 = C(null, desc2 + " (discounting doubtful classifications)", `${viol}/${cross} violations, ${doubtful} with doubtful classification`, "pending (manual)");
    applyManual("layers", { C2: c2 }, manual); crit.C2 = c2;
    forced = c2.ok ? [nFirm, nFirm, nFirm] : c2.ok === false ? [nAll, nAll, nAll] : [null, nAll, nFirm];
    finding = `Layers detected: ${ident.join(", ")}; ${viol} of ${cross} dependencies break the rule, ${doubtful} because of a doubtful classification ` +
      `(ambiguous directory): from ${nAll} to ${nFirm} depending on manual review (layers.C2) or a .layers.json.`;
  } else {
    crit.C2 = C(nAll !== "Fails", desc2, `${viol}/${cross} = ${fixed(vpct, 1)}%`);
    forced = [nAll, nAll, nAll];
    finding = `Layers detected: ${ident.join(", ")}; ${viol} of ${cross} inter-layer dependencies break the rule.`;
  }
  const evOut = [...ev];
  if (core.length) {
    finding += ` ${core.length} dependency(ies) on a shared core module (domain without outer-layer dependencies) not counted as violations.`;
    evOut.push(...core.slice(0, 3));
  }
  return [crit, { layers: ident, inter_layer_dependencies: cross, violations: viol, doubtful_violations: doubtful, violations_pct: vpct, shared_core_dependencies: core },
    evOut, finding, forced];
}

// ───────────────────────── Cohesion ─────────────────────────
export function mixedResponsibilityFiles(ast) {
  const routes = new Set(get(ast, "routes", []).map((r) => r.file));
  const data = new Set([...get(ast, "sqlStrings", []).filter((s) => !truthy(get(s, "migration"))).map((s) => s.file), ...get(ast, "queryFields", []).map((q) => q.file)]);
  const tests = new Set(get(ast, "files", []).filter((f) => truthy(get(f, "test"))).map((f) => f.path));
  return sorted([...routes].filter((f) => data.has(f) && !tests.has(f)));
}

export const oversizedComponents = (ast, locMax) =>
  sorted(get(ast, "components", []).filter((c) => c.loc > locMax).map((c) => [`${c.file}:${c.line} ${c.name} (${c.loc} LOC)`, c.loc]), (x) => -x[1]).map((x) => x[0]);

export function evalCohesion(m, manual, opts) {
  const T = RUBRIC.thresholds.cohesion;
  const fns = m.ast.functions.filter((f) => !f.test);
  const hi = fns.filter((f) => f.fanout > T.fanout_max);
  const p = pct(hi.length, fns.length);
  const fi = fanIn(m), locs = Object.fromEntries(m.ast.files.map((f) => [f.path, f.loc]));
  const gods = Object.entries(fi).filter(([k, v]) => or(get(locs, k), 0) >= T.god_loc_min && v >= T.god_fanin_min).map(([k, v]) => `${k} (LOC=${str(get(locs, k))}, fan-in=${v})`);
  const prod = m.ast.files.filter((f) => !f.test);
  const frag = prod.length ? pct(prod.filter((f) => f.loc < 10).length, prod.length) : 0;
  const dl = get(or(get(manual, "dv8"), {}), "DL");
  const c1 = C(p !== null && p <= T.pct_fanout_max, "≤ 5% of functions with fan-out > 5", p !== null ? `${hi.length}/${fns.length} = ${fixed(p, 1)}%` : null);
  const c2 = C(dl === null ? null : dl >= T.DL_min, "DV8 DL ≥ 60%", dl, dl !== null ? "dv8" : "pending (DV8)");
  const mixed = mixedResponsibilityFiles(m.ast);
  const big = oversizedComponents(m.ast, T.component_loc_max);
  const c3Txt = "Checklist with no findings ('god' module, mixed responsibilities, fragmentation)";
  const c3Val = { suggested_god_modules: gods, files_under_10_loc_pct: frag === null ? null : typeof frag === "number" ? frag : F(pyRound(frag, 1)),
    routes_and_queries_in_one_file: mixed, [`components_over_${str(T.component_loc_max)}_loc`]: big };
  // a measured finding decides it; otherwise "unrelated responsibilities" needs reading the code (suggestion)
  const c3 = mixed.length || big.length ? C(false, c3Txt, c3Val) : heur(C(null, c3Txt, c3Val, "auto", !gods.length && num(frag) < 40), opts);
  const oversized = sorted(prod.filter((f) => f.loc > T.file_loc_max).map((f) => [f.path, f.loc]), (x) => -x[1]);
  const c4 = C(oversized.length === 0, `0 production files with more than ${str(T.file_loc_max)} LOC (CWE-1080)`, oversized.length);
  const crit = { C1: c1, C2: c2, C3: c3, C4: c4 };
  applyManual("cohesion", crit, manual);
  const ev = [...sorted(hi, (f) => -f.fanout).slice(0, 5).map((f) => `${f.file}:${f.line} ${f.name} (fan-out=${f.fanout})`), ...gods.slice(0, 3),
    ...oversized.slice(0, 3).map(([q, l]) => `${q}: ${l} LOC`), ...mixed.slice(0, 3).map((x) => `routes and database queries in one module: ${x}`),
    ...big.slice(0, 3).map((x) => `component over ${str(T.component_loc_max)} LOC: ${x}`)];
  const il = get(or(get(manual, "dv8"), {}), "IL");
  return [crit, { pct_fanout: p, functions_fanout_above: hi.length, suggested_god_modules: gods, oversized_files: oversized.length, IL: il,
    mixed_responsibility_files: mixed, oversized_components: big }, ev,
    `${hi.length} of ${fns.length} functions with fan-out > ${str(T.fanout_max)}; ${gods.length} candidate 'god' module(s); ${oversized.length} file(s) over ${str(T.file_loc_max)} LOC.`, null];
}

// ───────────────────────── Coupling ─────────────────────────
function knipResult(m) {
  const kn = or(get(m, "knip"), {});
  if (truthy(get(kn, "ok"))) return [kn, null];
  return [null, "Knip did not run: " + or(get(kn, "error"), "no knip result in metrics.json (evaluate the app again)").slice(0, 200)];
}

function unusedDependencies(kn, includeDev) {
  const out = [...kn.dependencies];
  if (truthy(includeDev)) {
    const bins = new Set(get(kn, "binaries", []));
    out.push(...kn.devDependencies.filter((x) => !bins.has(x)));
  }
  return out;
}

const deadFiles = (m, kn) => {
  const prod = new Set(m.ast.files.filter((f) => !f.test).map((f) => f.path));
  return sorted(kn.files.filter((f) => prod.has(f)));
};

export function evalCoupling(m, manual, opts) {
  const T = RUBRIC.thresholds.coupling;
  const mods = get(m.graph, "modules", []);
  const A = mods.filter((x) => new Set(x.deps.map((d) => d.module)).size < T.outgoing_deps_max).length;
  const X = mods.length ? A / mods.length : null;
  const pc = get(or(get(manual, "dv8"), {}), "PC");
  const [kn, note] = knipResult(m);
  const unused = kn ? unusedDependencies(kn, T.include_devdependencies) : [];
  const direct = m.packages.direct;
  const pu = truthy(direct) ? pct(unused.length, direct) : F(0.0);
  const orphans = kn ? deadFiles(m, kn) : [];
  const DC = RUBRIC.thresholds.dead_code;
  const src = kn ? `auto (Knip ${str(kn.version)})` : `pending (${note})`;
  const cycles = get(m.graph, "cycles", []);
  const crit = {
    C1: C(cycles.length === 0, "0 dependency cycles (CWE-1047)", cycles.length),
    C2: C(X === null ? null : X >= T.X_min, "X (MMo-1-G) ≥ 0.90", X === null ? null : F(pyRound(X, 3))),
    C3: C(pc === null ? null : pc <= T.PC_max, `Propagation Cost (DV8) ≤ ${gfmt(num(T.PC_max) * 100)}%`, pc, pc !== null ? "dv8" : "pending (DV8)"),
    C4: C(kn ? pu <= T.pct_unused_max : null, "≤ 10% unused dependencies", kn ? `${unused.length}/${str(direct)} = ${fixed(pu, 1)}%` : null, src),
    C5: C(kn ? orphans.length <= DC.structural_max_files : null, `≤ ${str(DC.structural_max_files)} production file(s) unreachable from every entry point (CWE-561)`,
      kn ? orphans.length : null, src),
  };
  applyManual("coupling", crit, manual);
  const cq = cliques(m);
  const ev = [...cycles.slice(0, 4).map((c) => c.slice(0, 4).join(" ↔ ")), ...unused.slice(0, 6),
    ...cq.slice(0, 3).map((c) => `clique of ${c.length} files: ${c.slice(0, 4).join(", ")}`),
    ...orphans.slice(0, 4).map((h) => `structurally dead (no entry point reaches it): ${h}`)];
  const met = { modules: mods.length, cycles: cycles.length, X: X === null ? null : F(X), orphan_files: orphans, cliques: cq.length,
    files_in_cliques: cq.reduce((s, c) => s + c.length, 0), unused_dependencies: unused };
  let finding = `${cycles.length} cycles (${cq.length} clique(s)); X=${X === null ? "n/a" : fixed(X, 2)}; `;
  if (kn) {
    Object.assign(met, { unused_exports: kn.exports.length, unlisted_dependencies: kn.unlisted, unresolved_imports: kn.unresolved, knip_config_load_errors: kn.config_load_errors });
    ev.push(...kn.unlisted.slice(0, 3).map((x) => `used but not declared in package.json: ${x.name} (${x.file})`));
    finding += `${unused.length} unused dependencies; ${orphans.length} production file(s) no entry point reaches (CWE-561); ` +
      `${kn.exports.length} unused export(s) and ${kn.unlisted.length} dependency(ies) used but not declared (informational).`;
  } else finding += `unused dependencies and dead files not measured (${note}).`;
  return [crit, met, ev, finding, null];
}

// ───────────────────────── Cyclomatic complexity ─────────────────────────
function cognitiveMetrics(fns, lint) {
  const TC = RUBRIC.thresholds.cognitive.function_threshold;
  if (lint === null) return { cognitive_source: null, cognitive_threshold: TC, cognitive_median: null, cognitive_max: null, functions_cog_above_threshold: null, _high: [] };
  const vals = lint.cognitive.map((x) => ({ file: x.file, line: x.line, cog: x.value }));
  const cogs = sorted([...Array(Math.max(fns.length - vals.length, 0)).fill(0), ...vals.map((v) => v.cog)]);
  const high = sorted(vals.filter((v) => v.cog > TC), (v) => -num(v.cog));
  return { cognitive_source: "SonarJS S3776", cognitive_threshold: TC, cognitive_median: median(cogs), cognitive_max: cogs.length ? cogs.at(-1) : null,
    functions_cog_above_threshold: high.length, _high: high };
}

function crossCheck(fns, eslint, threshold) {
  const ours = new Map(), theirs = new Map();
  for (const f of fns) { const k = JSON.stringify([f.file, f.line]); if (!ours.has(k)) ours.set(k, f.cc); }
  for (const x of eslint) { const k = JSON.stringify([x.file, x.line]); if (!theirs.has(k)) theirs.set(k, x.value); }
  const both = [...ours.keys()].filter((k) => theirs.has(k));
  const equal = both.filter((k) => num(ours.get(k)) === num(theirs.get(k))).length;
  const above = [...theirs.values()].filter((v) => v > threshold).length;
  return { matched: both.length, ours: ours.size, eslint: theirs.size,
    equal_pct: both.length ? F(pyRound((100.0 * equal) / both.length, 1)) : null,
    max_abs_diff: both.length ? Math.max(...both.map((k) => Math.abs(ours.get(k) - theirs.get(k)))) : null,
    above_threshold: above, X: theirs.size ? F(pyRound(1 - above / theirs.size, 4)) : null };
}

function lintMeasures(m, fns, threshold) {
  const [lint, note] = usable(m);
  const met = cognitiveMetrics(fns, lint);
  const high = met._high; delete met._high;
  if (lint === null) return [met, [], ` Cognitive complexity not measured (${note}).`];
  const ev = high.slice(0, 3).map((f) => `${f.file}:${f.line} (cognitive=${str(f.cog)})`);
  let txt = ` Cognitive complexity (SonarJS S3776): ${high.length} functions > ${str(met.cognitive_threshold)}, max ${str(met.cognitive_max)} (informational).`;
  const x = (met.mccabe_eslint = crossCheck(fns, lint.mccabe, threshold));
  if (x.matched) txt += ` Cross-check with ESLint \`complexity\`: same value in ${fstr(x.equal_pct)}% of ${x.matched} matched functions, X = ${fstr(x.X)} (informational).`;
  return [met, ev, txt + (note ? ` ${note}.` : "")];
}

export function evalCyclomatic(m, manual, opts) {
  const T = RUBRIC.thresholds.cyclomatic;
  const fns = m.ast.functions.filter((f) => !f.test);
  const B = fns.length, big = fns.filter((f) => f.cc > T.function_threshold);
  const X = B ? 1 - big.length / B : null;
  const ccs = sorted(fns.map((f) => f.cc));
  const met = { functions: B, functions_cc_above_threshold: big.length, X: X === null ? null : F(X), median: median(ccs),
    p90: ccs.length ? ccs[Math.trunc(0.9 * (ccs.length - 1))] : null, max: ccs.length ? ccs.at(-1) : null };
  if (X === null) return [{}, met, [], "No implemented functions.", [null, null, null]];
  let ev = sorted(big, (f) => -f.cc).slice(0, 8).map((f) => `${f.file}:${f.line} ${f.name} (CC=${f.cc})`);
  const crit = { C1: C(X >= T.partial_X_min, "X ≥ 0.95 (Partial)", F(pyRound(X, 4))), C2: C(X >= T.meets_X_min, "X ≥ 0.98 (Meets)", F(pyRound(X, 4))) };
  let finding = `X = 1 − ${big.length}/${B} = ${fixed(X, 3)}; median CC ${str(met.median)}, p90 ${str(met.p90)}, max ${str(met.max)}.`;
  const [lmet, lev, ltxt] = lintMeasures(m, fns, T.function_threshold);
  Object.assign(met, lmet); ev = [...ev, ...lev]; finding += ltxt;
  const T2 = RUBRIC.thresholds.duplication;
  const dup = or(get(m, "duplication"), {});
  const ok = truthy(get(dup, "ok"));
  crit.C3 = C(!ok ? null : dup.pct <= T2.pct_max, `≤ ${gfmt(T2.pct_max)}% duplicated lines (CWE-1041)`, ok ? `${fixed(dup.pct, 1)}%` : null, ok ? "auto" : "pending (jscpd)");
  if (ok) {
    Object.assign(met, { duplication_pct: dup.pct, clones: dup.clones, duplication_above_threshold: dup.pct > T2.pct_max });
    ev = [...ev, ...dup.top.slice(0, 3).map((c) => `clone ${str(c)}`)];
    finding += ` Duplication (jscpd): ${fixed(dup.pct, 1)}% of lines, ${str(dup.clones)} clones (threshold ${gfmt(T2.pct_max)}%, CWE-1041).`;
  }
  applyManual("cyclomatic", crit, manual);
  return [crit, met, ev, finding, levelFrom(crit)];
}

export { has };
