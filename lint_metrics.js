#!/usr/bin/env node
/**
 * lint_metrics.js — Runs ESLint with eslint-plugin-sonarjs over the app's production files and dumps every report as JSON.
 *
 * usage: node lint_metrics.js <app_dir> <request.json> <out.json>
 *   request.json: {"files": ["backend/src/app.js", …], "rules": {"<rule id>": <ESLint rule setting>, …}}
 *
 * The rules and their options come from rubric.json (`lint`), composed by evaluator/collectors/lint.py: this script only runs them.
 * Its own configuration is the only one used (the app's eslint.config.* is ignored), so every app is measured with the same rules.
 * .ts/.mts/.cts files are parsed without JSX and the rest with JSX, all with the typescript-eslint parser and no type information.
 */
const fs = require("fs");
const path = require("path");

async function main() {
  const [root, reqFile, outFile] = process.argv.slice(2).map((x, i) => (i === 0 ? path.resolve(x) : x));
  const req = JSON.parse(fs.readFileSync(reqFile, "utf8"));
  const { ESLint } = require("eslint");
  const sonarjs = require("eslint-plugin-sonarjs");
  const tseslint = require("typescript-eslint");
  const base = { ecmaVersion: "latest", sourceType: "module", parser: tseslint.parser };
  const eslint = new ESLint({
    cwd: root,
    overrideConfigFile: true, // the app's own configuration is not read
    ignore: false,
    allowInlineConfig: false, // `// eslint-disable` comments in the app do not hide reports
    overrideConfig: [
      { files: ["**/*.{js,jsx,mjs,cjs,tsx}"], languageOptions: { ...base, parserOptions: { ecmaFeatures: { jsx: true } } } },
      { files: ["**/*.{ts,mts,cts}"], languageOptions: { ...base, parserOptions: { ecmaFeatures: { jsx: false } } } },
      { files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"], plugins: { sonarjs }, linterOptions: { reportUnusedDisableDirectives: "off" }, rules: req.rules },
    ],
  });
  const files = req.files.filter((f) => fs.existsSync(path.join(root, f)));
  const results = files.length ? await eslint.lintFiles(files.map((f) => path.join(root, f))) : [];
  const out = { ok: true, versions: { eslint: ESLint.version, "eslint-plugin-sonarjs": require("eslint-plugin-sonarjs/package.json").version, // meta.version says 0.0.0-SNAPSHOT
    "typescript-eslint": require("typescript-eslint/package.json").version }, files: files.length, parse_errors: [], messages: [] };
  for (const r of results) {
    const file = path.relative(root, r.filePath).split(path.sep).join("/");
    const lines = (r.source || fs.readFileSync(r.filePath, "utf8")).split(/\r?\n/);
    for (const msg of r.messages) {
      if (msg.fatal || !msg.ruleId) {
        out.parse_errors.push({ file, line: msg.line, message: msg.message });
        continue;
      }
      const m = { rule: msg.ruleId, file, line: msg.line, endLine: msg.endLine || msg.line, message: msg.message };
      if (msg.ruleId === "sonarjs/no-duplicate-string" && msg.endLine === msg.line) {
        m.text = (lines[msg.line - 1] || "").slice(msg.column - 1, msg.endColumn - 1); // the literal, quotes included
      }
      out.messages.push(m);
    }
  }
  fs.writeFileSync(outFile, JSON.stringify(out));
}

main().catch((e) => {
  const outFile = process.argv[4];
  if (outFile) fs.writeFileSync(outFile, JSON.stringify({ ok: false, error: String(e && e.stack || e) }));
  console.error(e && e.stack || e);
  process.exit(1);
});
