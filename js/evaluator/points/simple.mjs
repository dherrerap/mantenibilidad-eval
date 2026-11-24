// Decision points Configuration, Observability, Tests, Hierarchies and Contracts. Port of evaluator/points/{configuration,
// observability,tests,hierarchies,contracts}.py.
import { F, fixed, get, or, pyRound, search, sorted, str, truthy } from "../../lib/py.mjs";
import { RUBRIC, appFs, fstr } from "../common.mjs";
import { C, applyManual } from "../criteria.mjs";
import { decideCount, usable } from "../helpers.mjs";
import { fullRoutes, isHealthRoute, routeMatch } from "../routes.mjs";

const keys = (o) => (Array.isArray(o) ? o : Object.keys(o || {}));
const depsOf = (m) => new Set(m.packages.packages.flatMap((p) => [...Object.keys(p.dependencies), ...Object.keys(p.devDependencies)]));
const inter = (set, list) => sorted(list.filter((x, i) => set.has(x) && list.indexOf(x) === i));

// ───────────────────────── Configuration ─────────────────────────
export function evalConfiguration(m, manual, opts) {
  const T = RUBRIC.thresholds.configuration, a = m.ast;
  const lits = a.networkLiterals.filter((x) => !(truthy(T.cwe1051_ignore_env_fallback) && truthy(x.envFallback)));
  const kloc = a.files.filter((f) => !f.test).reduce((s, f) => s + f.loc, 0) / 1000.0;
  const [lint, note] = usable(m);
  const flagged = {};
  for (const x of get(lint || {}, "dup_strings", [])) flagged[`${or(x.literal, "«?»").slice(1, -1)} (${x.file})`] = x.times;
  const excess = Object.values(flagged).reduce((s, t) => s + (or(t, 0) - 1), 0);
  const dens = kloc ? excess / kloc : 0.0;
  const n = Object.keys(flagged).length;
  const c2 = decideCount(n, lint, note);
  const s1192 = c2 === null ? `pending (${str(note)})` : `auto (eslint-plugin-sonarjs ${str(get(lint.versions, "eslint-plugin-sonarjs"))})`;
  const cfgMod = keys(a.envFiles).some((f) => /(^|\/)config(\.|\/)/.test(f));
  const crit = {
    C1: C(lits.length === 0, "0 network literals (URL/IP/port) (CWE-1051)", lits.length),
    C2: C(c2, `0 literals of ≥10 characters repeated ≥${str(T.dup_literal_threshold)} times in a file (SonarQube S1192)`,
      n ? flagged : lint === null ? null : 0, s1192),
    C3: C(or(m.env_example, cfgMod), "External configuration (.env.example or configuration module)", { env_example: m.env_example, config_module: cfgMod }),
  };
  applyManual("configuration", crit, manual);
  const ev = lits.slice(0, 6).map((x) => `${x.file}:${x.line} ${str(x.value)}` + (truthy(x.envFallback) ? " [env fallback]" : ""));
  return [crit, { network_literals: lits.length, dup_per_kloc: F(dens), kloc: F(kloc), s1192_literals: flagged }, ev,
    `${lits.length} network literals; ` + (truthy(lint) ? `${n} duplicated literal(s) per S1192 (${fixed(dens, 1)} extra repetitions/KLOC, informational)` : "S1192 not measured")
      + (note ? `. ${note}.` : "."), null];
}

// ───────────────────────── Observability ─────────────────────────
export function evalObservability(m, manual, opts) {
  const T = RUBRIC.thresholds.observability, cb = m.ast.catchBlocks;
  const deps = depsOf(m);
  const logger = inter(deps, RUBRIC.libs_logger), metrics = inter(deps, RUBRIC.libs_metrics);
  const mw = m.ast.errorMiddleware;
  let centralLogs = false;
  for (const e of mw) {
    try {
      centralLogs = centralLogs || /\b(console|logger|log)\.\w+/.test(appFs.readText(m.app, e.file));  // \b: "catalog.find" is not a log call
    } catch { /* unreadable file: as in Python, it does not count */ }
  }
  const reqlog = inter(deps, RUBRIC.libs_request_logger);
  const evs = m.ast.functions.filter((f) => truthy(get(f, "event")));
  const evOk = evs.filter((f) => truthy(f.logs) || reqlog.length);
  const A = cb.logging + (centralLogs ? cb.delegating : 0) + evOk.length, B = cb.total + evs.length;
  const X = B ? A / B : null;
  const c1 = X !== null ? X >= T.X_min : truthy(mw) && centralLogs;
  const cons = m.ast.consoleCalls.length;
  const health = fullRoutes(m.ast).filter((r) => isHealthRoute(r.full_path));
  const crit = {
    C1: C(c1, "X ≥ 0.80 of critical events logged (errors: catch blocks; authentication and writes: functions that log, or a request logger)",
      X === null ? null : F(pyRound(X, 2)), "auto (proxy)"),
    C2: C(logger.length > 0 && cons === 0, "Structured logger and no console.* in production", { logger, console_calls: cons }),
    C3: C(mw.length > 0, "Centralized error handling", mw.length),
    C4: C(health.length > 0 || metrics.length > 0, "Health check, metrics or traces", { routes: health.map((r) => r.full_path), libs: metrics }),
  };
  applyManual("observability", crit, manual);
  const ev = [...m.ast.consoleCalls.slice(0, 5).map((c) => `${c.file}:${c.line} console.*`), ...cb.silent.slice(0, 3).map((c) => `catch without logging ${c.file}:${c.line}`),
    ...evs.filter((f) => !evOk.includes(f)).map((f) => `${f.event} without logging ${f.file}:${f.line} ${f.name}`).slice(0, 4)];
  return [crit, { catch_total: cb.total, console_calls: cons, auth_write_events: evs.length, logged_events: evOk.length, request_logger: reqlog }, ev,
    `${cb.total} catch blocks (${cb.logging} log, ${cb.delegating} delegate, ${cb.silent.length} silent); ${evs.length} authentication/write functions (${evOk.length} logged${reqlog.length ? ", request logger" : ""}); ${cons} console.*; ${mw.length} error middleware(s).`, null];
}

// ───────────────────────── Tests ─────────────────────────
function mutationMeasure(m) {
  const mu = get(m, "mutation");
  if (!truthy(mu)) return [{}, [], ""];
  if (!truthy(get(mu, "ok"))) return [{ mutation_score: null }, [], ` Mutation score not measured (${str(get(mu, "error"))}).`];
  const st = mu.statuses;
  const det = get(st, "Killed", 0) + get(st, "Timeout", 0), und = get(st, "Survived", 0) + get(st, "NoCoverage", 0);
  const surv = mu.packages.filter((p) => truthy(get(p, "ok"))).flatMap((p) => get(p, "survivors", []));
  return [{ mutation_score: mu.score, mutants: Object.values(st).reduce((s, x) => s + x, 0), mutants_detected: det, mutants_undetected: und },
    surv.slice(0, 3).map((s) => `surviving mutant: ${s}`),
    ` Mutation score (${str(mu.tool)}): ${fstr(mu.score)}% (${det} of ${det + und} valid mutants detected by the tests; informational).`];
}

export function evalTests(m, manual, opts) {
  const T = RUBRIC.thresholds.tests, a = m.ast;
  const bad = a.switchesMissingDefault.length + a.fallthrough.length + a.labeledJumps.length;
  const ts = m.tests_static, tr = m.tests_run, exist = ts.test_cases > 0;
  const c2 = !exist ? false : !truthy(tr.executed) || !truthy(get(tr, "ran_any")) ? null : tr.all_passed;
  let lines = null, branches = null, noBranches = false;
  if (truthy(tr.executed) && truthy(get(tr, "lines_total"))) {
    lines = (100.0 * tr.lines_cov) / tr.lines_total;
    branches = truthy(tr.br_total) ? (100.0 * tr.br_cov) / tr.br_total : null;
    noBranches = !truthy(tr.br_total);
  }
  const covOk = (v, thr) => (!exist ? false : v === null ? null : v >= thr);
  const src = (v) => (v !== null || !exist ? "auto" : "pending (--run-tests)");
  const crit = {
    C1: C(bad === 0, "0 CWE-478/484/1075 violations", { switch_without_default: a.switchesMissingDefault.length, fallthrough: a.fallthrough.length, labeled_jumps: a.labeledJumps.length }),
    C2: C(c2, "Tests exist and pass", `${ts.test_cases} cases in ${ts.test_files.length} files`, c2 !== null ? "auto" : "pending (--run-tests)"),
    C3: C(covOk(lines, T.lines_min), "Line coverage ≥ 70%", lines === null ? null : F(pyRound(lines, 1)), src(lines)),
    C4: C(covOk(branches, T.branches_min), "Branch coverage ≥ 50%", branches === null ? null : F(pyRound(branches, 1)), src(branches)),
  };
  if (noBranches && exist) delete crit.C4;  // not applicable: the level is decided by C1–C3
  applyManual("tests", crit, manual);
  const ev = [...a.switchesMissingDefault.slice(0, 3).map((x) => `switch without default ${x.file}:${x.line}`), ...ts.test_files.slice(0, 3)];
  const met = { cases: ts.test_cases, line_coverage: lines === null ? null : F(lines), branch_coverage: branches === null ? null : F(branches) };
  const finding = `${ts.test_cases} test cases; line coverage ${lines === null ? "n/a" : fixed(lines, 0) + "%"}, branches ` +
    `${noBranches ? "not measured by the coverage report (C4 not applicable)" : branches === null ? "n/a" : fixed(branches, 0) + "%"}.`;
  const [mmet, mev, mtxt] = mutationMeasure(m);
  Object.assign(met, mmet);
  return [crit, met, [...ev, ...mev], finding + mtxt, null];
}

// ───────────────────────── Hierarchies ─────────────────────────
const lastName = (x) => or(x, "").split(".").at(-1);

export function unhealthyInheritanceGraph(m) {
  const cls = m.ast.classes;
  const byname = Object.fromEntries(cls.map((c) => [c.name, c]));
  const deps = new Map();
  for (const mod of get(m.graph, "modules", [])) deps.set(mod.source, new Set(mod.deps.filter((d) => d.local).map((d) => d.to)));
  const found = [];
  for (const child of cls) {
    const parent = get(byname, lastName(child.extends));
    if (!parent || parent.file === child.file) continue;
    if ((deps.get(parent.file) ?? new Set()).has(child.file)) found.push(`parent ${parent.name} (${parent.file}) imports its child ${child.name} (${child.file})`);
    for (const [client, ds] of deps)
      if (client !== parent.file && client !== child.file && ds.has(parent.file) && ds.has(child.file)) found.push(`${client} imports parent ${parent.name} and child ${child.name}`);
  }
  return found;
}

export function evalHierarchies(m, manual, opts) {
  const T = RUBRIC.thresholds.hierarchies, cls = m.ast.classes;
  const byname = Object.fromEntries(cls.map((c) => [c.name, c]));
  const depth = (c, seen = []) => {
    if (!truthy(c.extends)) return 0;
    const parent = get(byname, c.extends.split(".").at(-1));
    return 1 + (parent && !seen.includes(parent.name) ? depth(parent, [...seen, c.name]) : 0);
  };
  const kids = {};
  for (const c of cls) {
    const parent = lastName(c.extends);
    if (Object.prototype.hasOwnProperty.call(byname, parent)) kids[parent] = (kids[parent] ?? 0) + 1;
  }
  const deep = cls.filter((c) => depth(c) > T.depth_max);
  const wide = Object.entries(kids).filter(([, v]) => v > T.children_max).map(([k]) => k);
  let uih = get(or(get(manual, "dv8"), {}), "unhealthy_inheritance");
  const own = cls.some((c) => Object.prototype.hasOwnProperty.call(byname, lastName(c.extends)));
  if (!own) {  // no class extends another class of the application: there is no hierarchy to evaluate, which is not "Meets"
    const what = cls.length ? `${cls.length} classes, none extends another class of the application` : "no classes";
    return [{}, { classes: cls.length, applicable: false }, [], `Not applicable: ${what}; there is no inheritance hierarchy to evaluate.`, null];
  }
  let uihSrc = !cls.length ? "auto (no classes)" : uih !== null ? "dv8" : "pending (DV8)";
  if (cls.length && uih === null && own && truthy(get(m.graph, "modules"))) { uih = unhealthyInheritanceGraph(m).length; uihSrc = "auto (DV8 rules on the graph)"; }
  else if (cls.length && uih === null && !own) { uih = 0; uihSrc = "auto (no own hierarchy)"; }
  const c3 = !cls.length ? true : uih === null ? null : uih === 0;
  const crit = {
    C1: C(!deep.length, "0 classes with depth > 7", deep.length),
    C2: C(!wide.length, "0 classes with > 10 direct children", wide.length),
    C3: C(c3, "0 Unhealthy Inheritance patterns (DV8)", uih, uihSrc),
  };
  applyManual("hierarchies", crit, manual);
  return [crit, { classes: cls.length }, deep.slice(0, 5).map((c) => `${c.file}: ${c.name}`), `${cls.length} classes; ${deep.length} too deep; ${wide.length} with too many children.`, null];
}

// ───────────────────────── Contracts ─────────────────────────
function runtimeConformance(m) {
  const rc = get(m, "conformance");
  if (!truthy(rc)) return [{}, [], ""];
  if (!truthy(get(rc, "ok"))) return [{ runtime_conformance: null }, [], ` Runtime conformance not measured (${str(get(rc, "error"))}).`];
  const met = { runtime_conformance_pct: rc.conformance_pct, runtime_calls: rc.calls, undocumented_routes: rc.undocumented_routes.length,
    undocumented_status: rc.undocumented_status.length, invalid_responses: rc.invalid_responses.length };
  const ev = [...rc.invalid_responses.slice(0, 2), ...rc.undocumented_status.slice(0, 1), ...rc.undocumented_routes.slice(0, 1)].map((x) => `at run time: ${str(x)}`);
  const txt = ` At run time (Prism, ${str(rc.calls)} calls of the acceptance suite): ${fstr(rc.conformance_pct)}% of the responses match the contract; ` +
    `${rc.undocumented_routes.length} undocumented route(s), ${rc.undocumented_status.length} undocumented status code(s), ` +
    `${rc.invalid_responses.length} response(s) off the schema (informational).`;
  return [met, ev, txt];
}

export function evalContracts(m, manual, opts) {
  const T = RUBRIC.thresholds.contracts, ct = m.contract, routes = fullRoutes(m.ast);
  const has = ct.files.length > 0;
  let cov = null;
  if (has && routes.length) cov = (100.0 * routes.filter((r) => routeMatch(ct.paths, r, get(ct, "bases"))).length) / routes.length;
  const unresolved = routes.filter((r) => !r.resolved).length;
  const vlibs = inter(depsOf(m), RUBRIC.libs_validation);
  const writes = routes.filter((r) => ["POST", "PUT", "PATCH"].includes(r.method));
  const validated = writes.filter((r) => truthy(get(r, "validated"))).length;
  const valPct = writes.length ? (100.0 * validated) / writes.length : null;
  const valTxt = valPct === null ? "no write routes" : `${validated}/${writes.length} = ${fixed(valPct, 0)}%`;
  const vf = new Set(get(m.ast, "validationFields", []).flatMap((v) => v.fields));
  const props = new Set(or(get(ct, "properties"), []));
  const outside = sorted([...vf].filter((x) => !props.has(x)));
  const fieldsOk = !(vf.size && props.size) ? null : !outside.length;
  let c4;
  if (!has) c4 = false;
  else if (valPct === null) c4 = true;
  else if (!vlibs.length) c4 = false;
  else c4 = valPct >= T.coverage_min && fieldsOk !== false;
  const c4Value = { libs: vlibs, validated_write_routes: valTxt, validated_fields_outside_contract: props.size ? outside : "no properties in the contract" };
  const se = ct.spectral_errors;
  const crit = {
    C1: C(has, "Machine-readable contract (OpenAPI/…)", ct.files),
    C2: C(has && se !== null ? se === 0 : !has ? false : null, "0 Spectral errors (spectral:oas)", se),
    C3: C(cov !== null ? cov >= T.coverage_min : false, "Contract covers ≥ 90% of routes", cov === null ? null : `${fixed(cov, 0)}% of ${routes.length} routes`),
    C4: C(c4, "Input validation consistent with the contract (write routes validated ≥ 90% and validated fields present in the contract)", c4Value),
  };
  applyManual("contracts", crit, manual);
  const met = { implemented_routes: routes.length, coverage_pct: cov === null ? null : F(cov), routes_with_unresolved_prefix: unresolved,
    contract_endpoints_over_implemented: routes.length && ct.paths.length ? F(ct.paths.length / routes.length) : null };
  let ev = [...ct.files.slice(0, 3), ...routes.slice(0, 4).map((r) => `${r.method} ${r.full_path}`)];
  const finding = `${has ? "Contract: " + ct.files.join(", ") : "No machine-readable contract"}; ${routes.length} implemented routes` +
    (unresolved ? ` (${unresolved} with a mount prefix that could not be resolved).` : ".");
  const [rmet, rev, rtxt] = runtimeConformance(m);
  Object.assign(met, rmet); ev = [...ev, ...rev];
  return [crit, met, ev, finding + rtxt, null];
}
