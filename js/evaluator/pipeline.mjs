// pipeline.mjs — Scoring of a run from its saved evidence, without collecting it again. Port of evaluator/pipeline.py and of the
// load_pg / load_conformance / load_judge inputs of evaluator/scoring.py (see pipeline.py for the inputs and their priority).
import fs from "node:fs";
import path from "node:path";
import { dumpsAscii, get, loadJson } from "../lib/py.mjs";
import { refreshSchemaArtifact } from "./collectors/docs.mjs";
import { writeOutputs } from "./outputs.mjs";
import { evaluateProfile } from "./scoring.mjs";

export const MANUAL_REVIEW = "manual_review.json";
const readJson = (p) => loadJson(fs.readFileSync(p, "utf8"));

/** Adds `key` from <out>/<file> to `obj`, or removes it when the file is not there. */
function loadOptional(out, file, obj, key) {
  const f = path.join(out, file);
  if (fs.existsSync(f)) obj[key] = readJson(f);
  else delete obj[key];
  return obj;
}
export const loadPg = (out, m) => loadOptional(out, "pg_schema.json", m, "pg");
export const loadConformance = (out, m) => loadOptional(out, "contract_conformance.json", m, "conformance");
export const loadJudge = (out, manual) => loadOptional(out, "judge.json", manual, "_judge");

/** The manual review of a run (--manual > <app>/manual.json > <res>/manual_review.json) plus the DV8 values
 *  (the review > dv8/dv8_manual.json > dv8/dv8_metrics.json). */
export function assembleManual(app, res, explicit = null) {
  const cands = [explicit, app ? path.join(app, "manual.json") : null, path.join(res, MANUAL_REVIEW)];
  const mfile = cands.find((p) => p && fs.existsSync(p));
  const manual = mfile ? readJson(mfile) : {};
  for (const source of ["dv8_manual.json", "dv8_metrics.json"]) {
    const f = path.join(res, "dv8", source);
    if (!fs.existsSync(f)) continue;
    if (!manual.dv8) manual.dv8 = {};
    const dv8 = manual.dv8;
    for (const [k, v] of Object.entries(readJson(f))) if (!k.startsWith("_") && v !== null && get(dv8, k) === null) dv8[k] = v;
  }
  return manual;
}

/** Scores a run from its evidence `m` and writes every output of results/<run>/. Returns [points, profile]. */
export function score(res, m, meta, manualFile = null) {
  const manual = assembleManual(get(m, "app"), res, manualFile);
  fs.writeFileSync(path.join(res, "manual.json"), dumpsAscii(manual, 1), "utf8");  // what this scoring used, for traceability
  loadPg(res, m);
  loadConformance(res, m);
  refreshSchemaArtifact(m);
  loadJudge(res, manual);
  const [pts, prof] = evaluateProfile(m, manual, { accept_heuristics: Boolean(get(meta, "accept_heuristics")) });
  writeOutputs(res, meta, pts, prof, m);
  return [pts, prof];
}

/** [metrics, meta] saved by `evaluate run` in results/<run>/. */
export const loadRun = (res) => [readJson(path.join(res, "metrics.json")), readJson(path.join(res, "meta.json"))];

/** Scores an already evaluated run again from its saved evidence. Returns [meta, points, profile]. */
export function rescore(res) {
  const [m, meta] = loadRun(res);
  const [pts, prof] = score(res, m, meta, get(meta, "manual_file"));
  return [meta, pts, prof];
}
