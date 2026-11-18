// Decision points Technologies and Data model. Port of evaluator/points/{technologies,data_model}.py.
import { F, fixed, format, get, isDict, or, pyRound, search, sorted, str, truthy } from "../../lib/py.mjs";
import * as ra from "../../relational/analysis.mjs";
import * as rs from "../../relational/schema.mjs";
import { RUBRIC, appFs, fstr, pct } from "../common.mjs";
import { C, applyManual, heur } from "../criteria.mjs";
import { coerceVersion } from "../helpers.mjs";

// ───────────────────────── Technologies ─────────────────────────
const DESC = { C1: "No deprecated packages", C2: "Runtime and framework supported", C3: "≤ 20% of direct dependencies with an outdated major version", C4: "0 high/critical vulnerabilities" };

export function major(v) {
  const c = coerceVersion(v);
  return c ? Number.parseInt(c.split(".")[0], 10) : null;
}

export function libyearSummary(items) {
  const out = {};
  for (const [group, dev] of [["dependencies", false], ["devDependencies", true]]) {
    const xs = items.filter((i) => i.dev === dev && get(i, "libyear") !== null);
    const sum = xs.reduce((s, i) => s + Number(i.libyear), 0);
    out[group] = { total: xs.length ? F(pyRound(sum, 2)) : 0, mean: xs.length ? F(pyRound(sum / xs.length, 2)) : null, measured: xs.length,
      oldest: sorted(xs, (i) => -Number(i.libyear)).slice(0, 5).filter((i) => i.libyear > 0).map((i) => `${i.pkg} ${str(i.resolved)} (${fstr(i.libyear)} y behind ${str(i.latest)})`) };
  }
  return out;
}

function unsupportedRuntimes(m, S, resolved) {
  const out = [];
  const inList = (lst, v) => (Array.isArray(lst) ? lst.some((x) => Number(x) === v) : false);
  for (const pkg of m.packages.packages) {
    const d = get(pkg, "dir", ".");
    for (const [name, spec] of Object.entries({ ...pkg.dependencies, ...pkg.devDependencies })) {
      const v = or(resolved.get(JSON.stringify([d, name])), spec);
      if (Object.prototype.hasOwnProperty.call(S, name) && major(v) !== null && !inList(S[name], major(v))) out.push(`${name} ${str(v)}`);
    }
    const eng = get(pkg.engines, "node");
    if (truthy(eng) && major(eng) !== null && !inList(S.node, major(eng))) out.push(`node ${str(eng)}`);
  }
  const images = or(get(m, "postgres_images"), []);
  out.push(...images.filter((i) => i.major !== null && !inList(S.postgresql, Number(i.major))).map((i) => `postgresql ${str(i.major)} (${i.image} in ${i.file})`));
  return [out, images.filter((i) => i.major === null).map((i) => `${i.image} in ${i.file}`)];
}

/** An npm item of an older metrics.json (declared range only) in the current shape. */
const normalized = (i) => (Object.prototype.hasOwnProperty.call(i, "resolved") ? i
  : { ...i, resolved: or(get(i, "base"), coerceVersion(get(i, "spec"))), resolved_source: "range lower bound", dev: false, dir: get(i, "dir", "."), libyear: null });

function vulnerabilityCount(pk) {
  const vu = or(get(pk, "vulnerabilities"), {});
  if (truthy(get(vu, "ok"))) return [vu.high + vu.critical, "auto (OSV)", null];
  const au = or(get(pk, "audit"), {});
  if (!truthy(vu) && truthy(get(au, "ok"))) return [au.high + au.critical, "auto (npm audit, older evaluation: not fixed at as_of)", null];
  return [null, null, or(get(vu, "error"), "not queried")];
}

export function evalTechnologies(m, manual, opts) {
  const T = RUBRIC.thresholds.technologies, S = { ...RUBRIC.supported_runtimes, ...or(get(m, "eol"), {}) };
  const pk = m.packages, npm = pk.npm, asOf = or(get(pk, "as_of"), get(m, "as_of"));
  const eolSource = truthy(get(m, "eol")) ? `endoflife.date as of ${str(asOf)}: ` + sorted(Object.keys(m.eol)).join(", ") : "rubric.json table";
  if (!truthy(npm.ok)) {
    const crit = Object.fromEntries(Object.entries(DESC).map(([k, d]) => [k, C(null, d, null, "pending (offline)")]));
    applyManual("technologies", crit, manual);
    return [crit, {}, [], "The npm registry was not queried (offline mode or no network).", null];
  }
  const items = npm.items.map(normalized);
  const dep = items.filter((i) => truthy(i.deprecated));
  const newer = items.filter((i) => truthy(get(i, "after_as_of"))).map((i) => `${i.pkg} ${str(i.resolved)}`);
  const outdated = items.filter((i) => !truthy(get(i, "after_as_of")) && major(i.resolved) !== null && major(i.latest) !== null && major(i.resolved) < major(i.latest))
    .map((i) => `${i.pkg} ${str(i.resolved)} (latest ${str(i.latest)} as of ${str(asOf)})`);
  const po = pct(outdated.length, items.length);
  const [unsupported, unversioned] = unsupportedRuntimes(m, S, new Map(items.map((i) => [JSON.stringify([i.dir, i.pkg]), i.resolved])));
  const vu = or(get(pk, "vulnerabilities"), {});
  const [vuln, vsource, verr] = vulnerabilityCount(pk);
  const SR = RUBRIC.supported_runtimes;
  const crit = {
    C1: C(!dep.length, DESC.C1, dep.map((i) => `${i.pkg} ${str(i.resolved)}`)),
    C2: C(!unsupported.length, `Runtime, framework and PostgreSQL supported (${eolSource}; rest: rubric.json table, ${str(SR.date)}; ` +
      `postgresql/sequelize/pg unverified since ${str(SR.unverified.date)})`,
      unversioned.length ? { unsupported, postgres_image_without_version_not_checked: unversioned } : unsupported),
    C3: C(newer.length ? null : po <= T.pct_major_outdated_max, DESC.C3, `${outdated.length}/${items.length} = ${fixed(po, 1)}%`,
      newer.length ? `pending (as_of ${str(asOf)} is earlier than ${newer.length} of the app's versions)` : "auto"),
    C4: C(vuln === null ? null : vuln <= T.vuln_high_critical_max, DESC.C4 + ` (OSV, advisories published by ${str(asOf)})`, vuln,
      vuln !== null ? vsource : `pending (OSV: ${verr.slice(0, 120)})`),
  };
  applyManual("technologies", crit, manual);
  const ly = libyearSummary(items);
  const sources = sorted([...new Set(items.map((i) => i.resolved_source))]);
  const met = { direct: items.length, deprecated: dep.length, outdated: outdated.length, as_of: asOf, libyear: ly, resolved_from: sources, newer_than_as_of: newer };
  let ev = [...outdated.slice(0, 6), ...unsupported.slice(0, 4)];
  if (truthy(get(vu, "ok"))) {
    const hi = vu.items.filter((x) => ["HIGH", "CRITICAL"].includes(x.severity));
    Object.assign(met, { vulnerabilities_high_critical_production: hi.filter((x) => !truthy(x.dev)).length, vulnerabilities_unknown_severity: vu.unknown_severity,
      advisories_published_after_as_of: vu.published_after_as_of, installed_packages_queried: vu.queried });
    ev.push(...hi.slice(0, 4).map((x) => `${x.severity.toLowerCase()}: ${x.pkg} ${str(x.version)} ${x.id}` + (truthy(x.dev) ? " (dev)" : "")));
  }
  ev.push(...ly.dependencies.oldest.slice(0, 3));
  const lyd = ly.dependencies;
  let finding = `${items.length} direct dependencies (versions from: ${sources.join(", ")}; as of ${str(asOf)}): ${dep.length} deprecated, ${outdated.length} with an ` +
    `outdated major, ${vuln !== null ? str(vuln) : "?"} high/critical vulnerabilities. Dependency age: ${str(lyd.total)} libyears over ` +
    `${lyd.measured} production dependencies (mean ${str(lyd.mean)}; informational).`;
  if (newer.length) finding += ` WARNING: ${newer.length} dependencies were published after the reference date ${str(asOf)} (${newer.slice(0, 4).join(", ")}): as_of is earlier ` +
    "than the app, so their age and C3 are not measured; set --as-of to the generation date or later.";
  return [crit, met, ev, finding, null];
}

// ───────────────────────── Data model ─────────────────────────
export function mixedNamingConvention(names) {
  names = [...new Set(names)].filter((n) => n !== "_id" && n !== "__v");
  const snake = sorted(names.filter((n) => n.replace(/^_+|_+$/g, "").includes("_") && n === n.toLowerCase()));
  const camel = sorted(names.filter((n) => /[a-z][A-Z]/.test(n)));
  return snake.length && camel.length ? [`mixed naming convention (snake_case: ${snake.slice(0, 3).join(", ")}; camelCase: ${camel.slice(0, 3).join(", ")})`] : [];
}

export function evalDataModel(m, manual, opts) {
  const T = RUBRIC.thresholds.data_model, Rr = RUBRIC.relational, D = RUBRIC.points.data_model.criteria;
  const stat = m.schema;
  const pg = or(get(m, "pg"), {});
  const live = truthy(get(pg, "tables")) ? ra.fromCatalog(pg, Rr) : null;
  const S = live || stat;
  const src = live ? "auto (live database)" : "auto";
  const er = or(get(m, "er"), { found: false, diagram: false });
  const ast = m.ast;
  const noPk = ra.tablesWithoutPk(S), implicit = ra.implicitRelations(S, Rr), poly = ra.polymorphicReferences(S);
  const hasTables = Object.keys(S.tables).length > 0;
  const c1 = hasTables && !noPk.length && !implicit.length;
  const cs = ra.constraintStats(S, Rr);
  const c3 = truthy(cs.total) && cs.pct >= T.constraints_min_pct && !cs.float_money.length;
  const queries = [...get(ast, "queryFields", []), ...ra.sqlFilters(get(ast, "sqlStrings", []), S)];
  const idx = ra.indexAnalysis(S, queries, T.unindexed_queries_max_pct, get(stat, "model_tables"));
  const docsText = or(get(m, "readme"), "") + "\n" + or(get(er, "text"), "") + "\n" + appFs.designText(get(m, "app"));
  const reps = ra.repeatingGroups(S), copies = ra.denormalizedCopies(S, docsText, Rr);
  const unjustified = copies.filter((c) => !c.justified);
  const loopReads = get(ast, "queryFields", []).filter((q) => truthy(get(q, "inLoop")) && rs.tableForModel(q.model, { tables: S.tables, model_tables: get(stat, "model_tables", {}) }))
    .map((q) => `${q.file}:${q.line} ${q.model}.${q.call}`);
  const c2 = hasTables && !reps.length && !unjustified.length && !loopReads.length;
  const types = ra.typeConflicts(S);
  const conflicts = [...types, ...mixedNamingConvention(Object.values(S.tables).flatMap((t) => Object.keys(t.columns)))];
  const dups = ra.duplicateTables(S);
  const c5 = hasTables && !conflicts.length && !dups.length;
  let c6, cmp = null, c6v;
  if (!truthy(get(er, "found"))) { c6 = false; c6v = `ER model not found (looked for ${ra.erSearched(Rr)})`; }
  else if (!truthy(get(er, "diagram"))) { c6 = false; c6v = `${er.file} has no Mermaid erDiagram with entities`; }
  else {
    cmp = ra.compareEr(er, S, Rr); c6 = cmp.matches;
    c6v = c6 ? "matches" : Object.fromEntries(Object.entries(cmp).filter(([k, v]) => truthy(v) && !["matches", "mismatches", "type_differences", "optionality_differences"].includes(k)));
  }
  const crit = {
    C1: C(c1, D.C1, { tables: Object.keys(S.tables).length, without_primary_key: noPk, implicit_relations: implicit, polymorphic_references: poly }, src),
    C2: heur(C(null, D.C2, { repeating_groups: reps, denormalized_copies: copies, reads_in_loops: loopReads }, "auto", c2), opts),
    C3: C(c3, format(D.C3, T), { constrained_columns: `${cs.constrained}/${cs.total} = ${fixed(cs.pct, 0)}%`, float_money_columns: cs.float_money,
      natural_keys_without_unique: cs.natural_keys_without_unique }, src),
    C4: C(idx.ok, D.C4, Object.fromEntries(["fks_without_index", "unindexed_queries", "unindexed_queries_pct", "distinct_queries", "unresolved_queries"].map((k) => [k, idx[k]])), src),
    // inconsistent types are measured, not judged: they decide C5; the rest (naming, identical tables) stays a suggestion
    C5: types.length ? C(false, D.C5, { type_conflicts: types, conflicts, duplicate_tables: dups }, src)
      : heur(C(null, D.C5, { conflicts, duplicate_tables: dups }, "auto", c5), opts),
    C6: C(c6, D.C6, c6v, live && truthy(cmp) ? "auto (live database)" : "auto"),
  };
  applyManual("data_model", crit, manual);
  const ev = Object.entries(S.tables).slice(0, 6).map(([n, t]) => `table ${n} [${t.source}]: PK ${t.primary_key.join(", ") || "none"}; ${Object.keys(t.columns).length} columns; ${t.foreign_keys.length} FK; ${t.indexes.length} index(es)`);
  ev.push(...noPk.slice(0, 3).map((x) => `no primary key: ${x}`), ...implicit.slice(0, 3).map((x) => `implicit relation ${x}`), ...cs.float_money.slice(0, 2).map((x) => `FLOAT money ${x}`));
  ev.push(...poly.slice(0, 2).map((x) => `polymorphic reference (no FK possible) ${x}`));
  ev.push(...idx.fks_without_index.slice(0, 3).map((x) => `FK without index ${x}`), ...idx.unindexed_queries.slice(0, 3).map((x) => `unindexed filter ${x}`));
  ev.push(...loopReads.slice(0, 2).map((x) => `read in loop ${x}`), ...conflicts.slice(0, 3), ...copies.slice(0, 2).map((c) => `copy ${c.copy} of ${c.of}` + (c.justified ? "" : " (unjustified)")));
  if (isDict(c6v)) ev.push(...Object.entries(c6v).slice(0, 3).map(([k, v]) => `ER vs schema ${k}: ${str(v)}`));
  ev.push(...get(stat, "secondary_sql", []).slice(0, 2).map((x) => `not part of the main schema (secondary database): ${x.file} (${x.reason})`));
  const met = { tables: Object.keys(S.tables).length, tables_without_pk: noPk.length, implicit_relations: implicit.length, polymorphic_references: poly.length,
    constrained_columns_pct: F(pyRound(cs.pct, 1)), fks_without_index: idx.fks_without_index.length, unindexed_queries_pct: idx.unindexed_queries_pct,
    queries_analyzed: idx.distinct_queries, queries_unresolved: idx.unresolved_queries, dynamic_queries: idx.dynamic_queries, conflicts: conflicts.length,
    duplicate_tables: dups.length, er_found: truthy(get(er, "found")), er_mismatches: cmp ? cmp.mismatches : null, live_database: Boolean(live),
    redundant_indexes: idx.redundant, unused_indexes: idx.unused, schema_unparsed: get(stat, "unparsed", []).slice(0, 5), secondary_sql_skipped: get(stat, "secondary_sql", []).slice(0, 10) };
  return [crit, met, ev, `${rs.summary(S)}${live ? " (live database)" : ""}; ${noPk.length} without primary key, ${implicit.length} implicit relation(s), ` +
    `${fixed(cs.pct, 0)}% of columns constrained, ${idx.fks_without_index.length} FK without index; ER ` + (c6 ? "matches." : truthy(get(er, "diagram")) ? "does not match." : "missing."), null];
}
