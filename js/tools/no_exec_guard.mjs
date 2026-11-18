/**
 * no_exec_guard.mjs — Preloaded with `node --import` before a tool that only has to READ the app (Knip): any attempt to execute a
 * file under NO_EXEC_ROOT throws, so the app's configuration files (vite.config.js, jest.config.js…) are never run. The tool then
 * logs a load error and keeps its static analysis.
 *
 * Three ways a file can be executed are blocked: ESM import (a module customization hook), CommonJS `require`
 * (Module.prototype._compile) and code evaluated through `vm` with a filename (what jiti does for TypeScript and ESM).
 */
import Module, { register } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";

const root = process.env.NO_EXEC_ROOT && path.resolve(process.env.NO_EXEC_ROOT);
if (root) {
  const inside = (file) => {
    if (!file) return false;
    let p = String(file);
    try {
      if (p.startsWith("file:")) p = fileURLToPath(p.split("?")[0]);
    } catch {
      return false;
    }
    const rel = path.relative(root, path.resolve(p));
    return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
  };
  const refuse = (file) => {
    const e = new Error(`no_exec_guard: refused to execute ${file}`);
    e.code = "NO_EXEC_GUARD";
    throw e;
  };

  const compile = Module.prototype._compile;
  Module.prototype._compile = function (content, filename) {
    if (inside(filename)) refuse(filename);
    return compile.call(this, content, filename);
  };

  const fname = (o) => (typeof o === "string" ? o : o && o.filename);
  const run = vm.runInThisContext;
  vm.runInThisContext = function (code, options) {
    if (inside(fname(options))) refuse(fname(options));
    return run.call(this, code, options);
  };
  const Script = vm.Script;
  vm.Script = class extends Script {
    constructor(code, options) {
      if (inside(fname(options))) refuse(fname(options));
      super(code, options);
    }
  };
  const compileFunction = vm.compileFunction;
  vm.compileFunction = function (code, params, options) {
    if (inside(fname(options))) refuse(fname(options));
    return compileFunction.call(this, code, params, options);
  };

  register(new URL("./no_exec_guard_hooks.mjs", import.meta.url), { data: { root: pathToFileURL(root + path.sep).href } });
}
