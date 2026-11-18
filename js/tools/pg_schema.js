#!/usr/bin/env node
/**
 * pg_schema.js — Creates, inspects and drops the disposable PostgreSQL database used by pg_analysis.py.
 *
 *   PG_ADMIN_URL=postgres://user:password@host:5432/postgres node pg_schema.js create <eval_db>
 *   PG_ADMIN_URL=...                                         node pg_schema.js dump   <eval_db> <output.json>
 *   PG_ADMIN_URL=...                                         node pg_schema.js drop   <eval_db>
 *
 * PG_ADMIN_URL is a connection string whose user may create and drop databases. This script only ever touches databases
 * named eval_[a-z0-9_]+ (create, dump and drop refuse any other name), so a mistake cannot reach other databases of the server.
 *
 * `dump` reads the catalog of the real database (information_schema and pg_catalog): columns, constraints, foreign keys, indexes
 * and index usage (pg_stat_user_indexes), and writes it in the normalized shape that relational_analysis.from_catalog() reads:
 *   { database, server_version, schema, tables: { name: { columns, primary_key, foreign_keys, unique, checks, indexes, rows } } }
 */
const fs = require("fs");

const NAME_RE = /^eval_[a-z0-9_]{1,50}$/;
const validDbName = (name) => NAME_RE.test(String(name));
const quoteIdent = (s) => '"' + String(s).replace(/"/g, '""') + '"';
const DELETE_RULES = { a: "NO ACTION", r: "RESTRICT", c: "CASCADE", n: "SET NULL", d: "SET DEFAULT" };

/** Connection string of database `db` on the same server (and with the same credentials) as `adminUrl`. */
function urlFor(adminUrl, db) {
  const u = new URL(adminUrl);
  u.pathname = "/" + db;
  return u.toString();
}

/** Type as the evaluator compares it (character varying(100), numeric(10,2), integer, text[] …). */
function typeOf(c) {
  const dt = c.data_type;
  if (dt === "USER-DEFINED") return c.udt_name;
  if (dt === "ARRAY") return String(c.udt_name).replace(/^_/, "") + "[]";
  if ((dt === "character varying" || dt === "character") && c.character_maximum_length) return `${dt}(${c.character_maximum_length})`;
  if (dt === "numeric" && c.numeric_precision != null) return `numeric(${c.numeric_precision},${c.numeric_scale ?? 0})`;
  return dt;
}

/**
 * Reads the catalog through `client` (anything with query(text, params) -> {rows}: a pg Client, or PGlite in the tests).
 * Sizes and row counts are of the data left by the acceptance gate and the seed script: they are small by design.
 */
async function dumpCatalog(client, schema = "public") {
  const q = async (text, params) => (await client.query(text, params)).rows;
  const version = (await q("SHOW server_version"))[0].server_version;
  const database = (await q("SELECT current_database() AS name"))[0].name;
  const tables = {};
  const cols = await q(
    `SELECT c.table_name, c.column_name, c.data_type, c.udt_name, c.character_maximum_length, c.numeric_precision, c.numeric_scale,
            c.is_nullable, c.column_default, c.is_identity
       FROM information_schema.columns c
       JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
      WHERE c.table_schema = $1 AND t.table_type = 'BASE TABLE'
      ORDER BY c.table_name, c.ordinal_position`, [schema]);
  for (const c of cols) {
    const t = (tables[c.table_name] ||= { columns: {}, primary_key: [], foreign_keys: [], unique: [], checks: [], indexes: [], rows: null });
    t.columns[c.column_name] = { name: c.column_name, type: typeOf(c), nullable: c.is_nullable === "YES",
      default: c.is_identity === "YES" ? "identity" : c.column_default };
  }
  const cons = await q(
    `SELECT con.conname AS name, con.contype AS kind, rel.relname AS table_name, ref.relname AS ref_table, con.confdeltype AS on_delete,
            pg_get_constraintdef(con.oid) AS definition,
            ARRAY(SELECT a.attname::text FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum ORDER BY k.ord) AS columns,
            ARRAY(SELECT a.attname::text FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum ORDER BY k.ord) AS ref_columns
       FROM pg_constraint con
       JOIN pg_class rel ON rel.oid = con.conrelid
       JOIN pg_namespace ns ON ns.oid = rel.relnamespace
       LEFT JOIN pg_class ref ON ref.oid = con.confrelid
      WHERE ns.nspname = $1 AND con.contype IN ('p', 'u', 'f', 'c') AND rel.relkind IN ('r', 'p')
      ORDER BY rel.relname, con.conname`, [schema]);
  for (const k of cons) {
    const t = tables[k.table_name];
    if (!t) continue;
    if (k.kind === "p") t.primary_key = k.columns;
    else if (k.kind === "u") t.unique.push({ name: k.name, columns: k.columns });
    else if (k.kind === "c") t.checks.push({ name: k.name, expr: k.definition, columns: k.columns });
    else t.foreign_keys.push({ name: k.name, columns: k.columns, ref_table: k.ref_table, ref_columns: k.ref_columns,
      on_delete: DELETE_RULES[k.on_delete] || null });
  }
  const idx = await q(
    `SELECT tbl.relname AS table_name, ic.relname AS name, ix.indisunique AS is_unique, ix.indisprimary AS is_primary,
            ix.indisvalid AS is_valid, am.amname AS method, pg_get_expr(ix.indpred, ix.indrelid) AS predicate,
            COALESCE(s.idx_scan, 0)::int AS scans,
            ARRAY(SELECT pg_get_indexdef(ix.indexrelid, k, true) FROM generate_series(1, ix.indnkeyatts::int) AS k ORDER BY k) AS columns
       FROM pg_index ix
       JOIN pg_class tbl ON tbl.oid = ix.indrelid
       JOIN pg_class ic ON ic.oid = ix.indexrelid
       JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
       JOIN pg_am am ON am.oid = ic.relam
       LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = ix.indexrelid
      WHERE ns.nspname = $1 AND tbl.relkind IN ('r', 'p')
      ORDER BY tbl.relname, ic.relname`, [schema]);
  for (const i of idx) {
    const t = tables[i.table_name];
    if (!t) continue;
    t.indexes.push({ name: i.name, columns: i.columns.map((c) => c.replace(/^"(.*)"$/, "$1")), unique: i.is_unique, primary: i.is_primary,
      method: i.method, predicate: i.predicate, valid: i.is_valid, scans: i.scans });
  }
  for (const name of Object.keys(tables)) {
    tables[name].rows = (await q(`SELECT count(*)::int AS n FROM ${quoteIdent(schema)}.${quoteIdent(name)}`))[0].n;
  }
  return { database, server_version: version, schema, tables };
}

const mask = (text, url) => {
  try { const pw = new URL(url).password; return pw ? String(text).split(decodeURIComponent(pw)).join("***") : String(text); } catch { return String(text); }
};

async function main() {
  const [cmd, db, out] = process.argv.slice(2);
  const admin = process.env.PG_ADMIN_URL;
  if (!["create", "dump", "drop"].includes(cmd) || !db || (cmd === "dump" && !out) || !admin) {
    console.error("Usage: PG_ADMIN_URL=postgres://… node pg_schema.js create|dump|drop <eval_db> [output.json]");
    process.exit(2);
  }
  if (!validDbName(db)) {
    console.error(`Refusing to touch "${db}": only databases named eval_[a-z0-9_]+ are allowed.`);
    process.exit(2);
  }
  const { Client } = require("pg");
  const client = new Client({ connectionString: cmd === "dump" ? urlFor(admin, db) : admin });
  try {
    await client.connect();
    if (cmd === "create") {
      const exists = (await client.query("SELECT 1 FROM pg_database WHERE datname = $1", [db])).rowCount > 0;
      if (exists) throw new Error(`database ${db} already exists (drop it first or use another run id)`);
      await client.query(`CREATE DATABASE ${quoteIdent(db)}`);
      console.log(`created ${db}`);
    } else if (cmd === "drop") {
      await client.query("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1 AND pid <> pg_backend_pid()", [db]);
      await client.query(`DROP DATABASE IF EXISTS ${quoteIdent(db)}`);
      console.log(`dropped ${db}`);
    } else {
      const cat = await dumpCatalog(client);
      fs.writeFileSync(out, JSON.stringify(cat, null, 1));
      console.log(`${db}: ${Object.keys(cat.tables).length} tables, PostgreSQL ${cat.server_version} → ${out}`);
    }
  } catch (e) {
    console.error(`pg_schema ${cmd} failed: ${mask(e.message, admin)}`);
    process.exitCode = 1;
  } finally {
    await client.end().catch(() => {});
  }
}

module.exports = { validDbName, urlFor, quoteIdent, typeOf, dumpCatalog };
if (require.main === module) main();
