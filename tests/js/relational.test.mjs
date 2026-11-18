// Differential test of the JavaScript port of the relational modules: every call recorded from the Python version
// (tests/golden/record_relational.py) must give exactly the same JSON, key order included.
//   node --test tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as rs from "../../js/relational/schema.mjs";
import * as ra from "../../js/relational/analysis.mjs";
import { pyRound, repr } from "../../js/lib/py.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const FN = {
  "relational_schema.ident_name": rs.identName, "relational_schema.qname_table": rs.qnameTable, "relational_schema.fold": rs.fold,
  "relational_schema.snake": rs.snake, "relational_schema.singular": rs.singular, "relational_schema.plural": rs.plural,
  "relational_schema.clean_and_split": rs.cleanAndSplit, "relational_schema.mask": rs.mask, "relational_schema.split_top": rs.splitTop,
  "relational_schema.match_paren": rs.matchParen, "relational_schema.col_list": rs.colList, "relational_schema.type_family": rs.typeFamily,
  "relational_schema.sequelize_type": rs.sequelizeType, "relational_schema.secondary_store": rs.secondaryStore,
  "relational_schema.path_tokens": rs.pathTokens, "relational_schema.table_for_model": rs.tableForModel,
  "relational_schema.extract": rs.extract, "relational_schema.summary": rs.summary,
  "relational_analysis.from_catalog": ra.fromCatalog, "relational_analysis.parse_er": ra.parseEr, "relational_analysis.er_searched": ra.erSearched,
  "relational_analysis.norm_entity": ra.normEntity, "relational_analysis.card_flags": ra.cardFlags, "relational_analysis.compare_er": ra.compareEr,
  "relational_analysis.tables_without_pk": ra.tablesWithoutPk, "relational_analysis.polymorphic_references": ra.polymorphicReferences,
  "relational_analysis.implicit_relations": ra.implicitRelations, "relational_analysis.unique_sets": ra.uniqueSets,
  "relational_analysis.constraint_stats": ra.constraintStats, "relational_analysis.leading_columns": ra.leadingColumns,
  "relational_analysis.resolve_column": ra.resolveColumn, "relational_analysis.sql_filters": ra.sqlFilters,
  "relational_analysis.index_analysis": ra.indexAnalysis, "relational_analysis.repeating_groups": ra.repeatingGroups,
  "relational_analysis.denormalized_copies": ra.denormalizedCopies, "relational_analysis.type_conflicts": ra.typeConflicts,
  "relational_analysis.duplicate_tables": ra.duplicateTables,
  // recorded with a repository-relative path
  "relational_analysis.load_er": (app, R) => ra.loadEr(path.join(ROOT, app), R),
};
// Python keyword arguments, by position
const KW = { "relational_schema.extract": [], "relational_analysis.index_analysis": ["model_tables"], "relational_schema.type_family": [] };

/** Deep equality that also requires the same key order (Python dicts are ordered, and so are the reports built from them). */
function sameJson(a, b, where = "$") {
  if (Array.isArray(a) || Array.isArray(b)) {
    assert.ok(Array.isArray(a) && Array.isArray(b), `${where}: array vs non-array`);
    assert.equal(a.length, b.length, `${where}: length ${a.length} vs ${b.length}`);
    a.forEach((x, i) => sameJson(x, b[i], `${where}[${i}]`));
  } else if (a && typeof a === "object" && b && typeof b === "object") {
    assert.deepEqual(Object.keys(a), Object.keys(b), `${where}: keys`);
    for (const k of Object.keys(a)) sameJson(a[k], b[k], `${where}.${k}`);
  } else assert.equal(a, b, `${where}`);
}

function run(file) {
  const g = JSON.parse(fs.readFileSync(file, "utf8"));
  const fix = (v) => (v && typeof v === "object" && !Array.isArray(v) && v.$R ? g.R : Array.isArray(v) ? v.map(fix) : v);
  for (const [i, c] of g.calls.entries()) {
    const fn = FN[c.fn];
    test(`${path.basename(file)} #${i} ${c.fn}`, () => {
      assert.ok(fn, `no port of ${c.fn}`);
      const args = c.args.map(fix);
      for (const k of KW[c.fn] || []) if (c.kwargs && k in c.kwargs) args.push(fix(c.kwargs[k]));
      // round-trip through JSON, as the Python result was: undefined -> missing, tuples -> arrays
      const got = JSON.parse(JSON.stringify(fn(...structuredClone(args)) ?? null));
      sameJson(got, c.result);
    });
  }
}

run(path.join(ROOT, "tests", "golden", "relational.json"));
const local = path.join(ROOT, "results", "_golden", "relational-apps.json");
if (fs.existsSync(local)) run(local);  // the generated apps, when this machine has them (apps/ is not versioned)

test("pyRound rounds half to even on the exact binary value, like Python", () => {
  for (const [x, n, want] of [[0.125, 2, 0.12], [0.375, 2, 0.38], [2.675, 2, 2.67], [2.5, 0, 2], [3.5, 0, 4], [33.33333333333333, 1, 33.3], [-0.125, 2, -0.12], [12.25, 1, 12.2]])
    assert.equal(pyRound(x, n), want, `round(${x}, ${n})`);
});

test("repr matches Python for the values the evaluator prints", () => {
  assert.equal(repr(null), "None"); assert.equal(repr(true), "True"); assert.equal(repr("it's"), '"it\'s"');
  assert.equal(repr({ a: [1, "x"] }), "{'a': [1, 'x']}"); assert.equal(repr(1e-5), "1e-05");
});
