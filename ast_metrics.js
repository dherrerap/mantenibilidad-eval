#!/usr/bin/env node
/**
 * ast_metrics.js — Structural AST metrics (ts-morph) for the maintainability
 * evaluation framework. Processes the JS/JSX/TS/TSX files of a MERN application.
 *
 * Usage: node ast_metrics.js <app_directory> <output.json>
 *
 * Produces, among others: cyclomatic complexity and fan-out per function,
 * class hierarchies, switch without default / fall-through (CWE-478/484),
 * labeled jumps (CWE-1075), network literals (CWE-1051) and duplicates
 * (CWE-1052), console.*, catch blocks, error middleware, Express routes
 * and Mongoose schemas.
 */
const fs = require("fs");
const path = require("path");
const { Project, SyntaxKind, Node } = require("ts-morph");

const root = path.resolve(process.argv[2] || ".");
const outFile = process.argv[3] || "ast.json";

const IGNORE = [
  "**/node_modules/**", "**/dist/**", "**/build/**", "**/coverage/**",
  "**/.git/**", "**/.next/**", "**/out/**", "**/*.min.js", "**/*.d.ts",
];
const project = new Project({
  skipAddingFilesFromTsConfig: true,
  compilerOptions: { allowJs: true, checkJs: false, jsx: 2 /* React */, noEmit: true },
});
project.addSourceFilesAtPaths([
  ...["js", "jsx", "ts", "tsx", "mjs", "cjs"].map((e) => path.join(root, `**/*.${e}`)),
  ...IGNORE.map((g) => "!" + path.join(root, g)),
]);

const rel = (f) => path.relative(root, f).split(path.sep).join("/");
const isTest = (p) => /(^|\/)(__tests__|__mocks__|tests?|specs?|e2e|cypress)\/|\.(test|spec)\.[cm]?[jt]sx?$/.test(p);
const isFrontend = (p) =>
  /(^|\/)(client|frontend|web|ui)\//.test(p) || /\.(jsx|tsx)$/.test(p);

const FN_KINDS = new Set([
  SyntaxKind.FunctionDeclaration, SyntaxKind.FunctionExpression,
  SyntaxKind.ArrowFunction, SyntaxKind.MethodDeclaration,
  SyntaxKind.Constructor, SyntaxKind.GetAccessor, SyntaxKind.SetAccessor,
]);

/** Walks descendants without entering nested functions (like ESLint/complexity). */
function walkOwn(node, visit) {
  node.forEachChild((child) => {
    if (FN_KINDS.has(child.getKind())) return;
    visit(child);
    walkOwn(child, visit);
  });
}

function cyclomatic(fn) {
  let cc = 1;
  const body = fn.getBody ? fn.getBody() : undefined;
  const nodes = body ? [body] : [];
  // Parameter default values also branch (ESLint ≥ 9)
  (fn.getParameters ? fn.getParameters() : []).forEach((p) => {
    if (p.getInitializer()) cc++;
  });
  const count = (n) => {
    switch (n.getKind()) {
      case SyntaxKind.IfStatement:
      case SyntaxKind.ConditionalExpression:
      case SyntaxKind.ForStatement:
      case SyntaxKind.ForInStatement:
      case SyntaxKind.ForOfStatement:
      case SyntaxKind.WhileStatement:
      case SyntaxKind.DoStatement:
      case SyntaxKind.CatchClause:
      case SyntaxKind.CaseClause:
        cc++; break;
      case SyntaxKind.BinaryExpression: {
        const op = n.getOperatorToken().getKind();
        if (op === SyntaxKind.AmpersandAmpersandToken || op === SyntaxKind.BarBarToken ||
            op === SyntaxKind.QuestionQuestionToken || op === SyntaxKind.AmpersandAmpersandEqualsToken ||
            op === SyntaxKind.BarBarEqualsToken || op === SyntaxKind.QuestionQuestionEqualsToken) cc++;
        break;
      }
      default:
    }
  };
  nodes.forEach((b) => { count(b); walkOwn(b, count); });
  return cc;
}

function fnName(fn) {
  if (fn.getName && fn.getName()) return fn.getName();
  const p = fn.getParent();
  if (p) {
    if (Node.isVariableDeclaration(p) || Node.isPropertyAssignment(p) || Node.isPropertyDeclaration(p)) return p.getName();
    if (Node.isCallExpression(p)) {
      const callee = p.getExpression().getText();
      return `<callback of ${callee.slice(0, 40)}>`;
    }
  }
  return "<anonymous>";
}

/** Cognitive complexity (SonarSource, approximate): +1 per control structure, +nesting level, +1 per sequence of
 *  logical operators and per labeled jump. Nested functions are measured separately (as their own entries). */
function cognitive(fn) {
  let total = 0;
  const LOOPS = new Set([SyntaxKind.ForStatement, SyntaxKind.ForInStatement, SyntaxKind.ForOfStatement, SyntaxKind.WhileStatement, SyntaxKind.DoStatement]);
  const LOGIC = new Set([SyntaxKind.AmpersandAmpersandToken, SyntaxKind.BarBarToken, SyntaxKind.QuestionQuestionToken]);
  const walk = (node, nesting, elseIf) => {
    const k = node.getKind();
    if (FN_KINDS.has(k)) return;
    if (k === SyntaxKind.IfStatement) {
      total += elseIf ? 1 : 1 + nesting;
      walk(node.getExpression(), nesting, false);
      walk(node.getThenStatement(), nesting + 1, false);
      const e = node.getElseStatement();
      if (e) {
        if (e.getKind() === SyntaxKind.IfStatement) walk(e, nesting, true);
        else { total += 1; walk(e, nesting + 1, false); }
      }
      return;
    }
    if (LOOPS.has(k) || k === SyntaxKind.SwitchStatement || k === SyntaxKind.CatchClause || k === SyntaxKind.ConditionalExpression) {
      total += 1 + nesting;
      node.forEachChild((c) => walk(c, nesting + 1, false));
      return;
    }
    if (k === SyntaxKind.BinaryExpression && LOGIC.has(node.getOperatorToken().getKind())) {
      const par = node.getParent();
      const same = par && Node.isBinaryExpression(par) && par.getOperatorToken().getKind() === node.getOperatorToken().getKind();
      if (!same) total += 1;
    }
    if ((k === SyntaxKind.BreakStatement || k === SyntaxKind.ContinueStatement) && node.getLabel && node.getLabel()) total += 1;
    node.forEachChild((c) => walk(c, nesting, false));
  };
  const body = fn.getBody ? fn.getBody() : undefined;
  if (body) walk(body, 0, false);
  return total;
}

const normCallee = (t) => t.replace(/\([^()]*\)/g, "()").replace(/\s+/g, "").slice(0, 80);

const out = {
  root, files: [], functions: [], classes: [],
  switchesMissingDefault: [], fallthrough: [], labeledJumps: [],
  consoleCalls: [], networkLiterals: [], literalOccurrences: {},
  catchBlocks: { total: 0, logging: 0, delegating: 0, silent: [] },
  errorMiddleware: [], routes: [], mounts: [], schemas: [], populateCalls: [],
  testCases: [], docs: [], components: [], hooks: [], security: { evalCalls: [], secrets: [], nosqlInjection: [] },
  validationFields: [], queryFields: [],
  processEnvAccess: 0, envFiles: {}, imports: [],
};

const ENV_FALLBACK = (n) => {
  const p = n.getParent();
  return p && Node.isBinaryExpression(p) &&
    [SyntaxKind.BarBarToken, SyntaxKind.QuestionQuestionToken].includes(p.getOperatorToken().getKind()) &&
    /process\.env|import\.meta\.env/.test(p.getLeft().getText());
};
/** Does the route validate its input? Validation middleware between the path and the handler, or validation inside the handler. */
const VALIDATED = (call) => {
  const txt = call.getText();
  return /\b(validate\w*|celebrate|checkSchema|body\s*\(|param\s*\(|query\s*\(|schema\w*|zod|joi|yup|ajv)\b|\.(safeParse|parse|validateAsync|validateSync)\s*\(|validationResult/i.test(txt);
};
const NET_RE = /^(https?|mongodb(\+srv)?|redis|amqps?|ftp|wss?):\/\/|(^|[^\w.])localhost\b|\b(\d{1,3}\.){3}\d{1,3}\b/i;

for (const sf of project.getSourceFiles()) {
  const file = rel(sf.getFilePath());
  const test = isTest(file);
  const front = isFrontend(file);
  const lines = sf.getFullText().split("\n");
  const loc = lines.filter((l) => l.trim() && !l.trim().startsWith("//") && !l.trim().startsWith("*") && !l.trim().startsWith("/*")).length;
  out.files.push({ path: file, loc, test, frontend: front });

  sf.getImportDeclarations().forEach((d) => out.imports.push({ file, spec: d.getModuleSpecifierValue() }));

  // ---- functions
  sf.getDescendants().forEach((n) => {
    if (!FN_KINDS.has(n.getKind())) return;
    if (!n.getBody || !n.getBody()) return; // overloads / abstract
    const callees = new Set();
    const b = n.getBody();
    const addCall = (c) => { if (Node.isCallExpression(c)) callees.add(normCallee(c.getExpression().getText())); };
    addCall(b); walkOwn(b, addCall);
    // critical event (framework: errors, authentication, writes) and whether the function logs it
    const cs = [...callees];
    const WRITE_RE = /^(?!Object\.|Array\.|Promise\.|document\.).*\b(save|create|insertMany|insertOne|updateOne|updateMany|findOneAndUpdate|findByIdAndUpdate|deleteOne|deleteMany|findByIdAndDelete|findOneAndDelete|findByIdAndRemove|bulkWrite|remove)$/;
    const AUTH_RE = /(bcrypt|bcryptjs|argon2)\.(compare|hash|verify)$|jwt\.(sign|verify)$|passport\.authenticate$/;
    const LOG_RE = /^(console\.(error|warn|log|info)|(logger|log)\.\w+|req\.log\.\w+)$/;
    const event = test || front ? null : (cs.some((c) => AUTH_RE.test(c)) ? "authentication" : (cs.some((c) => WRITE_RE.test(c)) ? "write" : null));
    out.functions.push({
      event, logs: cs.some((c) => LOG_RE.test(c)),
      file, test, frontend: front, name: fnName(n), line: n.getStartLineNumber(),
      cc: cyclomatic(n), cog: cognitive(n), fanout: callees.size,
      loc: n.getEndLineNumber() - n.getStartLineNumber() + 1,
      params: n.getParameters().map((p) => p.getName()),
    });
  });
  // ---- supplementary indicators (test quality, documentation, frontend, static security)
  const SECRET_NAME = /(pass(word|wd)?|secret|token|api[_-]?key|private[_-]?key)$/i;
  const QUERY_FNS = new Set(["find", "findOne", "findOneAndUpdate", "findOneAndDelete", "updateOne", "updateMany", "deleteOne", "deleteMany", "countDocuments"]);
  sf.forEachDescendant((n) => {
    const k = n.getKind();
    const line = n.getStartLineNumber();
    if (test) {
      if (Node.isCallExpression(n) && /^(it|test)$/.test(n.getExpression().getText())) {
        const fnArg = n.getArguments().find((a) => FN_KINDS.has(a.getKind()));
        if (fnArg) out.testCases.push({ file, line, asserts: /\b(assert|expect|should)\b|\.(ok|equal|deepEqual|strictEqual|throws|rejects)\s*\(/.test(fnArg.getText()) });
      }
      return;
    }
    if (FN_KINDS.has(k) && n.getBody && n.getBody()) {
      // documentation: top-level functions and class methods with a preceding JSDoc comment
      let holder = null;
      if (k === SyntaxKind.FunctionDeclaration && n.getParent() === sf) holder = n;
      else if (k === SyntaxKind.MethodDeclaration) holder = n;
      else if (k === SyntaxKind.ArrowFunction || k === SyntaxKind.FunctionExpression) {
        const st = n.getFirstAncestorByKind(SyntaxKind.VariableStatement);
        if (st && st.getParent() === sf) holder = st;
      }
      if (holder) out.docs.push({ file, line, name: fnName(n), documented: holder.getLeadingCommentRanges().some((r) => r.getText().startsWith("/**")) });
      // React components: capitalized function that returns JSX
      if (front && /^[A-Z]/.test(fnName(n) || "") &&
          (n.getDescendantsOfKind(SyntaxKind.JsxElement).length || n.getDescendantsOfKind(SyntaxKind.JsxSelfClosingElement).length || n.getDescendantsOfKind(SyntaxKind.JsxFragment).length)) {
        const p0 = n.getParameters()[0];
        let props = 0;
        if (p0 && Node.isObjectBindingPattern(p0.getNameNode())) props = p0.getNameNode().getElements().length;
        else if (p0) props = new Set([...n.getText().matchAll(new RegExp(p0.getName() + "\\.(\\w+)", "g"))].map((x) => x[1])).size;
        out.components.push({ file, line, name: fnName(n), loc: n.getEndLineNumber() - n.getStartLineNumber() + 1, props });
      }
    }
    if (Node.isCallExpression(n)) {
      const callee = n.getExpression().getText();
      if (front && /^(useEffect|useCallback|useMemo|useLayoutEffect)$/.test(callee))
        out.hooks.push({ file, line, hook: callee, noDeps: n.getArguments().length < 2 });
      if (!front) {
        // fields validated by the input schemas (zod/Joi/yup .object({...}) and express-validator body('field'))
        const a0 = n.getArguments()[0];
        if (/^(z|zod|Joi|joi|yup|Yup)\.object$/.test(callee) && a0 && Node.isObjectLiteralExpression(a0))
          out.validationFields.push({ file, line, fields: a0.getProperties().filter(Node.isPropertyAssignment).map((p) => p.getName().replace(/['"]/g, "")) });
        else if (/^(body|check|query|param)$/.test(callee) && a0 && Node.isStringLiteral(a0))
          out.validationFields.push({ file, line, fields: [a0.getLiteralValue().split(".")[0]] });
      }
      if (callee === "eval") out.security.evalCalls.push({ file, line });
      if (!front && Node.isPropertyAccessExpression(n.getExpression())) {
        // Mongoose queries: model, filter and sort fields, and whether they occur inside a loop (N+1)
        const name = n.getExpression().getName();
        if (QUERY_FNS.has(name) || /^findById/.test(name)) {
          let root_ = n.getExpression();
          while (Node.isPropertyAccessExpression(root_) || Node.isCallExpression(root_)) root_ = root_.getExpression();
          const keys = (o) => {
            if (!o || !Node.isObjectLiteralExpression(o)) return [];
            return o.getProperties().flatMap((p) => {
              if (Node.isShorthandPropertyAssignment(p)) return [p.getName()];
              if (!Node.isPropertyAssignment(p)) return [];
              const k = p.getName().replace(/['"]/g, "");
              if (/^\$(or|and|nor)$/.test(k) && Node.isArrayLiteralExpression(p.getInitializer())) return p.getInitializer().getElements().flatMap(keys);
              return k.startsWith("$") ? [] : [k];
            });
          };
          const sortKeys = [];
          let cur = n;
          while (cur.getParent() && Node.isPropertyAccessExpression(cur.getParent()) && cur.getParent().getParent() && Node.isCallExpression(cur.getParent().getParent())) {
            const call = cur.getParent().getParent();
            if (cur.getParent().getName() === "sort") {
              const s0 = call.getArguments()[0];
              if (s0 && Node.isStringLiteral(s0)) s0.getLiteralValue().split(/\s+/).filter(Boolean).forEach((x) => sortKeys.push(x.replace(/^-/, "")));
              else sortKeys.push(...keys(s0));
            }
            cur = call;
          }
          const inLoop = (() => {
            let c = n.getParent();
            while (c) {
              const kk = c.getKind();
              if ([SyntaxKind.ForStatement, SyntaxKind.ForOfStatement, SyntaxKind.ForInStatement, SyntaxKind.WhileStatement, SyntaxKind.DoStatement].includes(kk)) return true;
              if (FN_KINDS.has(kk)) {
                const par = c.getParent();
                if (par && Node.isCallExpression(par) && Node.isPropertyAccessExpression(par.getExpression()) &&
                    /^(map|forEach|filter|reduce|flatMap|some|every)$/.test(par.getExpression().getName())) { c = par.getParent(); continue; }
                return false;
              }
              c = c.getParent();
            }
            return false;
          })();
          out.queryFields.push({ file, line, model: root_.getText(), call: name,
            fields: /^findById/.test(name) ? ["_id"] : keys(n.getArguments()[0]), sort: sortKeys, inLoop });
        }
      }
      if (Node.isPropertyAccessExpression(n.getExpression()) && QUERY_FNS.has(n.getExpression().getName())) {
        const a0 = n.getArguments()[0];
        if (a0 && /^req\.(body|query|params)$/.test(a0.getText())) out.security.nosqlInjection.push({ file, line, call: callee });
      }
    }
    if (Node.isNewExpression(n) && n.getExpression().getText() === "Function") out.security.evalCalls.push({ file, line });
    if (Node.isPropertyAssignment(n) || Node.isVariableDeclaration(n)) {
      const init = n.getInitializer && n.getInitializer();
      const nm = Node.isPropertyAssignment(n) ? n.getName().replace(/['"]/g, "") : n.getName();
      if (init && Node.isStringLiteral(init) && init.getLiteralValue().length >= 6 && SECRET_NAME.test(nm) && !front)
        out.security.secrets.push({ file, line, name: nm });
    }
  });
  if (test) continue; // the remaining metrics apply to production code

  // ---- classes
  sf.getClasses().forEach((c) => {
    out.classes.push({ file, name: c.getName() || "<anonymous>", line: c.getStartLineNumber(),
      extends: c.getExtends() ? c.getExtends().getExpression().getText() : null });
  });

  sf.forEachDescendant((n) => {
    const k = n.getKind();
    const line = n.getStartLineNumber();
    // ---- switch (CWE-478 / CWE-484)
    if (k === SyntaxKind.SwitchStatement) {
      const clauses = n.getCaseBlock().getClauses();
      if (!clauses.some((c) => Node.isDefaultClause(c))) out.switchesMissingDefault.push({ file, line });
      clauses.forEach((c, i) => {
        const st = c.getStatements();
        if (!st.length || i === clauses.length - 1) return; // stacked empty cases are valid
        const last = st[st.length - 1];
        const terminates = (s) => Node.isBreakStatement(s) || Node.isReturnStatement(s) ||
          Node.isThrowStatement(s) || Node.isContinueStatement(s) ||
          (Node.isBlock(s) && s.getStatements().length && terminates(s.getStatements().at(-1)));
        if (!terminates(last)) out.fallthrough.push({ file, line: c.getStartLineNumber() });
      });
    }
    // ---- labeled jumps (CWE-1075)
    if (k === SyntaxKind.LabeledStatement) out.labeledJumps.push({ file, line });
    if ((k === SyntaxKind.BreakStatement || k === SyntaxKind.ContinueStatement) && n.getLabel && n.getLabel())
      out.labeledJumps.push({ file, line });

    // ---- process.env
    if (Node.isPropertyAccessExpression(n) && /^(process\.env|import\.meta\.env)/.test(n.getText())) {
      out.processEnvAccess++;
      out.envFiles[file] = (out.envFiles[file] || 0) + 1;
    }

    // ---- literals
    if (Node.isStringLiteral(n) || Node.isNoSubstitutionTemplateLiteral(n)) {
      const v = n.getLiteralValue();
      const parent = n.getParent();
      const isModuleSpec = Node.isImportDeclaration(parent) || Node.isExportDeclaration(parent) ||
        (Node.isCallExpression(parent) && /^(require|import)$/.test(parent.getExpression().getText()));
      const isKey = Node.isPropertyAssignment(parent) && parent.getNameNode() === n;
      const isJsxAttr = Node.isJsxAttribute(parent);
      if (!isModuleSpec && !isKey && !isJsxAttr) {
        if (NET_RE.test(v)) out.networkLiterals.push({ file, line, value: v.slice(0, 80), kind: "url/ip", envFallback: ENV_FALLBACK(n) });
        if (v.length >= 4) (out.literalOccurrences[v] ||= []).push(`${file}:${line}`);
      }
    }
    if (Node.isNumericLiteral(n)) {
      const v = Number(n.getLiteralValue());
      const p = n.getParent();
      const isListen = Node.isCallExpression(p) && /\.listen$/.test(p.getExpression().getText());
      if (v >= 1024 && v <= 65535 && (isListen || ENV_FALLBACK(n) || (Node.isPropertyAssignment(p) && /port/i.test(p.getName()))))
        out.networkLiterals.push({ file, line, value: String(v), kind: "port", envFallback: ENV_FALLBACK(n) || false });
    }

    // ---- calls
    if (Node.isCallExpression(n)) {
      const callee = n.getExpression().getText();
      if (!front && /^console\.(log|error|warn|info|debug)$/.test(callee)) out.consoleCalls.push({ file, line });
      // Express routes
      if (!front && /\.populate$/.test(callee)) out.populateCalls.push({ file, line });
      if (Node.isPropertyAccessExpression(n.getExpression())) {
        const m = n.getExpression().getName();
        const a0 = n.getArguments()[0];
        if (["get", "post", "put", "patch", "delete", "all"].includes(m) && a0 &&
            Node.isStringLiteral(a0) && a0.getLiteralValue().startsWith("/") && !front)
          out.routes.push({ file, line, method: m.toUpperCase(), path: a0.getLiteralValue(), validated: VALIDATED(n) });
        if (m === "use" && a0 && Node.isStringLiteral(a0) && !front)
          out.mounts.push({ file, line, path: a0.getLiteralValue() });
        if (m === "route" && a0 && Node.isStringLiteral(a0) && !front) {
          // router.route('/x').get(...).post(...)
          let cur = n.getParent(); const p0 = a0.getLiteralValue();
          while (cur && Node.isPropertyAccessExpression(cur)) {
            const mm = cur.getName(); const call = cur.getParent();
            if (["get", "post", "put", "patch", "delete"].includes(mm))
              out.routes.push({ file, line, method: mm.toUpperCase(), path: p0, validated: VALIDATED(n.getParent().getParent() || n) });
            cur = call && call.getParent();
          }
        }
      }
    }

    // ---- catch
    if (k === SyntaxKind.CatchClause && !front) {
      out.catchBlocks.total++;
      const txt = n.getBlock().getText();
      const logs = /\b(console\.(error|warn|log)|logger\.\w+|log\.\w+|winston|pino)\b/.test(txt);
      const deleg = /\bnext\s*\(|\bthrow\b/.test(txt);
      if (logs) out.catchBlocks.logging++;
      else if (deleg) out.catchBlocks.delegating++;
      else out.catchBlocks.silent.push({ file, line });
    }

    // ---- error middleware (err, req, res, next)
    if (FN_KINDS.has(k) && n.getParameters && n.getParameters().length === 4 &&
        /^_?err(or)?$/i.test(n.getParameters()[0].getName()) && !front)
      out.errorMiddleware.push({ file, line });

    // ---- Mongoose Schema
    if (Node.isNewExpression(n) && /(^|\.)Schema$/.test(n.getExpression().getText()) && !front) {
      const arg = n.getArguments()[0];
      const s = { file, line, name: null, fields: 0, required: 0, validated: 0, refs: 0, embedded: 0, indexedFields: 0, schemaIndexCalls: 0, timestamps: false, fieldTypes: {} };
      if (arg && Node.isObjectLiteralExpression(arg)) {
        arg.getProperties().forEach((p) => {
          if (!Node.isPropertyAssignment(p)) return;
          s.fields++;
          const init = p.getInitializer();
          const txt = init ? init.getText() : "";
          const tm = txt.match(/^\[?\s*\{?\s*(?:type\s*:\s*)?\[?\s*(String|Number|Boolean|Date|Buffer|Map|Mixed|Decimal128|(?:mongoose\.)?Schema\.Types\.\w+|ObjectId)\b/);
          if (tm) s.fieldTypes[p.getName().replace(/['"]/g, "")] = tm[1].replace(/^(mongoose\.)?Schema\.Types\./, "") + (txt.trim().startsWith("[") ? "[]" : "");
          if (/\brequired\s*:/.test(txt)) s.required++;
          if (/\b(enum|min|max|minlength|maxlength|match|validate|minLength|maxLength)\s*:/.test(txt)) s.validated++;
          if (/\bref\s*:/.test(txt)) s.refs++;
          if (/\b(index|unique)\s*:\s*true/.test(txt)) s.indexedFields++;
          if (init && (Node.isArrayLiteralExpression(init) && /\{|Schema/.test(txt))) s.embedded++;
        });
      }
      const opt = n.getArguments()[1];
      if (opt && /timestamps\s*:\s*true/.test(opt.getText())) s.timestamps = true;
      const decl = n.getFirstAncestorByKind(SyntaxKind.VariableDeclaration);
      s.name = decl ? decl.getName() : null;
      out.schemas.push(s);
    }
  });
  // schema.index({...}) and mongoose.model('Name')
  const txt = sf.getFullText();
  const idxCalls = (txt.match(/\.\s*index\s*\(\s*\{/g) || []).length;
  if (idxCalls) out.schemas.filter((s) => s.file === file).forEach((s) => (s.schemaIndexCalls = idxCalls));
}

fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log(`AST: ${out.files.length} files, ${out.functions.length} functions → ${outFile}`);
