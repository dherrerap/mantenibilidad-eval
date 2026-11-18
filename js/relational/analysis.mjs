// analysis.mjs — What the data_model criteria measure over a normalized schema. Port of relational_analysis.py (same functions,
// same results; checked call by call against the Python version on tests/golden/relational.json).
//
//   C1  tablesWithoutPk, implicitRelations, polymorphicReferences
//   C2  repeatingGroups, denormalizedCopies                (suggestion only)
//   C3  constraintStats
//   C4  indexAnalysis, sqlFilters
//   C5  typeConflicts (decides: not met), duplicateTables (suggestion)
//   C6  parseEr, loadEr, compareEr                         (Mermaid erDiagram vs. the schema)
import fs from "node:fs";
import path from "node:path";
import { F, cmp, finditer, readText, get, match, pyRound, search, setEq, sorted, splitlines, str, truthy } from "../lib/py.mjs";
import { IDENT, QNAME, fold, identName, qnameTable, singular, tableForModel, typeFamily } from "./schema.mjs";

const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const sortStr = (xs) => sorted(xs);

// ───────────────────────── live catalog (pg_schema.js output) ─────────────────────────
/** pg_schema.js dumps the real database in (almost) the normalized shape; this adds type families and sources. */
export function fromCatalog(cat, R) {
  const ignore = new Set(get(R, "ignore_tables", []).map(fold));
  const tables = {};
  for (const [name, t] of Object.entries(get(cat, "tables") || {})) {
    if (ignore.has(fold(name))) continue;
    const cols = {};
    for (const [c, d] of Object.entries(t.columns)) cols[c] = { ...d, family: typeFamily(get(d, "type"), R), source: "database" };
    tables[name] = { name, columns: cols, primary_key: [...(truthy(get(t, "primary_key")) ? t.primary_key : [])], primary_key_source: "database",
      foreign_keys: get(t, "foreign_keys", []).map((f) => ({ ...f, source: "database" })),
      unique: get(t, "unique", []).map((u) => ({ ...u, source: "database" })),
      checks: get(t, "checks", []).map((c) => ({ ...c, source: "database" })),
      indexes: get(t, "indexes", []).map((i) => ({ ...i, source: "database" })),
      source: "database", file: null, rows: get(t, "rows") };
  }
  return { tables, sources: { database: Object.keys(tables).length }, model_tables: {}, unparsed: [],
    server_version: get(cat, "server_version"), database: get(cat, "database") };
}

// ───────────────────────── Mermaid erDiagram ─────────────────────────
const ER_ATTR = String.raw`^\s*([^\s"]+)\s+([^\s"]+)((?:\s+(?:PK|FK|UK)\s*,?)*)\s*(?:"([^"]*)")?\s*$`;
// Mermaid's lexer accepts every cardinality token on either side (`o|` and `|o` are both zero-or-one…)
const ER_CARD = String.raw`(\|\||\|o|o\||\}\||\|\{|\}o|o\{)`;
const ER_REL = String.raw`^\s*("[^"]+"|[^\s"]+)\s+` + ER_CARD + String.raw`(--|\.\.)` + ER_CARD + String.raw`\s+("[^"]+"|[^\s"]+)\s*(?::\s*(.*))?$`;
const ER_OPEN = String.raw`^\s*("[^"]+"|[^\s"{\[]+)\s*(?:\[\s*"?([^\]"]+)"?\s*\])?\s*\{\s*$`;
const ER_START = String.raw`^\s*erDiagram\b`;

const unq = (x) => x.trim().replace(/^"+|"+$/g, "");

/** Entities (attributes with type and PK/FK/UK markers) and relationships of the Mermaid `erDiagram` blocks in `text`. */
export function parseEr(text) {
  let blocks = finditer("```\\s*mermaid\\s*\\n(.*?)```", text, "si").map((m) => m[1]);
  blocks = blocks.filter((b) => search(ER_START, b, "m"));
  if (!blocks.length) {
    const m = search(ER_START, text, "m");
    if (m) blocks = [text.slice(m.index)];
  }
  const ents = {}, rels = [];
  const ent = (e) => { if (!has(ents, e)) ents[e] = { name: e, alias: null, attributes: [] }; };
  for (const blk of blocks) {
    let cur = null;
    for (const line of splitlines(blk)) {
      const ln = line.split("%%")[0].trimEnd();
      if (!ln.trim() || match(ER_START, ln)) continue;
      if (cur !== null) {
        if (ln.trim() === "}") { cur = null; continue; }
        const m = match(ER_ATTR, ln, "i");
        if (m) {
          const keys = finditer("PK|FK|UK", m[3] || "", "i").map((k) => k[0].toUpperCase());
          ents[cur].attributes.push({ type: m[1], name: m[2], keys, comment: m[4] ?? null });
        }
        continue;
      }
      let m = match(ER_OPEN, ln);
      if (m) {
        cur = unq(m[1]);
        ent(cur);
        if (m[2]) ents[cur].alias = m[2].trim();
        continue;
      }
      m = match(ER_REL, ln);
      if (m) {
        const a = unq(m[1]), b = unq(m[5]);
        ent(a); ent(b);
        rels.push({ left: a, right: b, left_card: m[2], right_card: m[4], identifying: m[3] === "--", label: unq(m[6] || "") });
      }
    }
  }
  return { entities: ents, relationships: rels };
}

// Python sorts paths case-insensitively on Windows (WindowsPath) and pathlib's glob is case-insensitive there
const WIN = process.platform === "win32";
const sortNames = (names) => sorted(names, (n) => (WIN ? n.toLowerCase() : n));
const listDir = (d) => { try { return sortNames(fs.readdirSync(d)); } catch { return []; } };
const isDir = (p) => { try { return fs.statSync(p).isDirectory(); } catch { return false; } };
const isFile = (p) => { try { return fs.statSync(p).isFile(); } catch { return false; } };

/** docs/<label> of the app, matched case-insensitively (docs/R2, docs/r2), or null. */
export function versionDir(app, label, docs = "docs") {
  const base = path.join(app, docs);
  if (!isDir(base)) return null;
  const n = listDir(base).find((x) => isDir(path.join(base, x)) && x.toLowerCase() === str(label).toLowerCase());
  return n ? path.join(base, n) : null;
}

/** The file `name` directly inside `folder`, matched case-insensitively, or null. */
export function findFile(folder, name) {
  if (!folder || !isDir(folder)) return null;
  const n = listDir(folder).find((x) => isFile(path.join(folder, x)) && x.toLowerCase() === name.toLowerCase());
  return n ? path.join(folder, n) : null;
}

const posixParent = (p) => { const d = path.posix.dirname(p); return d === "." ? "" : d; };
const posixJoin = (...xs) => xs.filter(Boolean).join("/");

/** The places loadEr looks in, for messages: 'docs/R2/entity-relationship-model.md, docs/entity-relationship-model.md'. */
export function erSearched(R) {
  const want = R.er_model_path, parent = posixParent(want), name = path.posix.basename(want);
  return [...get(R, "doc_versions", []).map((label) => posixJoin(parent, label, name)), want].join(", ");
}

/** Reads the entity-relationship model and parses its erDiagram (latest versioned set first, then relational.er_model_path). */
export function loadEr(app, R) {
  const want = R.er_model_path, parent = posixParent(want), name = path.posix.basename(want);
  let found = null, version = null;
  for (const label of get(R, "doc_versions", [])) {
    const d = versionDir(app, label, parent || ".");
    if (!d) continue;
    let cand = findFile(d, name);
    if (cand === null) {  // e.g. docs/R2/data-model.md: any document of the set that carries the diagram
      const mds = listDir(d).filter((x) => (WIN ? /\.md$/i : /\.md$/).test(x) && isFile(path.join(d, x)));
      const hit = mds.find((x) => Object.keys(parseEr(readText(path.join(d, x))).entities).length);
      cand = hit ? path.join(d, hit) : null;
    }
    if (cand) { found = cand; version = label; break; }
  }
  found = found || findFile(path.join(app, parent), name);
  if (!found) return { file: null, found: false, diagram: false, entities: {}, relationships: [], text: "", version: null };
  const text = readText(found);
  const parsed = parseEr(text);
  return { file: path.relative(app, found).split(path.sep).join("/"), found: true, diagram: Object.keys(parsed.entities).length > 0, ...parsed, text, version };
}

export const normEntity = (name) => fold(singular(str(name)));

/** [many, optional] of a Mermaid cardinality token. */
export const cardFlags = (tok) => [tok.includes("{") || tok.includes("}"), tok.includes("o")];

const pairKey = (a, b) => [...new Set([a, b])].sort().join("\u0001");

/** Compares the declared ER (parseEr output) with the schema: entities, attributes, primary and foreign keys and relationships. */
export function compareEr(er, schema, R) {
  const T = schema.tables;
  const tn = new Map();
  for (const n of Object.keys(T)) tn.set(normEntity(n), n);
  const ignore = new Set(get(R, "ignore_tables", []).map(fold));
  const entities = Object.fromEntries(Object.entries(er.entities).filter(([, e]) => !ignore.has(fold(e.name))));
  const kept = new Set([...Object.values(entities).map((e) => fold(e.name)), ...Object.values(entities).filter((e) => truthy(get(e, "alias"))).map((e) => fold(e.alias))]);
  const rels = get(er, "relationships", []).filter((r) => ![fold(r.left), fold(r.right)].some((x) => ignore.has(x) && !kept.has(x)));
  const en = new Map();
  for (const [name, e] of Object.entries(entities)) {
    en.set(normEntity(name), e);
    if (truthy(get(e, "alias")) && !en.has(normEntity(e.alias))) en.set(normEntity(e.alias), e);
  }
  const out = {
    entities_missing_in_er: sortStr([...tn].filter(([k]) => !en.has(k)).map(([, n]) => n)),
    entities_not_in_schema: sortStr(Object.values(entities).filter((e) => !tn.has(normEntity(e.name)) && !(truthy(get(e, "alias")) && tn.has(normEntity(e.alias)))).map((e) => e.name)),
    attributes_missing_in_er: {}, attributes_not_in_schema: {}, pk_mismatch: {}, fk_mismatch: {},
    relationships_missing_in_er: [], relationships_not_in_schema: [], cardinality_mismatch: [], type_differences: [], optionality_differences: [],
  };
  for (const [k, tname] of tn) {
    const e = en.get(k);
    if (!e) continue;
    const t = T[tname];
    const scols = new Map(Object.keys(t.columns).map((c) => [fold(c), c]));
    const eattrs = new Map(e.attributes.map((a) => [fold(a.name), a]));
    const miss = sortStr([...scols].filter(([f]) => !eattrs.has(f)).map(([, c]) => c));
    const extra = sortStr([...eattrs].filter(([f]) => !scols.has(f)).map(([, a]) => a.name));
    if (miss.length) out.attributes_missing_in_er[tname] = miss;
    if (extra.length) out.attributes_not_in_schema[tname] = extra;
    const epk = [...eattrs].filter(([, a]) => a.keys.includes("PK")).map(([f]) => f);
    if (!setEq(t.primary_key.map(fold), epk)) out.pk_mismatch[tname] = { schema: sortStr(t.primary_key), er: sortStr(epk.map((f) => eattrs.get(f).name)) };
    const sfkCols = t.foreign_keys.flatMap((fk) => fk.columns);
    const efk = [...eattrs].filter(([, a]) => a.keys.includes("FK")).map(([f]) => f);
    if (!setEq(sfkCols.map(fold), efk)) out.fk_mismatch[tname] = { schema: sortStr(sfkCols), er: sortStr(efk.map((f) => eattrs.get(f).name)) };
    for (const [f, a] of eattrs) {
      const c = scols.has(f) ? get(t.columns, scols.get(f)) : null;
      const fam = typeFamily(a.type, R);
      if (c && fam && truthy(get(c, "family")) && fam !== c.family) out.type_differences.push(`${tname}.${c.name}: ER ${a.type} vs schema ${c.type}`);
    }
  }
  // relationships: entity pairs compared without direction; then the many/one side of the line that matches each foreign key
  const erPairs = new Map();
  for (const r of rels) {
    const key = pairKey(normEntity(r.left), normEntity(r.right));
    if (!erPairs.has(key)) erPairs.set(key, []);
    erPairs.get(key).push(r);
  }
  const schemaPairs = new Map();
  for (const [tname, t] of Object.entries(T)) {
    for (const fk of t.foreign_keys) {
      const parent = Object.keys(T).find((n) => fold(n) === fold(fk.ref_table)) ?? fk.ref_table;
      const key = pairKey(normEntity(tname), normEntity(parent));
      if (!schemaPairs.has(key)) schemaPairs.set(key, []);
      schemaPairs.get(key).push([tname, parent, fk]);
    }
  }
  for (const [key, fks] of schemaPairs) {
    const [child, parent, fk] = fks[0];
    const label = `${child} → ${parent}`;
    if (!erPairs.has(key)) { out.relationships_missing_in_er.push(label); continue; }
    const t = T[child];
    const fkset = fk.columns.map(fold);
    const oneToOne = [...t.unique.map((u) => u.columns), t.primary_key].some((cols) => setEq(cols.map(fold), fkset));
    const nullable = fk.columns.some((c) => truthy(get(get(t.columns, c, {}), "nullable")));
    let okShape = false;
    for (const r of erPairs.get(key)) {
      if (normEntity(child) === normEntity(parent)) {  // self reference: any line with a many side counts
        okShape = okShape || [r.left_card, r.right_card].some((x) => cardFlags(x)[0]);
        continue;
      }
      const sides = new Map([[normEntity(r.left), cardFlags(r.left_card)], [normEntity(r.right), cardFlags(r.right_card)]]);
      const [cm] = sides.get(normEntity(child));
      const [pm, po] = sides.get(normEntity(parent));
      if (!pm && cm !== oneToOne) {
        okShape = true;
        if (po !== nullable)
          out.optionality_differences.push(`${label}: parent side is ${po ? "optional" : "mandatory"} in the ER but the foreign key is ${nullable ? "nullable" : "NOT NULL"}`);
      }
    }
    if (!okShape) out.cardinality_mismatch.push(`${label}: the ER does not show ${oneToOne ? "one-to-one" : "many-to-one"} with ${parent} on the 'one' side`);
  }
  for (const [key, rs] of erPairs) if (!schemaPairs.has(key)) out.relationships_not_in_schema.push(`${rs[0].left} — ${rs[0].right}`);
  out.relationships_missing_in_er = sortStr(out.relationships_missing_in_er);
  out.relationships_not_in_schema = sortStr(out.relationships_not_in_schema);
  const counted = ["entities_missing_in_er", "entities_not_in_schema", "attributes_missing_in_er", "attributes_not_in_schema", "pk_mismatch", "fk_mismatch",
    "relationships_missing_in_er", "relationships_not_in_schema", "cardinality_mismatch"];
  out.mismatches = counted.reduce((n, k) => n + (Array.isArray(out[k]) ? out[k].length : Object.keys(out[k]).length), 0);
  out.matches = out.mismatches === 0;
  return out;
}

// ───────────────────────── C1 – C5 ─────────────────────────
export const tablesWithoutPk = (schema) => sortStr(Object.entries(schema.tables).filter(([, t]) => !t.primary_key.length).map(([n]) => n));

const POLY_SUFFIXES = ["", "_type", "_table", "_kind", "_model", "_name"];

/** `<x>_id` columns of a polymorphic association: the table also has a discriminator (`<x>`, `<x>_type`…) and no table is named `<x>`. */
export function polymorphicReferences(schema) {
  const names = new Set([...Object.keys(schema.tables).map((n) => fold(singular(n))), ...Object.keys(schema.tables).map(fold)]);
  const out = [];
  for (const [n, t] of Object.entries(schema.tables)) {
    const cols = new Set(Object.keys(t.columns).map(fold));
    for (const c of Object.keys(t.columns)) {
      const m = /^(.+?)(?:_id|Id|ID)$/.exec(c);
      if (!m || names.has(fold(m[1]))) continue;
      if (POLY_SUFFIXES.some((s) => cols.has(fold(m[1] + s)))) out.push(`${n}.${c}`);
    }
  }
  return sortStr(out);
}

/** Columns named like a reference (`*_id`, `*Id`) that are neither a foreign key, the table's own single-column primary key nor
 *  the id of a polymorphic association. */
export function implicitRelations(schema, R) {
  const pats = R.implicit_fk_patterns;
  const poly = new Set(polymorphicReferences(schema));
  const out = [];
  for (const [n, t] of Object.entries(schema.tables)) {
    const fkcols = new Set(t.foreign_keys.flatMap((fk) => fk.columns));
    const own = t.primary_key.length === 1 ? t.primary_key[0] : null;
    for (const c of Object.keys(t.columns))
      if (!fkcols.has(c) && c !== own && !poly.has(`${n}.${c}`) && pats.some((p) => search(p, c))) out.push(`${n}.${c}`);
  }
  return sortStr(out);
}

/** Column lists that are unique: primary key, unique constraints and unique indexes without a predicate. */
export function uniqueSets(t) {
  const sets = t.primary_key.length ? [t.primary_key] : [];
  sets.push(...t.unique.map((u) => u.columns));
  sets.push(...t.indexes.filter((i) => truthy(get(i, "unique")) && !truthy(get(i, "predicate"))).map((i) => i.columns));
  return sets;
}

/** Share of the non-primary-key columns that declare some constraint (NOT NULL, UNIQUE, CHECK or FOREIGN KEY), and type problems. */
export function constraintStats(schema, R) {
  let total = 0, constrained = 0;
  const floatMoney = [], naturalKeys = [];
  const nat = new Set(R.natural_key_names.map((x) => x.toLowerCase()));
  for (const [n, t] of Object.entries(schema.tables)) {
    const uniq = new Set(uniqueSets(t).filter((s) => s.length === 1).flat());
    const checked = new Set(t.checks.flatMap((ck) => ck.columns));
    const fks = new Set(t.foreign_keys.flatMap((fk) => fk.columns));
    for (const [name, c] of Object.entries(t.columns)) {
      if (t.primary_key.includes(name)) continue;
      total += 1;
      if (!truthy(c.nullable) || uniq.has(name) || checked.has(name) || fks.has(name)) constrained += 1;
      if (get(c, "family") === "float" && search(R.money_name_pattern, name, "i")) floatMoney.push(`${n}.${name} (${str(c.type)})`);
      if (nat.has(name.toLowerCase()) && !uniq.has(name)) naturalKeys.push(`${n}.${name}`);
    }
  }
  return { total, constrained, pct: F(total ? (100.0 * constrained) / total : 0.0), float_money: sortStr(floatMoney), natural_keys_without_unique: sortStr(naturalKeys) };
}

/** Column lists an index can serve, in index order: primary key, unique constraints and indexes. */
export function leadingColumns(t) {
  const lists = t.primary_key.length ? [t.primary_key] : [];
  lists.push(...t.unique.map((u) => u.columns), ...t.indexes.map((i) => i.columns));
  return lists.filter((l) => l.length);
}

/** Attribute name used in a query (`userId`) -> the column of the table (`user_id`); null if the table has no such column. */
export function resolveColumn(t, field) {
  if (has(t.columns, field)) return field;
  const f = fold(field);
  return Object.keys(t.columns).find((c) => fold(c) === f) ?? null;
}

const SQL_STOP = String.raw`\b(?:GROUP\s+BY|ORDER\s+BY|LIMIT|OFFSET|RETURNING|HAVING|UNION|FOR\s+UPDATE|WINDOW)\b`;
const SQL_NOT_ALIAS = new Set(["where", "join", "on", "set", "left", "right", "inner", "outer", "cross", "full", "using", "group", "order", "limit", "values", "natural", "returning"]);
const SQL_OPS = String.raw`(?:=|<>|!=|<=|>=|<|>|\bnot\s+in\b|\bin\b|\blike\b|\bilike\b|\bis\b|\bbetween\b)`;

/** Table and WHERE columns of the raw SELECT/UPDATE/DELETE strings in the code (best effort): [{file, line, table, fields}]. */
export function sqlFilters(sqlStrings, schema) {
  const T = schema.tables;
  const byFold = new Map(Object.keys(T).map((n) => [fold(n), n]));
  const out = [];
  for (const s of sqlStrings) {
    const text = s.text.replace(/\s+/g, " ");
    if (match(String.raw`\s*(create|alter|drop|insert)\b`, text, "i")) continue;
    const aliases = new Map();
    for (const m of finditer(String.raw`\b(?:FROM|JOIN|UPDATE|DELETE\s+FROM)\s+(${QNAME})(?:\s+(?:AS\s+)?(${IDENT}))?`, text, "i")) {
      const tn = byFold.get(fold(qnameTable(m[1])));
      if (!tn) continue;
      aliases.set(tn.toLowerCase(), tn);
      if (m[2] && !SQL_NOT_ALIAS.has(identName(m[2]).toLowerCase())) aliases.set(identName(m[2]).toLowerCase(), tn);
    }
    const mw = search(String.raw`\bWHERE\b(.*?)(?:` + SQL_STOP + "|$)", text, "i");
    if (!aliases.size || !mw) continue;
    const per = new Map();
    for (const m of finditer(String.raw`(?:(${IDENT})\.)?(${IDENT})\s*${SQL_OPS}`, mw[1], "i")) {
      const q = m[1] ? identName(m[1]).toLowerCase() : null, col = identName(m[2]);
      let tn = q ? aliases.get(q) ?? null : null;
      if (!tn && !q) {
        const cands = [...new Set(aliases.values())].filter((x) => resolveColumn(T[x], col));
        tn = cands.length === 1 ? cands[0] : null;
      }
      const c = tn ? resolveColumn(T[tn], col) : null;
      if (c) {
        if (!per.has(tn)) per.set(tn, new Set());
        per.get(tn).add(c);
      }
    }
    for (const [tn, cols] of per) out.push({ file: s.file, line: s.line, table: tn, fields: sortStr([...cols]), call: "sql" });
  }
  return out;
}

/** FK columns without an index, and query filters (Sequelize `where` and raw SQL) that no index can serve. */
export function indexAnalysis(schema, queries, maxUnindexedPct, modelTables = null) {
  const T = schema.tables;
  const fkUnindexed = [];
  for (const [n, t] of Object.entries(T)) {
    const lead = leadingColumns(t);
    for (const fk of t.foreign_keys) {
      const need = fk.columns.map(fold);
      if (!lead.some((l) => setEq(l.slice(0, fk.columns.length).map(fold), need))) fkUnindexed.push(`${n}(${fk.columns.join(", ")})`);
    }
  }
  const shapes = new Set(), unindexed = [];
  let dynamic = 0, unresolved = 0;
  for (const q of queries) {
    const tn = get(q, "table") || tableForModel(get(q, "model", ""), { tables: T, model_tables: modelTables || {} });
    dynamic += truthy(get(q, "dynamic")) ? 1 : 0;
    if (!tn || !has(T, tn)) { unresolved += 1; continue; }
    const t = T[tn];
    const cols = sortStr([...new Set(get(q, "fields", []).map((f) => resolveColumn(t, f)).filter((c) => c))]);
    if (!cols.length) continue;
    if (t.primary_key.length === 1 && setEq(cols.map(fold), [fold(t.primary_key[0])])) continue;  // filters by the primary key only
    const shape = JSON.stringify([tn, cols]);
    if (shapes.has(shape)) continue;
    shapes.add(shape);
    const firsts = new Set(leadingColumns(t).map((l) => fold(l[0])));
    if (!cols.some((c) => firsts.has(fold(c)))) unindexed.push(`${tn}.where(${cols.join(", ")})` + (truthy(get(q, "file")) ? ` in ${q.file}:${str(get(q, "line"))}` : ""));
  }
  const pctUn = shapes.size ? (100.0 * unindexed.length) / shapes.size : 0.0;
  const redundant = [];
  for (const [n, t] of Object.entries(T)) {
    const ixs = t.indexes.map((i) => [i.name, i.columns, get(i, "unique")]);
    for (const [a, ka, ua] of ixs)
      for (const [b, kb] of ixs)
        if (a !== b && !truthy(ua) && ka.length < kb.length && ka.every((x, i) => kb[i] === x)) redundant.push(`${n}: ${a} is a prefix of ${b}`);
  }
  const unused = Object.entries(T).flatMap(([n, t]) => t.indexes.filter((i) => get(i, "scans") === 0 && !truthy(get(i, "unique"))).map((i) => `${n}.${i.name}`));
  return { fks_without_index: sortStr(fkUnindexed), unindexed_queries: unindexed, distinct_queries: shapes.size, unindexed_queries_pct: F(pyRound(pctUn, 1)),
    unresolved_queries: unresolved, dynamic_queries: dynamic, redundant, unused, ok: !fkUnindexed.length && pctUn <= maxUnindexedPct };
}

export function repeatingGroups(schema) {
  const out = [];
  for (const [n, t] of Object.entries(schema.tables)) {
    const stems = new Map();
    for (const c of Object.keys(t.columns)) {
      const m = /^(.*?)_?(\d+)$/.exec(c);
      if (m && m[1]) {
        if (!stems.has(m[1])) stems.set(m[1], []);
        stems.get(m[1]).push(c);
      }
    }
    for (const v of stems.values()) if (v.length >= 2) out.push(`${n}: ${v.join(", ")}`);
  }
  return out;
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Columns that copy a column of the referenced table (`product_name` next to `product_id`) and whether the README or the ER
 *  document justifies them (a word from rubric.json within 200 characters of the column name). */
export function denormalizedCopies(schema, text, R) {
  const words = R.denormalization_words.map((w) => w.toLowerCase());
  const skip = new Set(R.boilerplate_columns.map(fold));
  const low = text.toLowerCase();
  const out = [];
  for (const [n, t] of Object.entries(schema.tables)) {
    for (const fk of t.foreign_keys) {
      const p = get(schema.tables, fk.ref_table);
      if (!p) continue;
      for (const pc of Object.keys(p.columns)) {
        if (skip.has(fold(pc)) || p.primary_key.includes(pc)) continue;
        const col = Object.keys(t.columns).find((c) => fold(c) === fold(`${singular(fk.ref_table)}_${pc}`));
        if (col) {
          const near = finditer(escapeRe(col.toLowerCase()), low).map((m) => low.slice(Math.max(0, m.index - 200), m.index + m[0].length + 200));
          out.push({ copy: `${n}.${col}`, of: `${fk.ref_table}.${pc}`, justified: near.some((x) => words.some((w) => x.includes(w))) });
        }
      }
    }
  }
  return out;
}

/** Same column name (ignoring case and `_`) with different type families in different tables. */
export function typeConflicts(schema) {
  const by = new Map();
  for (const [n, t] of Object.entries(schema.tables)) {
    for (const c of Object.values(t.columns)) {
      const fam = get(c, "family") || str(c.type).replace(/\(.*/s, "");
      const k = fold(c.name);
      if (!by.has(k)) by.set(k, new Map());
      const d = by.get(k);
      if (!d.has(fam)) d.set(fam, []);
      d.get(fam).push(`${n}.${c.name}`);
    }
  }
  return sorted([...by]).filter(([, d]) => d.size > 1).map(([k, d]) => `${k}: ` + [...d].map(([fam, v]) => `${str(fam)} (${v.slice(0, 3).join(", ")})`).join(" vs "));
}

export function duplicateTables(schema) {
  const sig = new Map();
  for (const [n, t] of Object.entries(schema.tables)) {
    if (Object.keys(t.columns).length >= 3) {
      const key = JSON.stringify(sorted(Object.values(t.columns).map((c) => [fold(c.name), get(c, "family")])));
      if (!sig.has(key)) sig.set(key, []);
      sig.get(key).push(n);
    }
  }
  return [...sig.values()].filter((v) => v.length > 1).map((v) => v.join(" = "));
}

export { cmp };
