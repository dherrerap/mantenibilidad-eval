// scoring.mjs — Protocol step 9: the 11 points with their level, severity and confidence, the maintainability profile per
// subcharacteristic, the judge's inputs, and the ranked risk list. Port of evaluator/scoring.py and evaluator/points/__init__.py.
import { F, get, pyRound, search, sorted, str, truthy } from "../lib/py.mjs";
import { artifactFindings } from "./artifacts.mjs";
import { ascmmProfile } from "./ascmm.mjs";
import { RUBRIC, pointWeight } from "./common.mjs";
import { levelFrom, pdict } from "./criteria.mjs";
import { evalDataModel, evalTechnologies } from "./points/dependencies.mjs";
import { evalConfiguration, evalContracts, evalHierarchies, evalObservability, evalTests } from "./points/simple.mjs";
import { evalCohesion, evalCoupling, evalCyclomatic, evalLayers } from "./points/structure.mjs";

export const EVALUATORS = { layers: evalLayers, cyclomatic: evalCyclomatic, cohesion: evalCohesion, hierarchies: evalHierarchies, technologies: evalTechnologies,
  coupling: evalCoupling, data_model: evalDataModel, contracts: evalContracts, observability: evalObservability, tests: evalTests, configuration: evalConfiguration };
/** Criteria that alone make a point fail (`must_criteria` in rubric.json). Read at call time, like the rest of the rubric. */
export const mustCriteria = (pid) => (pid.startsWith("_") ? [] : get(get(RUBRIC, "must_criteria", {}), pid, []));

// What the README usually says about each point (declared-vs-implemented gaps); whole words only
const DECLARED_PATTERNS = { layers: String.raw`\blayer(s|ed)?\b|\bcontrollers?\b|\bservices? layer\b|\brepositor(y|ies)\b`,
  cyclomatic: null, cohesion: String.raw`\bcohesi(on|ve)\b|\bresponsibilit(y|ies)\b|single[- ]responsibility`,
  hierarchies: null, technologies: String.raw`\bversions?\b|\bstack\b|\breact\b|\bexpress\b`,
  coupling: String.raw`\bcoupl(ed|ing)\b|dependency injection|\bdecoupl`,
  data_model: String.raw`\bschema\b|data model|entity[- ]relationship|\bindex(es)? on\b|\bindexes\b`,
  contracts: String.raw`\bopenapi\b|\bswagger\b|\bapi contract\b|\bapi spec(ification)?\b`,
  observability: String.raw`\blogg(ing|er)\b|\bwinston\b|\bpino\b|health[- ]?check|\bobservab|\bmetrics\b`,
  tests: String.raw`\b(unit|integration|automated) tests?\b|\bjest\b|\bvitest\b|node --test|\bcoverage\b|npm (run )?test`,
  configuration: String.raw`\.env\b|environment variables?|\bconfiguration\b` };

export function evaluatePoints(m, manual, opts) {
  const pts = [];
  const sc = RUBRIC.level_score;
  for (const [pid, fn] of Object.entries(EVALUATORS)) {
    const arts = (get(m, "artifacts") || []).filter((a) => a.feeds.includes(pid));
    const missCore = arts.filter((a) => a.level === "core" && !a.present);
    const missComp = arts.filter((a) => a.level === "complementary" && !a.present);
    const evaluable = !missCore.length;
    let crits, met, ev, finding, forced;
    if (evaluable) [crits, met, ev, finding, forced] = fn(m, manual, opts);
    else {
      [crits, met, ev, forced] = [{}, {}, [], [null, null, null]];
      finding = "Not evaluable: missing core artifact(s): " + missCore.map((a) => a.name).join(", ") + ".";
    }
    const applicable = !(met && met.applicable === false);  // the point has nothing to evaluate in this app (e.g. no inheritance)
    let level, lo, hi;
    if (!applicable) level = lo = hi = null;
    else if (forced && (forced[0] || forced[1] !== forced[2])) [level, lo, hi] = forced;  // forced, or a pending range
    else if (Object.keys(crits).length) [level, lo, hi] = levelFrom(crits, mustCriteria(pid));
    else level = lo = hi = null;
    const pend = Object.entries(crits).filter(([, v]) => v.ok === null).map(([k]) => k);
    const readme = get(m, "readme");
    const declared = truthy(readme) && DECLARED_PATTERNS[pid] ? Boolean(search(DECLARED_PATTERNS[pid], readme, "i")) : false;
    let gap = null;
    if (DECLARED_PATTERNS[pid]) {
      if (level === "Fails" && declared) gap = "declared but not supported by the structure";
      else if (level === "Meets" && !declared) gap = "implemented but not declared";
    }
    const artFindings = missComp.map((a) => ({ artifact: a.id, name: a.name, severity: get(a, "absence") === "high_finding" ? "Critical" : "Marginal" }));
    let severity = level ? get(RUBRIC.level_severity, level) : lo !== hi ? "Undetermined" : null;
    if (!evaluable) severity = "Not evaluable";
    else if (!applicable) severity = "Not applicable";
    else if (artFindings.some((f) => f.severity === "Critical")) severity = "Critical";  // IEEE 1028, 6.8.3
    const confidence = !evaluable || !applicable ? "n/a" : !missComp.length ? "high" : missComp.length === 1 ? "medium" : "low";
    pts.push({ ...pdict(pid), level, level_min: lo, level_max: hi, evaluable, ...(applicable ? {} : { applicable: false }), confidence, missing_artifacts: [...missCore, ...missComp].map((a) => a.id),
      artifact_findings: artFindings, complete: level !== null || !applicable, pending_criteria: pend, severity, finding, metrics: met, criteria: crits, evidence: ev,
      weaknesses: Object.entries(crits).filter(([, v]) => v.ok === false).map(([k, v]) => `${k}: ${str(v.desc)} → ${str(v.value)}`),
      declared_in_readme: declared, declarative_gap: gap, score_min: lo ? sc[lo] : null, score_max: hi ? sc[hi] : null });
  }
  return pts;
}

export function profile(points) {
  const W = RUBRIC.subcharacteristic_weights, subs = {};
  for (const s of Object.keys(W)) {
    const ps = points.filter((p) => p.subcharacteristics.includes(s) && p.score_min !== null);
    const tot = points.filter((p) => p.subcharacteristics.includes(s));
    // weighted mean of the evaluable points (`point_weights`); with no weights set every point weighs 1 and this is the plain mean
    const tw = ps.reduce((a, p) => a + pointWeight(p.id), 0);
    const lo = ps.length ? ps.reduce((a, p) => a + pointWeight(p.id) * Number(p.score_min), 0) / tw : null;
    const hi = ps.length ? ps.reduce((a, p) => a + pointWeight(p.id) * Number(p.score_max), 0) / tw : null;
    subs[s] = { weight: W[s], points: tot.map((p) => p.id), evaluable_points: ps.length,
      min: lo === null ? null : F(pyRound(100 * lo, 1)), max: hi === null ? null : F(pyRound(100 * hi, 1)) };
  }
  const ok = Object.values(subs).every((v) => v.min !== null);
  const wsum = (k) => Object.values(subs).filter((v) => v[k] !== null).reduce((a, v) => a + Number(v.weight) * Number(v[k]), 0);
  return { subcharacteristics: subs, maintainability_min: ok ? F(pyRound(wsum("min"), 1)) : null, maintainability_max: ok ? F(pyRound(wsum("max"), 1)) : null,
    complete: points.every((p) => p.complete) };
}

/** Points and profile with the judge's decisions; if there are any, adds the range that results without them (`without_judge`). */
export function evaluateProfile(m, manual, opts) {
  const pts = evaluatePoints(m, manual, opts), prof = profile(pts);
  prof.not_evaluable = pts.filter((p) => !p.evaluable).map((p) => p.id);
  prof.artifact_findings = artifactFindings(m);
  prof.ascmm = ascmmProfile(m, pts);
  if (truthy(get(manual, "_judge"))) {
    const without = profile(evaluatePoints(m, Object.fromEntries(Object.entries(manual).filter(([k]) => k !== "_judge")), opts));
    prof.without_judge = { min: without.maintainability_min, max: without.maintainability_max, complete: without.complete };
    prof.judge_criteria = sorted(pts.flatMap((p) => Object.entries(p.criteria).filter(([, v]) => str(v.source).startsWith("judge")).map(([c]) => `${p.id}.${c}`)));
    prof.judge_model = get(get(manual._judge, "meta", {}), "judge_model");
    prof.judge_audit = get(manual._judge, "audit", []);
  }
  return [pts, prof];
}

const TRAFFIC = { Meets: "🟢", Partial: "🟡", Fails: "🔴" };
export const trafficLight = (point) => get(TRAFFIC, point.level, "⚪");

/** Condensed risk view: every point with its traffic light and the overall-score points it puts at stake, highest risk first. */
export function riskSummary(points) {
  const W = RUBRIC.subcharacteristic_weights;
  // total point weight of each subcharacteristic: with no `point_weights` it is the number of points that feed it
  const total = Object.fromEntries(Object.keys(W).map((s) => [s, points.filter((p) => p.subcharacteristics.includes(s)).reduce((a, p) => a + pointWeight(p.id), 0)]));
  const rows = [];
  for (const p of points) {
    if (p.score_min === null) continue;
    const impact = 100 * p.subcharacteristics.filter((s) => Object.hasOwn(W, s)).reduce((a, s) => a + (Number(W[s]) * pointWeight(p.id)) / total[s], 0);
    rows.push({ id: p.id, name: p.name, light: trafficLight(p), level: p.level, level_min: p.level_min, level_max: p.level_max, pending: p.pending_criteria,
      impact: F(pyRound(impact, 1)), at_stake_min: F(pyRound((1 - Number(p.score_max)) * impact, 1)), at_stake_max: F(pyRound((1 - Number(p.score_min)) * impact, 1)) });
  }
  return sorted(rows, (r) => [-Number(r.at_stake_max), -Number(r.at_stake_min), r.id]);
}
