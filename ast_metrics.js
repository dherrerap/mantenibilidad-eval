#!/usr/bin/env node
/**
 * ast_metrics.js — Métricas estructurales por AST (ts-morph) para el marco de
 * evaluación de mantenibilidad. Procesa JS/JSX/TS/TSX de una aplicación MERN.
 *
 * Uso: node ast_metrics.js <directorio_app> <salida.json>
 *
 * Produce, entre otros: complejidad ciclomática y fan-out por función,
 * jerarquías de clases, switch sin default / fall-through (CWE-478/484),
 * saltos con etiqueta (CWE-1075), literales de red (CWE-1051) y duplicados
 * (CWE-1052), console.*, bloques catch, middleware de errores, rutas Express
 * y esquemas Mongoose.
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

/** Recorre descendientes sin entrar a funciones anidadas (como ESLint/complexity). */
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
  // Valores por defecto de parámetros también ramifican (ESLint ≥ 9)
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
      return `<callback de ${callee.slice(0, 40)}>`;
    }
  }
  return "<anónima>";
}

const normCallee = (t) => t.replace(/\([^()]*\)/g, "()").replace(/\s+/g, "").slice(0, 80);

const out = {
  root, files: [], functions: [], classes: [],
  switchesMissingDefault: [], fallthrough: [], labeledJumps: [],
  consoleCalls: [], networkLiterals: [], literalOccurrences: {},
  catchBlocks: { total: 0, logging: 0, delegating: 0, silent: [] },
  errorMiddleware: [], routes: [], mounts: [], schemas: [],
  processEnvAccess: 0, envFiles: {}, imports: [],
};

const ENV_FALLBACK = (n) => {
  const p = n.getParent();
  return p && Node.isBinaryExpression(p) &&
    [SyntaxKind.BarBarToken, SyntaxKind.QuestionQuestionToken].includes(p.getOperatorToken().getKind()) &&
    /process\.env|import\.meta\.env/.test(p.getLeft().getText());
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

  // ---- funciones
  sf.getDescendants().forEach((n) => {
    if (!FN_KINDS.has(n.getKind())) return;
    if (!n.getBody || !n.getBody()) return; // overloads / abstractos
    const callees = new Set();
    const b = n.getBody();
    const addCall = (c) => { if (Node.isCallExpression(c)) callees.add(normCallee(c.getExpression().getText())); };
    addCall(b); walkOwn(b, addCall);
    out.functions.push({
      file, test, frontend: front, name: fnName(n), line: n.getStartLineNumber(),
      cc: cyclomatic(n), fanout: callees.size,
      loc: n.getEndLineNumber() - n.getStartLineNumber() + 1,
      params: n.getParameters().map((p) => p.getName()),
    });
  });
  if (test) continue; // el resto de métricas aplica a código de producción

  // ---- clases
  sf.getClasses().forEach((c) => {
    out.classes.push({ file, name: c.getName() || "<anónima>", line: c.getStartLineNumber(),
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
        if (!st.length || i === clauses.length - 1) return; // casos vacíos apilados son válidos
        const last = st[st.length - 1];
        const terminates = (s) => Node.isBreakStatement(s) || Node.isReturnStatement(s) ||
          Node.isThrowStatement(s) || Node.isContinueStatement(s) ||
          (Node.isBlock(s) && s.getStatements().length && terminates(s.getStatements().at(-1)));
        if (!terminates(last)) out.fallthrough.push({ file, line: c.getStartLineNumber() });
      });
    }
    // ---- saltos con etiqueta (CWE-1075)
    if (k === SyntaxKind.LabeledStatement) out.labeledJumps.push({ file, line });
    if ((k === SyntaxKind.BreakStatement || k === SyntaxKind.ContinueStatement) && n.getLabel && n.getLabel())
      out.labeledJumps.push({ file, line });

    // ---- process.env
    if (Node.isPropertyAccessExpression(n) && /^(process\.env|import\.meta\.env)/.test(n.getText())) {
      out.processEnvAccess++;
      out.envFiles[file] = (out.envFiles[file] || 0) + 1;
    }

    // ---- literales
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
        out.networkLiterals.push({ file, line, value: String(v), kind: "puerto", envFallback: ENV_FALLBACK(n) || false });
    }

    // ---- llamadas
    if (Node.isCallExpression(n)) {
      const callee = n.getExpression().getText();
      if (!front && /^console\.(log|error|warn|info|debug)$/.test(callee)) out.consoleCalls.push({ file, line });
      // rutas Express
      if (Node.isPropertyAccessExpression(n.getExpression())) {
        const m = n.getExpression().getName();
        const a0 = n.getArguments()[0];
        if (["get", "post", "put", "patch", "delete", "all"].includes(m) && a0 &&
            Node.isStringLiteral(a0) && a0.getLiteralValue().startsWith("/") && !front)
          out.routes.push({ file, line, method: m.toUpperCase(), path: a0.getLiteralValue() });
        if (m === "use" && a0 && Node.isStringLiteral(a0) && !front)
          out.mounts.push({ file, line, path: a0.getLiteralValue() });
        if (m === "route" && a0 && Node.isStringLiteral(a0) && !front) {
          // router.route('/x').get(...).post(...)
          let cur = n.getParent(); const p0 = a0.getLiteralValue();
          while (cur && Node.isPropertyAccessExpression(cur)) {
            const mm = cur.getName(); const call = cur.getParent();
            if (["get", "post", "put", "patch", "delete"].includes(mm))
              out.routes.push({ file, line, method: mm.toUpperCase(), path: p0 });
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

    // ---- middleware de errores (err, req, res, next)
    if (FN_KINDS.has(k) && n.getParameters && n.getParameters().length === 4 &&
        /^_?err(or)?$/i.test(n.getParameters()[0].getName()) && !front)
      out.errorMiddleware.push({ file, line });

    // ---- Mongoose Schema
    if (Node.isNewExpression(n) && /(^|\.)Schema$/.test(n.getExpression().getText()) && !front) {
      const arg = n.getArguments()[0];
      const s = { file, line, name: null, fields: 0, required: 0, validated: 0, refs: 0, embedded: 0, indexedFields: 0, schemaIndexCalls: 0, timestamps: false };
      if (arg && Node.isObjectLiteralExpression(arg)) {
        arg.getProperties().forEach((p) => {
          if (!Node.isPropertyAssignment(p)) return;
          s.fields++;
          const init = p.getInitializer();
          const txt = init ? init.getText() : "";
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
  // schema.index({...}) y mongoose.model('Nombre')
  const txt = sf.getFullText();
  const idxCalls = (txt.match(/\.\s*index\s*\(\s*\{/g) || []).length;
  if (idxCalls) out.schemas.filter((s) => s.file === file).forEach((s) => (s.schemaIndexCalls = idxCalls));
}

fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
console.log(`AST: ${out.files.length} archivos, ${out.functions.length} funciones → ${outFile}`);
