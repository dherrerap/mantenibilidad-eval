// supplementary.mjs — Informational indicators that score none of the 11 points, and the ISO/IEC 5055 weaknesses no point scores.
// Port of evaluator/supplementary.py.
import { F, fixed, get, gfmt, or, pyRound, search, sorted, str, truthy } from "../lib/py.mjs";
import { fold } from "../relational/schema.mjs";
import { RUBRIC } from "./common.mjs";
import { decideCount, usable } from "./helpers.mjs";

const README_TOPICS = { installation: "install|npm i", execution: String.raw`\brun|execut|npm (run )?start|docker`, tests: "test",
  API: "api|endpoint|route", configuration: String.raw`\.env|variable|config` };

export function supplementaryIndicators(m) {
  const R = RUBRIC.thresholds.supplementary, a = m.ast, res = [];
  const add = (id, group, name, value, ref, ok, detail, ev = []) =>
    res.push({ id, group, name, value, reference: ref, status: ok === null || ok === undefined ? "n/a" : truthy(ok) ? "ok" : "review", detail, evidence: [...ev].slice(0, 5) });

  const tc = get(a, "testCases", []);
  const noAsserts = tc.filter((t) => !truthy(t.asserts));
  add("tests_without_assertions", "Tests", "Test cases without assertions", noAsserts.length, "0",
    !tc.length ? null : !noAsserts.length, `${noAsserts.length} of ${tc.length} cases contain no assert/expect.`, noAsserts.map((t) => `${t.file}:${t.line}`));
  const locT = a.files.filter((f) => f.test).reduce((s, f) => s + f.loc, 0), locP = a.files.filter((f) => !f.test).reduce((s, f) => s + f.loc, 0);
  const ratio = locP ? locT / locP : null;
  add("tests_loc_ratio", "Tests", "Test LOC / production LOC", ratio === null ? null : F(pyRound(ratio, 2)), `≥ ${str(R.test_ratio_min)}`,
    ratio === null ? null : ratio >= R.test_ratio_min, `${locT} test lines against ${locP} production lines.`);
  const tfiles = new Set(a.files.filter((f) => f.test).map((f) => f.path));
  const integ = new Set(a.imports.filter((i) => tfiles.has(i.file) && RUBRIC.libs_integration_test.includes(i.spec)).map((i) => i.file));
  add("tests_integration", "Tests", "Integration test files (HTTP or database)", integ.size, "≥ 1",
    !tfiles.size ? null : integ.size > 0, `${integ.size} of ${tfiles.size} test files touch the API or the database.`);

  const docs = get(a, "docs", []);
  const ndoc = docs.filter((d) => truthy(d.documented)).length;
  const dpct = docs.length ? (100.0 * ndoc) / docs.length : null;
  add("doc_jsdoc", "Documentation", "Top-level functions and methods with JSDoc (%)", dpct === null ? null : F(pyRound(dpct, 1)), `≥ ${str(R.jsdoc_min_pct)}%`,
    dpct === null ? null : dpct >= R.jsdoc_min_pct, `${ndoc} of ${docs.length} functions documented.`,
    docs.filter((d) => !truthy(d.documented)).map((d) => `${d.file}:${d.line} ${d.name}`));
  const rd = get(m, "readme", "") ?? "";
  const topics = Object.keys(README_TOPICS);
  const covered = topics.filter((k) => search(README_TOPICS[k], rd, "i"));
  add("doc_readme", "Documentation", "Topics covered by the README", `${covered.length}/${topics.length}`, `${topics.length}/${topics.length}`,
    truthy(rd) && covered.length === topics.length, (!truthy(rd) ? "No README. " : "") + "Missing: " + (topics.filter((k) => !covered.includes(k)).join(", ") || "none") + ".");

  const comps = get(a, "components", []), hooks = get(a, "hooks", []);
  if (comps.length || hooks.length) {
    const big = comps.filter((c) => c.loc > R.component_loc_max);
    const many = comps.filter((c) => c.props > R.component_props_max);
    const nodeps = hooks.filter((h) => truthy(h.noDeps));
    add("fe_large_components", "Frontend", `Components over ${str(R.component_loc_max)} lines`, big.length, "0", !big.length,
      `${big.length} of ${comps.length} components.`, big.map((c) => `${c.file}:${c.line} ${c.name} (${c.loc} lines)`));
    add("fe_props", "Frontend", `Components with more than ${str(R.component_props_max)} props`, many.length, "0", !many.length,
      `${many.length} of ${comps.length} components (a sign of prop drilling or lack of composition).`, many.map((c) => `${c.file}:${c.line} ${c.name} (${c.props} props)`));
    add("fe_hooks_without_deps", "Frontend", "useEffect/useCallback/useMemo without a dependency array", nodeps.length, "0", !nodeps.length,
      `${nodeps.length} of ${hooks.length} hooks run on every render.`, nodeps.map((h) => `${h.file}:${h.line} ${h.hook}`));
    const ft = a.files.filter((f) => f.test && f.frontend);
    add("fe_tests", "Frontend", "Frontend test files", ft.length, "≥ 1", ft.length > 0, `${ft.length} test files in the frontend.`);
  }

  const sec = get(a, "security", {});
  for (const [id, key, name] of [["sec_eval", "evalCalls", "Use of eval / new Function"], ["sec_secrets", "secrets", "Literal credentials in the code"],
    ["sec_sql", "sqlInjection", "Raw SQL built by interpolation or concatenation"]]) {
    const xs = get(sec, key, []);
    add(id, "Static security", name, xs.length, "0", !xs.length, `${xs.length} finding(s).`, xs.map((x) => `${x.file}:${x.line}`));
  }

  const props = new Set(or(get(m.contract, "properties"), []));
  const fields = new Set(Object.values(m.schema.tables).flatMap((t) => Object.values(t.columns).map((c) => c.name)));
  const normProps = new Set([...props].map(fold));
  if (props.size && fields.size) {
    const missing = sorted([...fields].filter((f) => !normProps.has(fold(f))));
    const cov = (100.0 * (fields.size - missing.length)) / fields.size;
    add("contract_schema", "Contract", "Table columns present in the contract (%)", F(pyRound(cov, 1)), `≥ ${str(R.contract_fields_min_pct)}%`,
      cov >= R.contract_fields_min_pct, `${fields.size - missing.length} of ${fields.size} fields appear as a property in the contract.`, missing.map((c) => `missing ${c}`));
  }
  for (const row of ascmmIndicators(m)) add(...row);
  return res;
}

/** CWE-1085: functions whose commented-out lines (SonarJS S125) exceed `maxPct` of their lines. [[function, commented lines]]. */
export function commentedOutFunctions(fns, reports, maxPct) {
  const byFile = new Map();
  for (const x of reports) {
    if (!byFile.has(x.file)) byFile.set(x.file, new Set());
    for (let l = x.line; l <= x.end_line; l++) byFile.get(x.file).add(l);
  }
  const out = [];
  for (const f of fns) {
    const lines = byFile.get(f.file) ?? new Set();
    let n = 0;
    for (let l = f.line; l < f.line + f.loc; l++) if (lines.has(l)) n += 1;
    if (n && (100.0 * n) / f.loc > maxPct) out.push([f, n]);
  }
  return out;
}

/** Informational ISO/IEC 5055 weaknesses that no point scores. Rows: [id, group, name, value, reference, ok, detail, evidence]. */
export function ascmmIndicators(m) {
  const T = RUBRIC.thresholds.ascmm, a = m.ast, rows = [];
  const fns = get(a, "functions", []).filter((f) => !f.test);
  const kloc = a.files.filter((f) => !f.test).reduce((s, f) => s + f.loc, 0) / 1000.0;
  const dens = (n) => (kloc ? ` (${fixed(n / kloc, 2)}/KLOC)` : "");
  const many = fns.filter((f) => get(f, "params", []).length > T.params_max);
  rows.push(["ascmm_cwe1064", "ASCMM", `CWE-1064 Functions with more than ${str(T.params_max)} parameters`, many.length, "0", !many.length,
    `${many.length} of ${fns.length} functions${dens(many.length)}. Default of ISO/IEC 5055: ${str(T.params_max)} parameters.`,
    many.map((f) => `${f.file}:${f.line} ${f.name} (${f.params.length} parameters)`)]);
  const [lint, note] = usable(m);
  const tail = note ? ` ${note}.` : "";
  for (const [cwe, d] of Object.entries(get(get(RUBRIC, "lint", {}), "ascmm", {}))) {
    const id = "ascmm_" + cwe.toLowerCase().replaceAll("-", "").replaceAll("/", "_");
    if (lint === null) { rows.push([id, "ASCMM", `${cwe} ${d.name}`, null, "0", null, note + "."]); continue; }
    const reps = get(lint.ascmm, cwe, []);
    if (cwe === "CWE-1085") {
      const bad = commentedOutFunctions(fns, reps, T.commented_code_max_pct);
      rows.push([id, "ASCMM", `${cwe} Functions with more than ${gfmt(T.commented_code_max_pct)}% commented-out code`, bad.length, "0",
        decideCount(bad.length, lint, note),
        `${bad.length} of ${fns.length} functions${dens(bad.length)}; ${reps.length} commented-out block(s) in total (SonarJS S125).${tail}`,
        bad.map(([f, n]) => `${f.file}:${f.line} ${f.name} (${n} of ${f.loc} lines)`)]);
      continue;
    }
    const rules = sorted([...new Set(reps.map((x) => x.rule))]);
    rows.push([id, "ASCMM", `${cwe} ${d.name}`, reps.length, str(T.occurrences_max), decideCount(reps.length, lint, note),
      `${reps.length} occurrence(s)${dens(reps.length)}` + (rules.length ? ` (${rules.join(", ")})` : "") + `.${tail}`,
      reps.map((x) => `${x.file}:${x.line} ${x.message}`)]);
  }
  return rows;
}
