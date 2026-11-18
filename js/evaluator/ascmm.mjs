// ascmm.mjs — The Automated Source Code Maintainability Measure (ISO/IEC 5055:2021) of a run: occurrences of every weakness the
// framework detects and their density per KLOC of production code. Port of evaluator/ascmm.py (the profile; the Markdown comes
// with the outputs).
import { F, get, isDict, pyRound, str, truthy } from "../lib/py.mjs";
import { RUBRIC } from "./common.mjs";
import { ascmmIndicators } from "./supplementary.mjs";

const isInt = (v) => typeof v === "number" && Number.isInteger(v);  // Python int: a PyFloat (an object) or a bool is not one

/** Integer count kept in a criterion's value: an int, a dict entry (`key`), the size of a dict or list; null if not measured. */
function critValue(pt, cid, key = null) {
  const c = get(get(pt, "criteria") || {}, cid);
  if (!c) return null;
  const v = get(c, "value");
  if (key !== null) return isDict(v) ? get(v, key) : null;
  if (typeof v === "boolean") return null;
  if (isInt(v)) return v;
  if (isDict(v)) return Object.keys(v).length;
  if (Array.isArray(v)) return v.length;
  return null;
}

function metValue(pt, key) {
  const v = get(get(pt, "metrics") || {}, key);
  return isInt(v) ? v : null;
}

const SCORED = [
  ["CWE-478", "Missing Default Case in Multiple Condition Expression", "switch", "tests", (p) => critValue(p, "C1", "switch_without_default")],
  ["CWE-484", "Omitted Break Statement in Switch", "case", "tests", (p) => critValue(p, "C1", "fallthrough")],
  ["CWE-561", "Dead Code", "file", "coupling", (p) => critValue(p, "C5")],
  ["CWE-1041", "Use of Redundant Code", "clone", "cyclomatic", (p) => metValue(p, "clones")],
  ["CWE-1047", "Modules with Circular Dependencies", "cycle", "coupling", (p) => critValue(p, "C1")],
  ["CWE-1048", "Invokable Control Element with Large Number of Outward Calls", "function", "cohesion", (p) => metValue(p, "functions_fanout_above")],
  ["CWE-1051", "Initialization with Hard-Coded Network Resource Configuration Data", "literal", "configuration", (p) => critValue(p, "C1")],
  ["CWE-1052", "Excessive Use of Hard-Coded Literals in Initialization", "literal", "configuration", (p) => critValue(p, "C2")],
  ["CWE-1054", "Invocation of a Control Element at an Unnecessarily Deep Horizontal Layer", "dependency", "layers", (p) => metValue(p, "violations")],
  ["CWE-1062", "Parent Class with References to Child Class", "pattern", "hierarchies", (p) => critValue(p, "C3")],
  ["CWE-1074", "Class with Excessively Deep Inheritance", "class", "hierarchies", (p) => critValue(p, "C1")],
  ["CWE-1075", "Unconditional Control Flow Transfer outside of Switch Block", "jump", "tests", (p) => critValue(p, "C1", "labeled_jumps")],
  ["CWE-1080", "Source Code File with Excessive Number of Lines of Code", "file", "cohesion", (p) => critValue(p, "C4")],
  ["CWE-1086", "Class with Excessive Number of Child Classes", "class", "hierarchies", (p) => critValue(p, "C2")],
  ["CWE-1121", "Excessive McCabe Cyclomatic Complexity", "function", "cyclomatic", (p) => metValue(p, "functions_cc_above_threshold")],
];

const perKloc = (n, kloc) => (n === null || n === undefined || !kloc ? null : F(pyRound(n / kloc, 3)));

export function ascmmProfile(m, points) {
  const kloc = pyRound(m.ast.files.filter((f) => !f.test).reduce((s, f) => s + f.loc, 0) / 1000.0, 3);
  const pts = Object.fromEntries(points.map((p) => [p.id, p]));
  const rows = [];
  for (const [cwe, name, unit, pid, fn] of SCORED) {
    const pt = get(pts, pid) || {};
    const n = get(pt, "evaluable", true) ? fn(pt) : null;
    rows.push({ cwe, name, unit, point: pid, scored: true, count: n ?? null, per_kloc: perKloc(n, kloc) });
  }
  for (const r of ascmmIndicators(m)) {
    const i = r[2].indexOf(" ");
    const cwe = i < 0 ? r[2] : r[2].slice(0, i), name = i < 0 ? "" : r[2].slice(i + 1);
    rows.push({ cwe, name, unit: cwe === "CWE-1064" || cwe === "CWE-1085" ? "function" : "occurrence", point: null, scored: false, count: r[3], per_kloc: perKloc(r[3], kloc) });
  }
  const total = (rs) => {
    const n = rs.filter((r) => r.count !== null).reduce((s, r) => s + r.count, 0);
    const missing = rs.filter((r) => r.count === null).map((r) => r.cwe);
    return { occurrences: n, per_kloc: perKloc(n, kloc), complete: !missing.length, not_measured: missing };
  };
  return { kloc: F(kloc), size_basis: "KLOC of production code (ISO/IEC 5055 Annex C.1 uses AFP)", weaknesses: rows,
    scored: total(rows.filter((r) => r.scored)), all: total(rows) };
}

const geq = (t) => (t.complete ? "" : "≥ ");

export const fmtTotal = (t) => `${geq(t)}${t.occurrences} (${geq(t)}${t.per_kloc !== null ? str(t.per_kloc) : "n/a"}/KLOC)`;

export const COLUMNS = ["kloc", "ascmm_scored", "ascmm_scored_per_kloc", "ascmm_all", "ascmm_all_per_kloc", "ascmm_complete"];

/** Values of COLUMNS for comparison.csv; nulls for an older profile without ASCMM. */
export function ascmmColumns(prof) {
  const a = get(prof, "ascmm");
  if (!truthy(a)) return COLUMNS.map(() => null);
  return [a.kloc, a.scored.occurrences, a.scored.per_kloc, a.all.occurrences, a.all.per_kloc, a.all.complete];
}

/** Section of comparison.md and report.md: runs = [[run_id, profile]]. */
export function ascmmComparisonMd(runs) {
  const rows = runs.filter(([, p]) => truthy(get(p, "ascmm"))).map(([r, p]) => [r, p.ascmm]);
  if (!rows.length) return [];
  const L = ["## ISO/IEC 5055 weaknesses (ASCMM)", "",
    "Occurrences of the detected weaknesses and their density per KLOC of production code: compare densities, since the applications " +
    "differ in size (ISO/IEC 5055 Annex C.1). ≥ = some weakness not measured, so the total is a lower bound.", "",
    "| Run | KLOC | Scored | Scored / KLOC | All detected | All / KLOC |", "|---|---|---|---|---|---|"];
  for (const [r, a] of rows)
    L.push(`| ${r} | ${str(a.kloc)} | ${geq(a.scored)}${a.scored.occurrences} | ${geq(a.scored)}${str(a.scored.per_kloc)} | ${geq(a.all)}${a.all.occurrences} | ${geq(a.all)}${str(a.all.per_kloc)} |`);
  const cwes = rows[0][1].weaknesses.map((w) => w.cwe);
  L.push("", "Per weakness (occurrences / per KLOC):", "", "| CWE | " + rows.map(([r]) => r).join(" | ") + " |", "|---|" + "---|".repeat(rows.length));
  for (const c of cwes) {
    const cells = rows.map(([, a]) => {
      const w = a.weaknesses.find((x) => x.cwe === c);
      return !w || w.count === null ? "n/a" : `${str(w.count)} / ${str(w.per_kloc)}`;
    });
    L.push(`| ${c} | ` + cells.join(" | ") + " |");
  }
  return [...L, ""];
}

/** Section of profile.md. */
export function ascmmMarkdown(a) {
  const cov = RUBRIC.backing._coverage_ascmm;
  const L = ["## ISO/IEC 5055 weaknesses (ASCMM)", "",
    `Occurrences of every weakness the framework detects (${cov.scored.length} scored, ${cov.informational.length} informational, ` +
    `${cov.not_detected.length} of the ${str(cov.applicable)} applicable not detected), and their density per KLOC of production code ` +
    `(${str(a.kloc)} KLOC; ISO/IEC 5055 Annex C.1 normalizes by AFP, which is not computed). n/a = not measured.`, "",
    "| CWE | Weakness | Occurrences | Per KLOC | Counted as | Scored in |", "|---|---|---|---|---|---|"];
  for (const r of a.weaknesses)
    L.push(`| ${r.cwe} | ${r.name} | ${r.count === null ? "n/a" : str(r.count)} | ${r.per_kloc === null ? "n/a" : str(r.per_kloc)} | ${r.unit} | ${r.point || "informational"} |`);
  L.push("", `**ASCMM, scored weaknesses:** ${fmtTotal(a.scored)} · **all detected:** ${fmtTotal(a.all)}` + (a.all.not_measured.length ? `. Not measured: ${a.all.not_measured.join(", ")}.` : "."), "");
  return L;
}
