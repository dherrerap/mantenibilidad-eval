// schema.mjs — Static extraction of a relational (PostgreSQL) schema from a generated application. Port of relational_schema.py:
// same sources, same order of preference and the same normalized structure (see that file's docstring). Checked against the
// Python version call by call (tests/js/relational.test.mjs on tests/golden/relational.json).
import { cmp, findall, finditer, fullmatch, get, isDict, match, or, search, sorted, str, sub, truthy } from "../lib/py.mjs";

// ───────────────────────── identifiers and text scanning ─────────────────────────
export const IDENT = String.raw`(?:"(?:[^"]|"")+"|[A-Za-z_][\w$]*)`;
export const QNAME = String.raw`${IDENT}(?:\s*\.\s*${IDENT})*`;

/** Unquoted identifiers fold to lower case (PostgreSQL); quoted ones keep their case. */
export function identName(tok) {
  tok = tok.trim();
  return tok.startsWith('"') ? tok.slice(1, -1).replaceAll('""', '"') : tok.toLowerCase();
}

/** `public.users` -> `users` (the schema is ignored: the evaluated apps use one). */
export function qnameTable(tok) {
  const parts = findall(IDENT, tok);
  return parts.length ? identName(parts[parts.length - 1]) : tok.trim();
}

export const fold = (name) => str(name).toLowerCase().replace(/[^a-z0-9]/g, "");
export const snake = (name) => str(name).replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();

export function singular(word) {
  const w = str(word);
  if (/ies$/i.test(w) && w.length > 3) return w.slice(0, -3) + "y";
  if (/(ses|xes|zes|ches|shes)$/i.test(w)) return w.slice(0, -2);
  if (w.toLowerCase().endsWith("s") && !w.toLowerCase().endsWith("ss")) return w.slice(0, -1);
  return w;
}

/** Approximation of Sequelize's inflection-based pluralization (regular English plurals only). */
export function plural(word) {
  const w = str(word);
  if (/[^aeiou]y$/i.test(w)) return w.slice(0, -1) + "ies";
  if (/(s|x|z|ch|sh)$/i.test(w)) return w + "es";
  return w + "s";
}

/** Removes comments, blanks dollar-quoted bodies and splits into statements on ';' (outside quotes and parentheses). */
export function cleanAndSplit(sql) {
  const out = [];
  let buf = [], i = 0, depth = 0;
  const n = sql.length;
  while (i < n) {
    const c = sql[i];
    if (c === "-" && sql.startsWith("--", i)) {
      const j = sql.indexOf("\n", i);
      i = j < 0 ? n : j;
      continue;
    }
    if (c === "/" && sql.startsWith("/*", i)) {
      const j = sql.indexOf("*/", i + 2);
      i = j < 0 ? n : j + 2;
      buf.push(" ");
      continue;
    }
    if (c === "'" || c === '"') {
      let j = i + 1;
      while (j < n) {
        if (sql[j] === c) {
          if (j + 1 < n && sql[j + 1] === c) { j += 2; continue; }
          break;
        }
        j += 1;
      }
      buf.push(sql.slice(i, j + 1));
      i = j + 1;
      continue;
    }
    if (c === "$") {
      const m = /^\$[A-Za-z_]*\$/.exec(sql.slice(i));
      if (m) {
        const tag = m[0];
        const j = sql.indexOf(tag, i + tag.length);
        buf.push("''");
        i = j < 0 ? n : j + tag.length;
        continue;
      }
    }
    if (c === "(") depth += 1;
    else if (c === ")") depth -= 1;
    else if (c === ";" && depth <= 0) {
      const stmt = buf.join("").trim();
      if (stmt) out.push(stmt);
      buf = []; depth = 0; i += 1;
      continue;
    }
    buf.push(c);
    i += 1;
  }
  const tail = buf.join("").trim();
  if (tail) out.push(tail);
  return out;
}

/** Replaces what is inside parentheses and quotes by `_`, so keywords can be searched at the top level only. */
export function mask(s) {
  const out = [];
  let depth = 0, q = null;
  for (let i = 0; i < s.length; i++) {  // by UTF-16 unit: the result must have the same length as `s`, its indexes are used on `s`
    const c = s[i];
    if (q) {
      out.push("_");
      if (c === q) q = null;
    } else if (c === "'" || c === '"') {
      q = c; out.push("_");
    } else if (c === "(") {
      depth += 1; out.push(depth === 1 ? "(" : "_");
    } else if (c === ")") {
      out.push(depth === 1 ? ")" : "_"); depth = Math.max(0, depth - 1);
    } else out.push(depth ? "_" : c);
  }
  return out.join("");
}

export function splitTop(s, sep = ",") {
  const parts = [];
  let cur = [], depth = 0, q = null;
  for (const c of s) {
    if (q) {
      cur.push(c);
      if (c === q) q = null;
      continue;
    }
    if (c === "'" || c === '"') q = c;
    else if (c === "(") depth += 1;
    else if (c === ")") depth -= 1;
    else if (c === sep && depth === 0) {
      parts.push(cur.join("").trim()); cur = [];
      continue;
    }
    cur.push(c);
  }
  if (cur.join("").trim()) parts.push(cur.join("").trim());
  return parts;
}

/** Index of the parenthesis that closes s[start] == '('; -1 if unbalanced. */
export function matchParen(s, start) {
  let depth = 0, q = null;
  for (let i = start; i < s.length; i++) {
    const c = s[i];
    if (q) { if (c === q) q = null; }
    else if (c === "'" || c === '"') q = c;
    else if (c === "(") depth += 1;
    else if (c === ")") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** `(a, "B", lower(c))` contents -> ['a', 'B', 'lower(c)']; plain identifiers lose quotes/ordering words. */
export function colList(txt) {
  return splitTop(txt).map((part) => {
    const m = match(String.raw`^\s*(${IDENT})\s*(?:(?:ASC|DESC)\b|NULLS\s+(?:FIRST|LAST)\b|\w+_ops\b|\s)*$`, part, "i");
    return m ? identName(m[1]) : part.trim().replace(/\s+/g, " ");
  });
}

// ───────────────────────── types ─────────────────────────
/** Family of a type (integer, numeric, float, string, boolean, date, timestamp, uuid, json, binary, enum, array) or null. */
export function typeFamily(raw, R) {
  let t = str(or(raw, "")).toLowerCase().replace(/\(.*?\)/g, "").trim();
  const known = Object.values(R.type_families).flat();
  if (t.endsWith("[]") || (t.startsWith("_") && known.includes(t.slice(1)))) return "array";  // `_int4` is how pg_catalog names int4[]
  t = t.replace(/\s+/g, " ");
  for (const [fam, names] of Object.entries(R.type_families)) if (names.includes(t)) return fam;
  return null;
}

/** `Sequelize.STRING(100)` -> `varchar(100)`; `DataTypes.DECIMAL(10, 2)` -> `numeric(10,2)`; unknown types keep their name. */
export function sequelizeType(expr, R) {
  if (isDict(expr)) expr = get(expr, "$expr", "");
  const txt = str(or(expr, "")).trim();
  const m = /^(?:[\w$]+\.)*([A-Za-z0-9_]+)(?:\((.*)\))?(?:\.\w+)*$/s.exec(txt);
  if (!m) return txt.toLowerCase();
  const name = m[1].toUpperCase(), args = (m[2] ?? "").trim();
  const base = get(R.sequelize_types, name);
  if (base === null) return name.toLowerCase();
  if (name === "ARRAY") return (args ? sequelizeType(args, R) : "unknown") + "[]";
  if (name === "ENUM") return "enum";
  if (args && /^[\d\s,]+$/.test(args)) return base.split("(")[0] + "(" + args.replace(/\s+/g, "") + ")";
  return base;
}

// ───────────────────────── schema builder ─────────────────────────
/** Accumulates tables of ONE source. */
export class Builder {
  constructor(source) {
    this.source = source;
    this.tables = {};
    this.unparsed = [];
  }

  find(name) {
    if (Object.prototype.hasOwnProperty.call(this.tables, name)) return name;
    const f = fold(name);
    return Object.keys(this.tables).find((t) => fold(t) === f) ?? null;
  }

  table(name, file = null, create = false) {
    let key = this.find(name);
    if (key === null) {
      if (!create) return null;
      key = name;
      this.tables[key] = { name: key, columns: {}, primary_key: [], primary_key_source: null, foreign_keys: [], unique: [], checks: [], indexes: [],
        source: this.source, file };
    }
    return this.tables[key];
  }

  dropTable(name) {
    const key = this.find(name);
    if (key) delete this.tables[key];
  }

  column(t, name, typ, R, nullable = true, dflt = null) {
    t.columns[name] = { name, type: typ, family: typeFamily(typ, R), nullable, default: dflt, source: this.source };
    return t.columns[name];
  }

  primaryKey(t, cols) {
    t.primary_key = [...cols];
    t.primary_key_source = this.source;
    for (const c of cols) if (Object.prototype.hasOwnProperty.call(t.columns, c)) t.columns[c].nullable = false;
  }

  foreignKey(t, cols, refTable, refCols, name = null, onDelete = null) {
    if (t.foreign_keys.some((fk) => sameList(fk.columns, cols) && fold(fk.ref_table) === fold(refTable))) return;
    t.foreign_keys.push({ columns: [...cols], ref_table: refTable, ref_columns: [...refCols], name, on_delete: onDelete, source: this.source });
  }

  unique(t, cols, name = null) {
    if (!t.unique.some((u) => sameList(u.columns, cols))) t.unique.push({ columns: [...cols], name, source: this.source });
  }

  check(t, expr, name = null, cols = null) {
    if (cols === null) {
      const toks = new Set(findall(IDENT, expr).map(identName));
      cols = Object.keys(t.columns).filter((c) => toks.has(c));
    }
    t.checks.push({ expr: expr.trim(), columns: cols, name, source: this.source });
  }

  index(t, name, cols, unique = false, method = null, predicate = null) {
    t.indexes.push({ name, columns: [...cols], unique: truthy(unique), method, predicate, source: this.source });
  }
}

const sameList = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

// ───────────────────────── 1. SQL ─────────────────────────
const COL_KW = String.raw`\b(NOT\s+NULL|NULL|DEFAULT|PRIMARY\s+KEY|UNIQUE|REFERENCES|CHECK|CONSTRAINT|GENERATED|COLLATE|COMPRESSION|STORAGE|AS)\b`;
const ACTIONS = String.raw`CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION`;
const SERIAL = { serial: "integer", serial4: "integer", bigserial: "bigint", serial8: "bigint", smallserial: "smallint", serial2: "smallint" };

function applyReferences(seg) {
  const m = match(String.raw`REFERENCES\s+(${QNAME})\s*(?:\(([^)]*)\))?`, seg, "i");
  if (!m) return null;
  const od = search(String.raw`ON\s+DELETE\s+(${ACTIONS})`, seg, "i");
  return [qnameTable(m[1]), m[2] ? colList(m[2]) : [], od ? od[1].toUpperCase().replace(/\s+/g, " ") : null];
}

function parseColumn(b, t, item, R) {
  const m = match(String.raw`\s*(${IDENT})\s+(.*)$`, item, "s");
  if (!m) {
    b.unparsed.push(`column not understood in ${t.name}: ${item.slice(0, 60)}`);
    return null;
  }
  const name = identName(m[1]), rest = m[2];
  const masked = mask(rest);
  const km = search(COL_KW, masked, "i");
  const typeTxt = (km ? rest.slice(0, km.index) : rest).trim().replace(/\s+/g, " ").replace(/\s*,\s*/g, ",");
  const [mods, mmask] = km ? [rest.slice(km.index), masked.slice(km.index)] : ["", ""];
  const base = typeTxt.toLowerCase().replace(/\(.*?\)/g, "").trim();
  let typ = typeTxt.toLowerCase();
  let nullable = true, dflt = null;
  if (has(SERIAL, base)) { nullable = false; dflt = "nextval(serial)"; }
  const starts = finditer(COL_KW, mmask, "i").map((x) => x.index);
  const segs = starts.map((a, i) => mods.slice(a, i + 1 < starts.length ? starts[i + 1] : mods.length).trim());
  let cname = null, pk = false, uniq = false, fk = null;
  const chk = [];
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i], up = seg.toUpperCase();
    if (up.startsWith("CONSTRAINT")) {
      const mm = match(String.raw`CONSTRAINT\s+(${IDENT})`, seg, "i");
      cname = mm ? identName(mm[1]) : null;
    } else if (up.startsWith("NOT NULL") || /^NOT\s+NULL/.test(up)) nullable = false;
    else if (up === "NULL") nullable = true;
    else if (up.startsWith("DEFAULT")) {
      dflt = seg.slice(7).trim();
      if (i + 1 < segs.length && segs[i + 1].toUpperCase() === "NULL") { dflt = "NULL"; i += 1; }  // DEFAULT NULL is a default, not a nullability marker
    } else if (/^PRIMARY\s+KEY/.test(up)) pk = true;
    else if (up.startsWith("UNIQUE")) uniq = true;
    else if (up.startsWith("REFERENCES")) fk = applyReferences(seg);
    else if (up.startsWith("CHECK")) {
      const p = seg.indexOf("(");
      const e = p >= 0 ? matchParen(seg, p) : -1;
      if (e > p) chk.push(seg.slice(p + 1, e));
    } else if (up.startsWith("GENERATED") || up.startsWith("AS")) {
      const two = segs.slice(i, i + 2);
      dflt = up.includes("IDENTITY") || two.some((x) => x.toUpperCase().includes("IDENTITY")) ? "identity" : "generated";
      if (two.join(" ").toUpperCase().includes("IDENTITY")) nullable = false;
    }
  }
  if (has(SERIAL, base)) typ = SERIAL[base];
  const c = b.column(t, name, typ, R, nullable, dflt);
  if (pk) b.primaryKey(t, [name]);
  if (uniq) b.unique(t, [name], cname);
  if (fk) b.foreignKey(t, [name], fk[0], fk[1], cname, fk[2]);
  for (const e of chk) b.check(t, e, cname, [name]);
  return c;
}

/** [CONSTRAINT name] PRIMARY KEY (..) | UNIQUE (..) | FOREIGN KEY (..) REFERENCES t (..) | CHECK (..) -> true if recognized. */
function parseTableConstraint(b, t, item) {
  const m = match(String.raw`\s*(?:CONSTRAINT\s+(${IDENT})\s+)?(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|EXCLUDE)\b\s*(.*)$`, item, "is");
  if (!m) return false;
  const name = m[1] ? identName(m[1]) : null;
  const kind = m[2].toUpperCase().replace(/\s+/g, " "), rest = m[3];
  if (kind === "EXCLUDE") return true;
  const p = rest.indexOf("(");
  const e = p >= 0 ? matchParen(rest, p) : -1;
  if (e < 0) {
    b.unparsed.push(`constraint not understood in ${t.name}: ${item.slice(0, 60)}`);
    return true;
  }
  const inner = rest.slice(p + 1, e), after = rest.slice(e + 1);
  if (kind === "CHECK") b.check(t, inner, name);
  else if (kind === "PRIMARY KEY") b.primaryKey(t, colList(inner));
  else if (kind === "UNIQUE") b.unique(t, colList(inner), name);
  else {
    const ref = applyReferences(after.trim());
    if (ref) b.foreignKey(t, colList(inner), ref[0], ref[1], name, ref[2]);
    else b.unparsed.push(`foreign key without REFERENCES in ${t.name}`);
  }
  return true;
}

function resetTable(t) {
  Object.assign(t, { columns: {}, primary_key: [], foreign_keys: [], unique: [], checks: [], indexes: [] });
}

function alterTable(b, t, actions, R) {
  for (const act of splitTop(actions)) {
    const a = act.trim();
    const ma = match(String.raw`ADD (?:COLUMN )?(?:IF NOT EXISTS )?(.*)$`, a, "is");
    if (ma && !match(String.raw`(CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK|EXCLUDE)\b`, ma[1], "i") && !match(String.raw`ADD (CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK)`, a, "i")) {
      parseColumn(b, t, ma[1], R);
    } else if (match(String.raw`ADD (CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK|EXCLUDE)\b`, a, "i")) {
      parseTableConstraint(b, t, a.slice(4));
    } else if (match(String.raw`DROP COLUMN (?:IF EXISTS )?(${IDENT})`, a, "i")) {
      const c = identName(match(String.raw`DROP COLUMN (?:IF EXISTS )?(${IDENT})`, a, "i")[1]);
      delete t.columns[c];
      t.foreign_keys = t.foreign_keys.filter((f) => !f.columns.includes(c));
      t.unique = t.unique.filter((u) => !u.columns.includes(c));
      t.indexes = t.indexes.filter((i) => !i.columns.includes(c));
      if (t.primary_key.includes(c)) t.primary_key = [];
    } else if (match(String.raw`DROP CONSTRAINT (?:IF EXISTS )?(${IDENT})`, a, "i")) {
      const n = identName(match(String.raw`DROP CONSTRAINT (?:IF EXISTS )?(${IDENT})`, a, "i")[1]);
      for (const k of ["foreign_keys", "unique", "checks"]) t[k] = t[k].filter((x) => get(x, "name") !== n);
    } else if (match(String.raw`ALTER (?:COLUMN )?(${IDENT}) `, a, "i")) {
      const mc = match(String.raw`ALTER (?:COLUMN )?(${IDENT}) (.*)$`, a, "i");
      const col = identName(mc[1]), act2 = mc[2];
      const c = get(t.columns, col);
      if (c === null) b.unparsed.push(`ALTER COLUMN on unknown column ${t.name}.${col}`);
      else if (match("SET NOT NULL", act2, "i")) c.nullable = false;
      else if (match("DROP NOT NULL", act2, "i")) c.nullable = true;
      else if (match("SET DEFAULT ", act2, "i")) c.default = act2.slice(12).trim();
      else if (match("DROP DEFAULT", act2, "i")) c.default = null;
      else if (match("(?:SET DATA )?TYPE ", act2, "i")) {
        c.type = sub(String.raw`\s+USING .*$`, "", sub("^(?:SET DATA )?TYPE ", "", act2, "i"), "i").trim().toLowerCase();
        c.family = typeFamily(c.type, R);
      } else b.unparsed.push(`ALTER COLUMN not understood: ${act2.slice(0, 50)}`);
    } else b.unparsed.push(`ALTER TABLE action not understood on ${t.name}: ${a.slice(0, 60)}`);
  }
}

/** Applies the DDL of `text` to builder `b`. With a `deferred` list, an ALTER TABLE or CREATE INDEX on a table not created yet is
 *  kept there as [statement, file] instead of reported, to be applied once every source of the builder has been read. */
export function applySql(b, text, file, R, deferred = null) {
  for (const stmt of cleanAndSplit(text)) {
    const s = stmt.replace(/\s+/g, " ").trim();
    const up = s.toUpperCase();
    let m = match(String.raw`CREATE (?:(?:GLOBAL |LOCAL )?(?:TEMP|TEMPORARY) |UNLOGGED )?TABLE (?:IF NOT EXISTS )?(${QNAME})\s*\(`, s, "i");
    if (m) {
      const p = m.index + m[0].length - 1;
      const e = matchParen(s, p);
      if (e < 0) { b.unparsed.push(`CREATE TABLE not closed in ${file}`); continue; }
      const t = b.table(qnameTable(m[1]), file, true);
      resetTable(t);
      const items = splitTop(s.slice(p + 1, e));
      const consts = items.filter((x) => match(String.raw`\s*(?:CONSTRAINT\b|PRIMARY\s+KEY\b|UNIQUE\s*\(|FOREIGN\s+KEY\b|CHECK\s*\(|EXCLUDE\b)`, x, "i"));
      for (const item of items) {
        if (consts.includes(item) || match(String.raw`\s*(LIKE|INHERITS)\b`, item, "i")) continue;
        parseColumn(b, t, item, R);
      }
      for (const item of consts) parseTableConstraint(b, t, item);
      continue;
    }
    if (match("CREATE (?:UNLOGGED )?TABLE ", up)) {
      b.unparsed.push(`CREATE TABLE form not understood in ${file}: ${s.slice(0, 70)}`);
      continue;
    }
    m = match(String.raw`ALTER TABLE (?:ONLY )?(?:IF EXISTS )?(${QNAME}) (.*)$`, s, "i");
    if (m) {
      const t = b.table(qnameTable(m[1]));
      if (t === null) {
        if (deferred !== null) { deferred.push([stmt, file]); continue; }
        b.unparsed.push(`ALTER TABLE on a table not created before: ${qnameTable(m[1])} (${file})`);
        continue;
      }
      alterTable(b, t, m[2], R);
      continue;
    }
    m = match(String.raw`CREATE (UNIQUE )?INDEX (?:CONCURRENTLY )?(?:IF NOT EXISTS )?(${IDENT} )?ON (?:ONLY )?(${QNAME})\s*(?:USING (\w+))?\s*\(`, s, "i");
    if (m) {
      const t = b.table(qnameTable(m[3]));
      if (t === null) {
        if (deferred !== null) { deferred.push([stmt, file]); continue; }
        b.unparsed.push(`CREATE INDEX on a table not created before: ${qnameTable(m[3])} (${file})`);
        continue;
      }
      const p = m.index + m[0].length - 1;
      const e = matchParen(s, p);
      // Python's s[p+1:e] with e == -1 is s[p+1:-1]
      const cols = colList(s.slice(p + 1, e < 0 ? s.length - 1 : e));
      const tail = s.slice(e + 1);
      const wm = search(String.raw`\bWHERE\b(.*)$`, tail, "is");
      const name = m[2] ? identName(m[2]) : `${t.name}_${cols.join("_")}_idx`;
      b.index(t, name, cols, Boolean(m[1]), (m[4] || "btree").toLowerCase(), wm ? wm[1].trim() : null);
      continue;
    }
    m = match(String.raw`DROP TABLE (?:IF EXISTS )?(.+?)(?: CASCADE| RESTRICT)?$`, s, "i");
    if (m) {
      for (const x of splitTop(m[1])) b.dropTable(qnameTable(x));
      continue;
    }
    m = match(String.raw`DROP INDEX (?:CONCURRENTLY )?(?:IF EXISTS )?(.+?)(?: CASCADE| RESTRICT)?$`, s, "i");
    if (m) {
      const names = new Set(splitTop(m[1]).map(qnameTable));
      for (const t of Object.values(b.tables)) t.indexes = t.indexes.filter((i) => !names.has(i.name));
    }
    // INSERT, SET, CREATE EXTENSION/TYPE/SEQUENCE/FUNCTION/VIEW/TRIGGER, COMMENT, BEGIN/COMMIT… do not change what is measured
  }
}

const DOWN_MARK = String.raw`^\s*--\s*(\+goose\s+down|migrate:down|\+migrate\s+down|\+micrate\s+down|@down)\b`;

// ───────────────────────── secondary databases (R2, Requirement 1) ─────────────────────────
const TSQL = String.raw`^\s*GO\s*;?\s*$|\bIDENTITY\s*\(\s*\d+\s*,\s*\d+\s*\)|\bNVARCHAR\b|\bDATETIME2\b|\bUNIQUEIDENTIFIER\b|\[dbo\]|\bdbo\.|` +
  String.raw`\bIF\s+(?:NOT\s+)?EXISTS\s*\(\s*SELECT\b[^)]*\bsys\.|\bOBJECT_ID\s*\(|\bBIT\s+NOT\s+NULL\s+DEFAULT\s*\(?\s*[01]`;
const SECONDARY_TOKENS = new Set(["mssql", "sqlserver", "tsql", "replica", "replicas", "replication", "mirror", "secondary"]);

/** Lower-case words of a path, splitting camelCase too: backend/src/db/sqlServerReplica.js -> [..., sql, server, replica, js]. */
export const pathTokens = (p) => str(p).replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);

/** Why a SQL text belongs to a secondary database rather than the main PostgreSQL schema, or null. */
export function secondaryStore(p, text) {
  const toks = pathTokens(p);
  if (toks.some((t) => SECONDARY_TOKENS.has(t)) || toks.some((a, i) => a === "sql" && toks[i + 1] === "server")) return "the path names a replica or SQL Server";
  if (search(TSQL, text, "im")) return "SQL Server (T-SQL) syntax";
  return null;
}

/** Sort key that orders numbered migrations by number: 2_create.sql before 10_alter.sql. */
export const naturalKey = (p) => str(p).split(/(\d+)/).map((x) => (/^\d+$/.test(x) ? Number(x) : x.toLowerCase()));

/** `files` = [[relative_path, text]]; applied in natural path order. */
export function sqlBuilder(files, R, skipped = null, deferred = null) {
  const b = new Builder("sql");
  for (const [p, text] of sorted(files, (f) => naturalKey(f[0]))) {
    if (/[._-]down\.sql$/i.test(p)) continue;  // golang-migrate style: the down half undoes the schema
    const why = secondaryStore(p, text);
    if (why) {
      if (skipped !== null) skipped.push({ file: p, reason: why });
      continue;
    }
    const m = search(DOWN_MARK, text, "im");
    applySql(b, m ? text.slice(0, m.index) : text, p, R, deferred);
  }
  return b;
}

// ───────────────────────── 2. Sequelize migrations ─────────────────────────
/** Unwraps ast_metrics.js' {$expr: text} into text; other values unchanged. */
export const val = (x) => (isDict(x) && has(x, "$expr") ? x.$expr : x);

function tableArg(x) {
  x = val(x);
  if (isDict(x)) return val(get(x, "tableName"));
  return typeof x === "string" && fullmatch(String.raw`[\w$.\- ]+`, x) ? x : null;
}

/** Applies a Sequelize attribute definition (string/expression shorthand or object) to table `t`. */
function seqColumn(b, t, name, d, R) {
  if (!isDict(d) || has(d, "$expr")) d = { type: d };
  const typ = sequelizeType(get(d, "type"), R);
  if (str(or(val(get(d, "type")), "")).toUpperCase().endsWith("VIRTUAL")) return null;
  const pk = truthy(get(d, "primaryKey"));
  const field = get(d, "field");
  const c = b.column(t, typeof field === "string" ? field : name, typ, R, pk || get(d, "allowNull") === false ? false : true);
  const dv = get(d, "defaultValue");
  if (dv !== null) c.default = str(val(dv));
  else if (truthy(get(d, "autoIncrement"))) c.default = "autoincrement";
  if (pk) {
    if (!t.primary_key.includes(c.name)) t.primary_key.push(c.name);
    t.primary_key_source = b.source;
  }
  if (truthy(get(d, "unique"))) b.unique(t, [c.name], typeof d.unique === "string" ? d.unique : null);
  const ref = get(d, "references");
  if (isDict(ref)) {
    const target = or(tableArg(get(ref, "model")), tableArg(get(ref, "table")));
    if (target) {
      const k = or(get(ref, "key"), get(ref, "field"));
      b.foreignKey(t, [c.name], target, truthy(k) ? [k] : [], null, get(d, "onDelete"));
    } else b.unparsed.push(`reference to a model expression in ${t.name}.${c.name}: ${str(val(get(ref, "model")))}`);
  }
  return c;
}

function constraintCols(fields) {
  return (Array.isArray(fields) ? fields : []).map((f) => {
    f = val(f);
    return typeof f === "string" ? f : isDict(f) ? val(or(get(f, "name"), get(f, "attribute"))) : str(f);
  });
}

const TABLE_METHODS = new Set(["createTable", "dropTable", "addColumn", "removeColumn", "changeColumn", "addConstraint", "removeConstraint", "addIndex", "removeIndex"]);

export function migrationsBuilder(migs, R) {
  const b = new Builder("sequelize_migration");
  for (const mg of sorted(migs, (x) => [x.file, x.line])) {
    const a = mg.args, f = mg.file;
    const tname = a.length ? tableArg(a[0]) : null;
    if (TABLE_METHODS.has(mg.method) && !tname) {
      b.unparsed.push(`${mg.method} with a table name that is not a literal (${f}:${mg.line})`);
      continue;
    }
    const m = mg.method;
    if (m === "createTable" && a.length > 1 && isDict(a[1])) {
      const t = b.table(tname, f, true);
      resetTable(t);
      for (const [cname, d] of Object.entries(a[1])) if (cname !== "$spread") seqColumn(b, t, cname, d, R);
      if (truthy(get(a[1], "$spread"))) b.unparsed.push(`createTable(${tname}) spreads columns from ${str(a[1].$spread)}`);
      const opts = a.length > 2 && isDict(a[2]) ? a[2] : {};
      const uks = get(opts, "uniqueKeys");
      for (const uk of isDict(uks) ? Object.values(uks) : []) if (isDict(uk)) b.unique(t, constraintCols(get(uk, "fields")));
    } else if (m === "dropTable") b.dropTable(tname);
    else if ((m === "addColumn" || m === "changeColumn") && a.length > 2) {
      const t = b.table(tname);
      if (t === null) { b.unparsed.push(`${m} on a table not created before: ${tname} (${f}:${mg.line})`); continue; }
      if (m === "changeColumn" && typeof a[1] === "string" && has(t.columns, a[1])) {
        const old = t.columns[a[1]];
        seqColumn(b, t, a[1], a[2], R);
        if (isDict(a[2]) && !has(a[2], "allowNull")) t.columns[a[1]].nullable = old.nullable;
      } else seqColumn(b, t, a[1], a[2], R);
    } else if (m === "removeColumn" && a.length > 1) {
      const t = b.table(tname);
      if (t) {
        delete t.columns[a[1]];
        t.foreign_keys = t.foreign_keys.filter((x) => !x.columns.includes(a[1]));
        t.indexes = t.indexes.filter((x) => !x.columns.includes(a[1]));
      }
    } else if (m === "addConstraint" && a.length > 1 && isDict(a[1])) {
      const t = b.table(tname);
      if (t === null) { b.unparsed.push(`addConstraint on a table not created before: ${tname} (${f}:${mg.line})`); continue; }
      const c = a[1];
      const kind = str(or(val(get(c, "type")), "")).toLowerCase(), cols = constraintCols(get(c, "fields")), name = val(get(c, "name"));
      if (kind === "primary key") b.primaryKey(t, cols);
      else if (kind === "unique") b.unique(t, cols, name);
      else if (kind === "foreign key") {
        const r = or(get(c, "references"), {});
        const tgt = or(tableArg(get(r, "table")), tableArg(get(r, "model")));
        if (tgt) {
          const k = or(get(r, "field"), get(r, "key"));
          b.foreignKey(t, cols, tgt, truthy(k) ? [k] : [], name, get(c, "onDelete"));
        }
      } else if (kind === "check") {
        const w = get(c, "where");
        const wcols = isDict(w) ? Object.keys(w).filter((k) => !k.startsWith("[")) : cols;
        const use = wcols.length ? wcols : cols;
        b.check(t, `check(${use.join(", ")})`, name, use);
      }
    } else if (m === "removeConstraint" && a.length > 1) {
      const t = b.table(tname);
      if (t) for (const k of ["foreign_keys", "unique", "checks"]) t[k] = t[k].filter((x) => get(x, "name") !== a[1]);
    } else if (m === "addIndex") {
      const t = b.table(tname);
      if (t === null) { b.unparsed.push(`addIndex on a table not created before: ${tname} (${f}:${mg.line})`); continue; }
      const attrs = a.length > 1 ? a[1] : null;
      const opts = a.length > 2 && isDict(a[2]) ? a[2] : isDict(attrs) ? attrs : {};
      const fields = Array.isArray(attrs) ? attrs : isDict(opts) ? get(opts, "fields") : null;
      const cols = constraintCols(fields);
      if (cols.length) {
        const name = isDict(opts) && truthy(get(opts, "name")) ? val(opts.name) : `${t.name}_${cols.join("_")}`;
        b.index(t, name, cols, isDict(opts) ? truthy(get(opts, "unique")) : false,
          isDict(opts) ? str(or(val(get(opts, "using")), "btree")).toLowerCase() : "btree",
          isDict(opts) && truthy(get(opts, "where")) ? "partial" : null);
      }
    } else if (m === "removeIndex" && a.length > 1) {
      const t = b.table(tname);
      if (t) {
        const byCols = constraintCols(Array.isArray(a[1]) ? a[1] : []);
        t.indexes = t.indexes.filter((i) => i.name !== a[1] && !sameList(i.columns, byCols));
      }
    } else if (m === "renameColumn" || m === "renameTable") b.unparsed.push(`${m} ignored (${f}:${mg.line}): the resulting names are not tracked`);
  }
  return b;
}

/** DDL found in string/template literals of the production code, as [[file:line, text]], in file order. */
export function ddlStrings(sqlStrings, migration, skipped = null) {
  const out = [];
  for (const s of sqlStrings) {
    if (truthy(get(s, "migration")) !== migration || !match(String.raw`\s*(create|alter|drop)\b`, s.text, "i")) continue;
    const where = `${s.file}:${s.line}`;
    const why = secondaryStore(s.file, s.text);
    if (why) {
      if (skipped !== null) skipped.push({ file: where, reason: why });
      continue;
    }
    out.push([where, s.text]);
  }
  return sorted(out, (x) => naturalKey(x[0]));
}

// ───────────────────────── 3. Sequelize models ─────────────────────────
function modelTableName(model) {
  const o = or(get(model, "options"), {});
  if (typeof get(o, "tableName") === "string") return o.tableName;
  const name = or(get(model, "modelName"), get(model, "variable"));
  return truthy(get(o, "freezeTableName")) ? name : plural(name);
}

export function modelsBuilder(seq, R) {
  const b = new Builder("sequelize_model");
  const models = get(seq, "models", []).filter((m) => truthy(or(get(m, "modelName"), get(m, "variable"))));
  const byRef = new Map();
  for (const m of models) for (const key of [get(m, "variable"), get(m, "modelName")]) if (truthy(key) && !byRef.has(key)) byRef.set(key, m);
  const info = new Map();  // model -> {table, underscored, name, attr: {attribute: column}}
  for (const m of models) {
    const o = or(get(m, "options"), {});
    const und = truthy(get(o, "underscored"));
    const t = b.table(modelTableName(m), m.file, true);
    const inf = { table: t.name, underscored: und, name: or(get(m, "modelName"), get(m, "variable")), model: m, attr: {} };
    info.set(m, inf);
    const attrs = isDict(get(m, "attributes")) ? m.attributes : {};
    for (let [aname, d] of Object.entries(attrs)) {
      if (aname === "$spread") { b.unparsed.push(`model ${str(inf.name)} spreads attributes from ${str(attrs.$spread)}`); continue; }
      if (und && isDict(d) && !has(d, "$expr") && !has(d, "field")) d = { ...d, field: snake(aname) };
      else if (und && !(isDict(d) && !has(d, "$expr"))) d = { type: d, field: snake(aname) };
      const col = seqColumn(b, t, aname, d, R);
      if (col) inf.attr[aname] = col.name;
    }
    if (!t.primary_key.length && get(o, "id") !== false && !has(t.columns, "id")) {
      b.column(t, "id", "integer", R, false, "autoincrement");
      t.primary_key = ["id"]; t.primary_key_source = "sequelize_model (implicit id)";
    }
    const ts = get(o, "timestamps", true);
    if (ts !== false) {
      for (const [key, dflt] of [["createdAt", "createdAt"], ["updatedAt", "updatedAt"]]) {
        let nm = get(o, key, dflt);
        if (nm !== false) {
          nm = und && nm === dflt ? snake(nm) : nm;
          if (!has(t.columns, nm)) b.column(t, nm, "timestamp with time zone", R, false);
        }
      }
      if (truthy(get(o, "paranoid"))) {
        let nm = get(o, "deletedAt", "deletedAt");
        nm = und && nm === "deletedAt" ? snake(nm) : nm;
        if (!has(t.columns, nm)) b.column(t, nm, "timestamp with time zone", R, true);
      }
    }
    for (const ix of or(get(o, "indexes"), [])) {
      if (!isDict(ix)) continue;
      const cols = constraintCols(get(ix, "fields"));
      if (cols.length) b.index(t, or(val(get(ix, "name")), `${t.name}_${cols.join("_")}`), cols, truthy(get(ix, "unique")),
        str(or(val(get(ix, "using")), "btree")).toLowerCase(), truthy(get(ix, "where")) ? "partial" : null);
    }
  }

  const lookup = (ref) => byRef.get(ref) ?? null;
  const pkOf = (t) => (t.primary_key.length ? t.primary_key[0] : "id");
  function addFk(table, col, targetTable, targetCol, nullable, onDelete = null, inf = null) {
    if (inf) col = or(get(inf.attr, col), inf.underscored && has(table.columns, snake(col)) ? snake(col) : col);
    let c = get(table.columns, col);
    if (c === null) {
      const tcol = get(targetTable.columns, targetCol, {});
      c = b.column(table, col, get(tcol, "type", "integer"), R, nullable);
      c.source = "sequelize_model (association)";
    } else if (nullable === false) c.nullable = false;
    b.foreignKey(table, [col], targetTable.name, [targetCol], null, onDelete);
  }
  const fkName = (base, und, pk) => (und ? snake(base) + "_" + pk : pk === "id" ? `${base}Id` : `${base}${pk[0].toUpperCase() + pk.slice(1)}`);

  for (const a of get(seq, "associations", [])) {
    const src = lookup(get(a, "source")), tgt = lookup(get(a, "target"));
    if (!src || !tgt) {
      b.unparsed.push(`association ${str(get(a, "source"))}.${a.kind}(${str(get(a, "target"))}) between models that were not found (${a.file}:${a.line})`);
      continue;
    }
    const si = info.get(src), ti = info.get(tgt);
    const st = b.tables[si.table], tt = b.tables[ti.table];
    const o = or(get(a, "options"), {});
    const fkopt = get(o, "foreignKey");
    const fkAllow = isDict(fkopt) ? get(fkopt, "allowNull") : null;
    const fkn = isDict(fkopt) ? or(get(fkopt, "name"), get(fkopt, "field")) : fkopt;
    const onDelete = typeof get(o, "onDelete") === "string" ? o.onDelete : null;
    const kind = a.kind;
    if (kind === "belongsTo") {
      const alias = typeof get(o, "as") === "string" ? o.as : singular(ti.name);
      const col = typeof fkn === "string" ? fkn : fkName(alias, si.underscored, pkOf(tt));
      addFk(st, col, tt, pkOf(tt), fkAllow !== false, onDelete, si);
    } else if (kind === "hasMany" || kind === "hasOne") {
      const alias = singular(si.name);
      const col = typeof fkn === "string" ? fkn : fkName(alias, ti.underscored, pkOf(st));
      addFk(tt, col, st, pkOf(st), fkAllow !== false, onDelete, ti);
    } else if (kind === "belongsToMany") {
      let thr = val(get(o, "through"));
      if (isDict(thr)) thr = val(get(thr, "model"));
      const tmodel = typeof thr === "string" ? lookup(thr) : null;
      const tname = tmodel ? info.get(tmodel).table : typeof thr === "string" && fullmatch(String.raw`[\w$.\- ]+`, thr) ? thr : null;
      if (!tname) { b.unparsed.push(`belongsToMany without a resolvable through table (${a.file}:${a.line})`); continue; }
      const jt = b.table(tname, a.file, true);
      const c1 = typeof fkn === "string" ? fkn : fkName(singular(si.name), si.underscored, pkOf(st));
      const c2 = typeof get(o, "otherKey") === "string" ? o.otherKey : fkName(singular(ti.name), si.underscored, pkOf(tt));
      addFk(jt, c1, st, pkOf(st), false, onDelete);
      addFk(jt, c2, tt, pkOf(tt), false, onDelete);
      if (!tmodel && !jt.primary_key.length) {
        jt.primary_key = [c1, c2]; jt.primary_key_source = "sequelize_model (belongsToMany)";
        if (!has(jt.columns, "createdAt") && !has(jt.columns, "created_at"))
          for (const nm of ["createdAt", "updatedAt"]) b.column(jt, si.underscored ? snake(nm) : nm, "timestamp with time zone", R, false);
      }
    }
  }
  const modelTables = {};
  for (const m of models) modelTables[or(get(m, "modelName"), get(m, "variable"))] = info.get(m).table;
  for (const m of models) if (truthy(get(m, "variable"))) modelTables[m.variable] = info.get(m).table;
  return [b, modelTables];
}

// ───────────────────────── assembling ─────────────────────────
/** `builders` in order of preference. A table is decided by the first source that defines it. */
function merge(builders, R) {
  let tables = {};
  const seen = new Set();
  for (const b of builders) {
    for (const [name, t] of Object.entries(b.tables)) {
      if (seen.has(fold(name))) continue;
      seen.add(fold(name));
      tables[name] = t;
    }
  }
  const ignore = new Set(get(R, "ignore_tables", []).map(fold));
  tables = Object.fromEntries(Object.entries(tables).filter(([k]) => !ignore.has(fold(k))));
  for (const t of Object.values(tables)) {  // resolve FK targets to the table names of the final schema
    for (const fk of t.foreign_keys) {
      fk.ref_table = Object.keys(tables).find((n) => fold(n) === fold(fk.ref_table)) ?? fk.ref_table;
      if (!fk.ref_columns.length) {
        const pk = get(get(tables, fk.ref_table, {}), "primary_key");
        fk.ref_columns = [...(truthy(pk) ? pk : ["id"])];
      }
    }
  }
  return tables;
}

/** Table of the final schema that a query's model reference (`Order`, `models.Order`) points to; null if unknown. */
export function tableForModel(model, schema) {
  const mt = get(schema, "model_tables", {});
  const cand = get(mt, model);
  const names = Object.keys(schema.tables);
  if (truthy(cand)) return names.find((n) => fold(n) === fold(cand)) ?? null;
  const f = fold(model);
  const alts = [f, fold(plural(model)), fold(singular(model))];
  return names.find((n) => alts.includes(fold(n))) ?? null;
}

/** sqlFiles = [[relative path, text]]; ast = the ast_metrics.js output. Returns the normalized schema. */
export function extract(sqlFiles, ast, R) {
  const seq = or(get(ast, "sequelize"), { models: [], associations: [], migrations: [] });
  const skipped = [], deferred = [];
  const sqlb = sqlBuilder(sqlFiles, R, skipped, deferred);
  const migs = migrationsBuilder(get(seq, "migrations", []), R);
  for (const [p, text] of ddlStrings(get(ast, "sqlStrings", []), true, skipped)) {  // DDL in JS migrations: same parser, labelled as a migration
    const tmp = new Builder("sequelize_migration");
    tmp.tables = migs.tables;
    applySql(tmp, text, p, R);
    migs.unparsed.push(...tmp.unparsed);
  }
  for (const [p, text] of ddlStrings(get(ast, "sqlStrings", []), false, skipped)) applySql(sqlb, text, p, R, deferred);  // start-up DDL
  for (const [stmt, p] of deferred) applySql(sqlb, stmt, p, R);  // now every CREATE of the source is known
  const [modb, modelTables] = modelsBuilder(seq, R);
  const order = { sql: sqlb, sequelize_migration: migs, sequelize_model: modb };
  const tables = merge(R.source_preference.filter((s) => has(order, s)).map((s) => order[s]), R);
  const count = {};
  for (const t of Object.values(tables)) count[t.source] = (count[t.source] ?? 0) + 1;
  return { tables, sources: count, model_tables: modelTables,
    unparsed: [...sqlb.unparsed, ...migs.unparsed, ...modb.unparsed].slice(0, 40), secondary_sql: skipped.slice(0, 40) };
}

export function summary(schema) {
  const t = get(schema, "tables", {});
  const src = sorted(Object.entries(get(schema, "sources", {}))).map(([s, n]) => `${n} from ${s}`).join(", ");
  return `${Object.keys(t).length} table(s)` + (src ? ` (${src})` : "");
}

export { cmp };
