#!/usr/bin/env node
/**
 * mongo_schema.js — What MongoDB Compass shows (Schema, Indexes and Validation tabs), but from the command line.
 *
 * Usage:  MONGO_URI="mongodb+srv://user:password@host/<database>" node mongo_schema.js <output.json> [--drop]
 *
 * For each collection of the database in the URI: document count, schema observed in a sample (the same
 * analysis Compass uses: @mongodb-js/mongodb-schema), indexes and server validation rules.
 * --drop drops the database when finished (only if its name starts with "eval_": it never touches other databases in the cluster).
 */
const fs = require("fs");
const { MongoClient } = require("mongodb");
const { parseSchema } = require("@mongodb-js/mongodb-schema");

const SAMPLE = 1000;
const [outFile, ...flags] = process.argv.slice(2);
if (!outFile || !process.env.MONGO_URI) {
  console.error("Usage: MONGO_URI=... node mongo_schema.js <output.json> [--drop]");
  process.exit(2);
}

/** Flattens the field tree from mongodb-schema into [{path, types:[{type, prob}], presence}] */
function flatten(fields, prefix = "", out = []) {
  for (const f of fields) {
    const path = prefix + f.name;
    out.push({ path, presence: round(f.probability), types: f.types.map((t) => ({ type: t.name, prob: round(t.probability) })) });
    for (const t of f.types) {
      if (t.name === "Document" && t.fields) flatten(t.fields, path + ".", out);
      if (t.name === "Array") {
        for (const e of t.types || []) if (e.name === "Document" && e.fields) flatten(e.fields, path + "[].", out);
      }
    }
  }
  return out;
}
const round = (x) => Math.round(x * 1000) / 1000;

const { ObjectId } = require("mongodb");
const isOid = (v) => typeof v === "string" && /^[0-9a-f]{24}$/i.test(v);
const stripBrackets = (r) => r.replace(/\[\]/g, "");

/** Relations shown by the data: a field whose values are `_id`s of another collection (declared with ref or not). */
async function relations(db, collections) {
  const out = [];
  for (const [name, col] of Object.entries(collections)) {
    for (const f of col.fields) {
      if (f.path === "_id") continue;
      const types = f.types.map((t) => t.type);
      if (!types.includes("ObjectId") && !types.includes("String")) continue;
      let vals;
      try { vals = (await db.collection(name).distinct(stripBrackets(f.path))).slice(0, 300); } catch { continue; }
      vals = vals.filter((v) => v !== null && v !== undefined && (typeof v === "string" ? v.length >= 12 : v instanceof ObjectId));
      if (!vals.length) continue;
      const cands = vals.flatMap((v) => (typeof v === "string" && isOid(v) ? [v, new ObjectId(v)] : [v]));
      let best = null;
      for (const target of Object.keys(collections)) {
        const n = await db.collection(target).countDocuments({ _id: { $in: cands } });
        if (n > 0 && (!best || n > best.n)) best = { target, n };
      }
      if (best) out.push({ collection: name, field: f.path, type: types.includes("ObjectId") ? "ObjectId" : "String", target: best.target,
                           distinct: vals.length, match: round(Math.min(1, best.n / vals.length)), orphans: round(Math.max(0, 1 - best.n / vals.length)) });
    }
  }
  return out;
}

(async () => {
  const client = new MongoClient(process.env.MONGO_URI, { serverSelectionTimeoutMS: 20000 });
  await client.connect();
  const db = client.db();
  const info = await db.listCollections().toArray();
  const collections = {};
  for (const c of info) {
    if (c.name.startsWith("system.")) continue;
    const col = db.collection(c.name);
    const docs = await col.aggregate([{ $sample: { size: SAMPLE } }]).toArray();
    const schema = docs.length ? await parseSchema(docs) : { fields: [] };
    const fields = flatten(schema.fields);
    collections[c.name] = {
      documents: await col.estimatedDocumentCount(),
      sample: docs.length,
      fields,
      // field with more than one real type (not counting absence): what Compass marks as "Mixed"
      mixed_type_fields: fields.filter((f) => f.types.filter((t) => !["Undefined", "Null"].includes(t.type)).length > 1).map((f) => f.path),
      objectid: fields.filter((f) => f.path !== "_id" && f.types.some((t) => t.type === "ObjectId")).map((f) => f.path),
      document_arrays: fields.filter((f) => f.types.some((t) => t.type === "Array") && fields.some((g) => g.path.startsWith(f.path + "[]."))).map((f) => f.path),
      indexes: (await col.indexes()).map((i) => ({ name: i.name, key: i.key, unique: !!i.unique })),
      index_usage: await col.aggregate([{ $indexStats: {} }]).toArray().then((r) => r.map((x) => ({ name: x.name, operations: Number(x.accesses.ops) }))).catch(() => []),
      size_bytes: await col.aggregate([{ $project: { b: { $bsonSize: "$$ROOT" } } }, { $group: { _id: null, average: { $avg: "$b" }, max: { $max: "$b" } } }])
        .toArray().then((r) => (r[0] ? { average: Math.round(r[0].average), max: r[0].max } : null)).catch(() => null),
      max_depth: fields.reduce((m, f) => Math.max(m, f.path.split(/[.]|\[\]\./).length), 0),
      validator: (c.options && c.options.validator) || null,
    };
    // maximum length of top-level arrays (or nested only in documents): do they grow without bound?
    const col2 = collections[c.name];
    const paths = col2.fields.filter((f) => f.types.some((t) => t.type === "Array") && !f.path.includes("[]")).map((f) => f.path);
    col2.arrays = [];
    for (const path of paths) {
      const r = await col.aggregate([{ $project: { n: { $cond: [{ $isArray: "$" + path }, { $size: "$" + path }, 0] } } },
                                     { $group: { _id: null, max: { $max: "$n" }, average: { $avg: "$n" } } }]).toArray().catch(() => []);
      if (r[0]) col2.arrays.push({ path, max: r[0].max, average: round(r[0].average) });
    }
  }
  const rels = await relations(db, collections);
  fs.writeFileSync(outFile, JSON.stringify({ database: db.databaseName, date: new Date().toISOString(), collections, relations: rels }, null, 1));
  console.log(`mongo_schema: ${Object.keys(collections).length} collection(s) of ${db.databaseName} → ${outFile}`);
  if (flags.includes("--drop")) {
    if (!db.databaseName.startsWith("eval_")) console.error(`Not dropping ${db.databaseName}: only eval_* databases are dropped`);
    else { await db.dropDatabase(); console.log(`Database ${db.databaseName} dropped.`); }
  }
  await client.close();
})().catch((e) => { console.error("ERROR:", e.message); process.exit(1); });
