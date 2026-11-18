// docs.mjs — The app's documents and structure: SQL files, the README, the layer of each backend file, and the inventory of input
// artifacts (Table 27). Port of evaluator/collectors/{documents,layers}.py and inventory_artifacts / refresh_schema_artifact of
// evaluator/artifacts.py.
import fs from "node:fs";
import path from "node:path";
import { readText, findall, get, loadJson, or, search, sorted, splitlines, str, truthy } from "../../lib/py.mjs";
import * as ra from "../../relational/analysis.mjs";
import * as rs from "../../relational/schema.mjs";
import { RUBRIC } from "../common.mjs";
import { globToRe, rel, walk } from "../sys.mjs";

// ───────────────────────── documents ─────────────────────────
/** [[relative path, text]] of the app's *.sql files (at most 2 MB each), sorted. */
export function readSqlFiles(app, maxBytes = 2_000_000) {
  const out = [];
  for (const p of walk(app)) if (path.extname(p).toLowerCase() === ".sql" && fs.statSync(p).size <= maxBytes) out.push([rel(p, app), readText(p)]);
  return sorted(out);
}

/** docs/<label>/README.md of the latest versioned set, else README.md at the root, else the first README.md found. */
export function readmeFile(app) {
  for (const label of get(RUBRIC.relational, "doc_versions", [])) {
    const f = ra.findFile(ra.versionDir(app, label), "README.md");
    if (f) return f;
  }
  const root = ra.findFile(app, "README.md");
  if (root) return root;
  for (const p of walk(app)) if (path.basename(p).toLowerCase() === "readme.md") return p;
  return null;
}

export function readmeText(app) {
  const f = readmeFile(app);
  return f ? readText(f) : "";
}

// ───────────────────────── layers ─────────────────────────
/** [layers, origin]: the layer of each backend production file from its directory and file names, or from a .layers.json. */
export function classifyLayers(ast, app, override) {
  const L = RUBRIC.default_layers, names = ["presentation", "business", "data", "shared"];
  let ov = null;
  if (override && fs.existsSync(override))
    ov = Object.entries(JSON.parse(fs.readFileSync(override, "utf8"))).filter(([k]) => !k.startsWith("_")).map(([k, v]) => [k, v.map(globToRe)]);
  const out = {}, origin = {};
  const norm = (s) => s.replace(/s+$/, "");
  for (const f of ast.files) {
    if (f.test || f.frontend) continue;
    const p = f.path;
    let layer = null;
    if (ov) {
      for (const [k, res] of ov) if (res.some((r) => r.test(p))) { layer = k; origin[p] = "override"; break; }
    } else {
      const parts = p.toLowerCase().split("/");
      const base = path.posix.basename(p), dot = base.lastIndexOf(".");
      const stem = (dot > 0 ? base.slice(0, dot) : base).replace(/([a-z])([A-Z])/g, "$1.$2").toLowerCase();
      const tokens = [...stem.split(/[.\-_]/).filter(Boolean), ...parts.slice(0, -1).reverse()];
      // Architectural layers first (token closest to the file); 'shared' only if nothing else matches
      outer: for (const group of [names.slice(0, 3), names.slice(3)])
        for (const tok of tokens)
          for (const n of group)
            if (L[n].map(norm).includes(norm(tok))) { layer = n; origin[p] = tok; break outer; }
    }
    if (layer) out[p] = layer;
  }
  return [out, origin];
}

// ───────────────────────── artifacts (Table 27) ─────────────────────────
/** Does a Markdown text embed an architecture diagram: a Mermaid block other than an erDiagram, or a PlantUML one? */
export function embeddedDiagram(text) {
  if ((text || "").includes("@startuml")) return true;
  for (const block of findall("```[ \\t]*mermaid[ \\t]*\\r?\\n(.*?)```", text || "", "si")) {
    const first = splitlines(block).map((ln) => ln.trim()).find((ln) => ln && !ln.startsWith("%%")) || "";
    if (first && !/^erDiagram\b/.test(first)) return true;
  }
  return false;
}

/** Which input artifacts exist, classified as core, complementary or optional; `files` = relative paths of the app. */
export function inventoryArtifacts(m, files) {
  const low = files.map((f) => f.toLowerCase());
  const found = (rx) => files.filter((f, i) => search(rx, low[i]));
  const deps = new Set(m.packages.packages.flatMap((p) => [...Object.keys(p.dependencies), ...Object.keys(p.devDependencies)]));
  const obsLibs = sorted([...new Set([...RUBRIC.libs_logger, ...RUBRIC.libs_request_logger, ...RUBRIC.libs_metrics])].filter((x) => deps.has(x)));
  const prod = m.ast.files.filter((f) => !f.test);
  const ts = m.tests_static, tr = m.tests_run;
  const lock = found(String.raw`(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$`);
  const contract = [...m.contract.files, ...found(String.raw`\.schema\.json$|(^|/)dtos?/|\.dto\.[jt]s$`)];
  const deploy = [...found(String.raw`(^|/)dockerfile|docker-compose|\.github/workflows/|\.gitlab-ci|jenkinsfile|\.circleci/`), ...(truthy(m.env_example) ? [".env.example"] : [])];
  const adrs = found(String.raw`(^|/)(adrs?|docs?)/.*\.md$`);
  const diagrams = found(String.raw`\.(puml|drawio|mmd|plantuml)$|(architecture|diagram)[^/]*\.(png|svg|jpe?g)$`);
  if (embeddedDiagram(get(m, "readme", ""))) diagrams.push("README (embedded diagram)");
  for (const f of truthy(get(m, "app")) ? adrs : []) {  // docs/**/*.md with a Mermaid or PlantUML diagram
    let text;
    try { text = readText(path.join(m.app, f)); } catch { continue; }
    if (embeddedDiagram(text)) diagrams.push(`${f} (embedded diagram)`);
  }
  const agent = found(String.raw`(^|/)(prompt|session|transcript)[^/]*\.(md|txt|log|jsonl?)$|(^|/)(technical-n\d|requirements[\w-]*)\.md$`);
  const glossary = [...found("glossary|ontology"), ...(search(String.raw`^#+\s*glossary`, get(m, "readme", ""), "im") ? ["README (glossary section)"] : [])];
  const tables = m.schema.tables, er = m.er;
  const state = {
    source_code: [prod.length > 0, `${prod.length} production files`],
    data_schema: [Object.keys(tables).length > 0, Object.keys(tables).length ? rs.summary(m.schema) : "no relational schema found (SQL, Sequelize migrations or models)"],
    er_model: [truthy(er.found) && truthy(er.diagram), truthy(er.found)
      ? (truthy(er.diagram) ? `${er.file}: ${Object.keys(er.entities).length} entities` : `${er.file} has no erDiagram block`)
      : "not found (looked for " + ra.erSearched(RUBRIC.relational) + ")"],
    manifests: [m.packages.packages.length > 0, `${m.packages.packages.length} package.json` + (lock.length ? "" : "; no lockfile")],
    test_suite: [ts.test_cases > 0, `${ts.test_cases} test cases` + (truthy(tr.executed) && truthy(get(tr, "lines_total")) ? "; coverage report produced" : "; no coverage report")],
    contract_spec: [contract.length > 0, contract.slice(0, 3).join(", ") || "none"],
    config_deploy: [deploy.length > 0, deploy.slice(0, 4).join(", ") || "none"],
    logging_config: [obsLibs.length > 0, obsLibs.join(", ") || "no logging or metrics library"],
    readme_docs: [truthy(get(m, "readme")) || adrs.length > 0, (truthy(get(m, "readme")) ? "README" : "no README") + (adrs.length ? `; ${adrs.length} doc/ADR files` : "")],
    diagrams: [diagrams.length > 0, diagrams.slice(0, 3).join(", ") || "none"],
    agent_log: [agent.length > 0, agent.slice(0, 3).join(", ") || "none"],
    glossary: [glossary.length > 0, glossary.slice(0, 2).join(", ") || "none"],
  };
  return RUBRIC.artifacts.map((a) => ({ ...a, present: state[a.id][0], detail: state[a.id][1] }));
}

/** The data_schema artifact also counts as present when the live database (pg_schema.json) has tables. */
export function refreshSchemaArtifact(m) {
  const live = get(or(get(m, "pg"), {}), "tables");
  for (const a of get(m, "artifacts") || [])
    if (a.id === "data_schema" && !a.present && truthy(live)) Object.assign(a, { present: true, detail: `${Object.keys(live).length} table(s) from the live database (the static extraction found none)` });
  return m;
}

