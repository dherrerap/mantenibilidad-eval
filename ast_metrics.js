#!/usr/bin/env node
/**
 * ast_metrics.js — Structural AST metrics (ts-morph) for the maintainability
 * evaluation framework. Processes the JS/JSX/TS/TSX files of a PERN application.
 *
 * Usage: node ast_metrics.js <app_directory> <output.json>
 *
 * Produces, among others: cyclomatic complexity and fan-out per function,
 * class hierarchies, switch without default / fall-through (CWE-478/484),
 * labeled jumps (CWE-1075), network literals (CWE-1051) and duplicates
 * (CWE-1052), console.*, catch blocks, error middleware, Express routes and
 * the raw material of the relational schema: Sequelize models, associations and
 * migrations (queryInterface.*), raw SQL strings and query filters (`where`).
 * The schema itself is assembled and normalized by relational_schema.py.
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
  errorMiddleware: [], routes: [], mounts: [],
  sequelize: { models: [], associations: [], migrations: [] }, sqlStrings: [],
  testCases: [], docs: [], components: [], hooks: [], security: { evalCalls: [], secrets: [], sqlInjection: [] },
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
const NET_RE = /^(https?|postgres(ql)?|mysql|redis|amqps?|ftp|wss?):\/\/|(^|[^\w.])localhost\b|\b(\d{1,3}\.){3}\d{1,3}\b/i;


// ───────── relational schema extraction (Sequelize models/migrations, raw SQL) ─────────
/** Property name of an object literal member as plain text; computed names keep their brackets: "[Op.or]". */
const propName = (nameNode) => (Node.isStringLiteral(nameNode) || Node.isNoSubstitutionTemplateLiteral(nameNode)
  ? nameNode.getLiteralValue() : nameNode.getText());

/** Converts a JS expression into JSON: literals and object/array literals are evaluated; anything else
 *  (Sequelize.STRING(100), DataTypes.NOW, a model reference…) becomes {$expr: "<source text>"}. */
function lit(n, depth = 0) {
  if (!n) return null;
  if (depth > 8) return { $expr: n.getText().slice(0, 160) };
  if (Node.isParenthesizedExpression(n) || Node.isAsExpression(n) || Node.isAwaitExpression(n)) return lit(n.getExpression(), depth + 1);
  if (Node.isObjectLiteralExpression(n)) {
    const o = {};
    for (const p of n.getProperties()) {
      if (Node.isPropertyAssignment(p)) o[propName(p.getNameNode())] = lit(p.getInitializer(), depth + 1);
      else if (Node.isShorthandPropertyAssignment(p)) o[p.getName()] = { $expr: p.getName() };
      else if (Node.isSpreadAssignment(p)) (o.$spread ||= []).push(p.getExpression().getText().slice(0, 80));
      else if (Node.isMethodDeclaration(p) || Node.isGetAccessor(p) || Node.isSetAccessor(p)) o[p.getName()] = { $expr: "function" };
    }
    return o;
  }
  if (Node.isArrayLiteralExpression(n)) return n.getElements().map((e) => lit(e, depth + 1));
  if (Node.isStringLiteral(n) || Node.isNoSubstitutionTemplateLiteral(n)) return n.getLiteralValue();
  if (Node.isNumericLiteral(n)) return Number(n.getLiteralValue());
  if (Node.isPrefixUnaryExpression(n) && n.getOperatorToken() === SyntaxKind.MinusToken && Node.isNumericLiteral(n.getOperand())) return -Number(n.getOperand().getLiteralValue());
  const k = n.getKind();
  if (k === SyntaxKind.TrueKeyword) return true;
  if (k === SyntaxKind.FalseKeyword) return false;
  if (k === SyntaxKind.NullKeyword) return null;
  return { $expr: n.getText().slice(0, 160) };
}

const MIG_FNS = new Set(["createTable", "dropTable", "addColumn", "removeColumn", "changeColumn", "renameColumn", "renameTable",
  "addConstraint", "removeConstraint", "addIndex", "removeIndex"]);
const ASSOC_FNS = new Set(["belongsTo", "hasMany", "hasOne", "belongsToMany"]);
const SQL_START = /^\s*(select\s[\s\S]+\sfrom\s|insert\s+into\s|update\s+\S+\s+set\s|delete\s+from\s|create\s+(unique\s+)?(table|index)\s|alter\s+table\s|drop\s+(table|index)\s|with\s[\s\S]+\sselect\s)/i;

/** Name of the model an expression refers to: `User`, `models.User`, `db.User`, `this` (inside a class). */
function modelRef(expr) {
  if (!expr) return null;
  if (expr.getKind() === SyntaxKind.ThisKeyword || expr.getKind() === SyntaxKind.SuperKeyword) {
    const cls = expr.getFirstAncestorByKind(SyntaxKind.ClassDeclaration) || expr.getFirstAncestorByKind(SyntaxKind.ClassExpression);
    return cls && cls.getName ? cls.getName() || null : null;
  }
  if (Node.isIdentifier(expr)) return expr.getText();
  if (Node.isPropertyAccessExpression(expr)) return expr.getName();
  return null;
}

/** Is `n` inside the `down` half of a migration? Those calls undo the schema and are ignored. */
function inDown(n) {
  for (let c = n.getParent(); c; c = c.getParent()) {
    if ((Node.isMethodDeclaration(c) || Node.isPropertyAssignment(c)) && c.getName() === "down") return true;
    if (Node.isBinaryExpression(c) && /\.down$/.test(c.getLeft().getText())) return true;
  }
  return false;
}

function relational(n, file, line) {
  // raw SQL strings (DDL for migrations and queries for filter analysis)
  if (Node.isStringLiteral(n) || Node.isNoSubstitutionTemplateLiteral(n) || Node.isTemplateExpression(n)) {
    const parent = n.getParent();
    if (Node.isTemplateSpan && parent && Node.isTemplateSpan(parent)) return;
    let text;
    if (Node.isTemplateExpression(n)) text = n.getHead().getLiteralText() + n.getTemplateSpans().map((sp) => "$?" + sp.getLiteral().getLiteralText()).join("");
    else text = n.getLiteralValue();
    if (text.length > 12 && SQL_START.test(text))
      out.sqlStrings.push({ file, line, text: text.slice(0, 6000), interpolated: Node.isTemplateExpression(n), migration: /(^|\/)migrations?\//.test(file) });
    return;
  }
  if (!Node.isCallExpression(n) || !Node.isPropertyAccessExpression(n.getExpression())) return;
  const callee = n.getExpression(), method = callee.getName(), args = n.getArguments();
  // migrations: queryInterface.createTable / addColumn / addConstraint / addIndex …
  if (MIG_FNS.has(method) && args.length >= 1 && (/queryInterface|\bqi\b/i.test(callee.getExpression().getText()) || /(^|\/)migrations?\//.test(file))) {
    if (!inDown(n)) out.sequelize.migrations.push({ file, line, method, args: args.slice(0, 3).map((a) => lit(a)) });
    return;
  }
  // models: sequelize.define('Name', attrs, opts)  |  Model.init(attrs, { sequelize, ... })
  const isDefine = method === "define" && args.length >= 2 && Node.isStringLiteral(args[0]) && Node.isObjectLiteralExpression(args[1]);
  const isInit = method === "init" && args.length >= 2 && Node.isObjectLiteralExpression(args[0]) && Node.isObjectLiteralExpression(args[1]) && !!args[1].getProperty("sequelize");
  if (isDefine || isInit) {
    const decl = n.getFirstAncestorByKind(SyntaxKind.VariableDeclaration);
    const opts = lit(isDefine ? args[2] : args[1]) || {};
    const owner = isInit ? modelRef(callee.getExpression()) : null;
    out.sequelize.models.push({ file, line, kind: isDefine ? "define" : "init",
      variable: isInit ? owner : (decl ? decl.getName() : null),
      modelName: isDefine ? args[0].getLiteralValue() : (typeof opts.modelName === "string" ? opts.modelName : owner),
      attributes: lit(isDefine ? args[1] : args[0]), options: opts });
    return;
  }
  // associations: A.belongsTo(B, {...}) …
  if (ASSOC_FNS.has(method) && args.length >= 1) {
    out.sequelize.associations.push({ file, line, kind: method, source: modelRef(callee.getExpression()), target: modelRef(args[0]),
      options: args[1] && Node.isObjectLiteralExpression(args[1]) ? lit(args[1]) : {} });
  }
}

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
    const WRITE_RE = /^(?!Object\.|Array\.|Promise\.|document\.).*\b(save|create|bulkCreate|update|destroy|upsert|findOrCreate|increment|decrement)$/;
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
  // Sequelize model methods that take a `where`: index of the options argument that holds it
  const QUERY_FNS = { findOne: 0, findAll: 0, findAndCountAll: 0, findOrCreate: 0, findCreateFind: 0, count: 0, max: 1, min: 1, sum: 1, update: 1, destroy: 0 };
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
        // Sequelize queries: model, `where` and `order` fields, and whether they occur inside a loop (N+1)
        const name = n.getExpression().getName();
        if (Object.prototype.hasOwnProperty.call(QUERY_FNS, name)) {
          const obj = n.getExpression().getExpression();
          const model = Node.isPropertyAccessExpression(obj) ? obj.getName() : (Node.isIdentifier(obj) ? obj.getText() : null);
          const opt = n.getArguments()[QUERY_FNS[name]];
          const optProps = opt && Node.isObjectLiteralExpression(opt) ? opt : null;
          const prop = (o, k) => {
            const p = o && o.getProperty(k);
            if (!p) return null;
            return Node.isShorthandPropertyAssignment(p) ? { dynamic: true } : (Node.isPropertyAssignment(p) ? p.getInitializer() : null);
          };
          // `where` keys; Op.or / Op.and / Op.not (computed names) are walked, any other operator is skipped
          const whereKeys = (w) => {
            if (Node.isArrayLiteralExpression(w)) return w.getElements().flatMap(whereKeys);
            if (!w || !Node.isObjectLiteralExpression(w)) return [];
            return w.getProperties().flatMap((p) => {
              if (Node.isShorthandPropertyAssignment(p)) return [p.getName()];
              if (!Node.isPropertyAssignment(p)) return [];
              const nameNode = p.getNameNode();
              if (Node.isComputedPropertyName(nameNode)) return /Op\.(or|and|not)\]?$/.test(nameNode.getText()) ? whereKeys(p.getInitializer()) : [];
              const k = nameNode.getText().replace(/['"]/g, "");
              return k.startsWith("$") ? [] : [k]; // '$assoc.col$' refers to a joined table
            });
          };
          const w = optProps ? prop(optProps, "where") : null;
          const dynamic = !!(w && (w.dynamic || !Node.isObjectLiteralExpression(w))) || (!optProps && !!opt);
          const order = optProps ? prop(optProps, "order") : null;
          const sortKeys = [];
          if (order && Node.isArrayLiteralExpression(order)) {
            order.getElements().forEach((e) => {
              const first = Node.isArrayLiteralExpression(e) ? e.getElements()[0] : e;
              if (first && Node.isStringLiteral(first)) sortKeys.push(first.getLiteralValue());
            });
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
          if (model) out.queryFields.push({ file, line, model, call: name, fields: w && !w.dynamic ? whereKeys(w) : [], sort: sortKeys, inLoop, dynamic });
        }
        // raw SQL built by interpolation or concatenation: injectable (parameters/replacements are the safe form)
        if (/^(query|raw|execute|unsafe)$/.test(name)) {
          const a0 = n.getArguments()[0];
          const SQL_HEAD = /^\s*(select|insert|update|delete|with|create|alter|drop)\b/i;
          const interpolated = a0 && Node.isTemplateExpression(a0) && SQL_HEAD.test(a0.getHead().getLiteralText());
          const concatenated = a0 && Node.isBinaryExpression(a0) && a0.getOperatorToken().getKind() === SyntaxKind.PlusToken &&
            SQL_HEAD.test(a0.getLeft().getText().replace(/^['"`]/, "")) && !Node.isStringLiteral(a0.getRight());
          if (interpolated || concatenated) out.security.sqlInjection.push({ file, line, call: callee });
        }
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

    // ---- relational schema material (Sequelize + raw SQL); interpreted by relational_schema.py
    if (!front) relational(n, file, line);
  });
}

fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log(`AST: ${out.files.length} files, ${out.functions.length} functions → ${outFile}`);
