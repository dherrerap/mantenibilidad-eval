// collectors/index.mjs — Evidence collection (protocol steps 3-4): runs every collector over an app and returns the metrics
// dictionary `m`, with the same keys in the same order as evaluator/collectors/__init__.py.
import fs from "node:fs";
import path from "node:path";
import { get, truthy } from "../../lib/py.mjs";
import * as ra from "../../relational/analysis.mjs";
import * as rs from "../../relational/schema.mjs";
import { RUBRIC } from "../common.mjs";
import { rel, walk } from "../sys.mjs";
import { classifyLayers, inventoryArtifacts, readSqlFiles, readmeText } from "./docs.mjs";
import { analyzePackages, fetchEol, postgresImages } from "./packages.mjs";
import { runMutation, runTests, staticTests } from "./testing.mjs";
import { findContracts, runAst, runContract, runDepcruise, runDuplication, runKnip, runLint } from "./tools.mjs";

/** Local ISO date and time to the second, as Python's datetime.now().isoformat(timespec="seconds"). */
export function nowIso(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** opts: {as_of, offline, run_tests, test_cmd, mutation, layers}. */
export async function collect(app, out, opts) {
  app = fs.realpathSync.native(path.resolve(app));
  const m = { app, date: nowIso() };
  m.as_of = get(opts, "as_of") || nowIso().slice(0, 10);  // reference date of everything that changes with time
  m.ast = runAst(app, out);
  m.schema = rs.extract(readSqlFiles(app), m.ast, RUBRIC.relational);
  m.er = ra.loadEr(app, RUBRIC.relational);
  m.postgres_images = postgresImages(app);
  m.graph = runDepcruise(app, out);
  m.packages = await analyzePackages(app, truthy(opts.offline), RUBRIC.thresholds.coupling.include_devdependencies, m.as_of);
  m.contract = runContract(app, out, findContracts(app));
  m.eol = await fetchEol(truthy(opts.offline), m.as_of);
  m.tests_static = staticTests(m.ast, app);
  m.tests_run = truthy(opts.run_tests) ? runTests(app, m.packages.packages, get(opts, "test_cmd"), out) : { executed: false };
  if (truthy(opts.run_tests) && truthy(get(opts, "mutation"))) m.mutation = runMutation(app, m.packages.packages, m.ast, out, get(opts, "test_cmd"));
  m.duplication = runDuplication(app, out);
  m.knip = runKnip(app, out);
  m.lint = runLint(app, out, m.ast.files.filter((f) => !f.test).map((f) => f.path));
  [m.layers, m.layers_origin] = classifyLayers(m.ast, app, get(opts, "layers") || path.join(app, ".layers.json"));
  m.readme = readmeText(app);
  const files = [...walk(app)];
  m.env_example = files.some((p) => [".env.example", ".env.sample", ".env.template", "env.example"].includes(path.basename(p)));
  m.artifacts = inventoryArtifacts(m, files.map((p) => rel(p, app)));
  return m;
}
