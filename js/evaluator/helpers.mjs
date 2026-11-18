// helpers.mjs — The small pieces of the collectors that the scoring reads: whether ESLint's result is usable, how an occurrence count
// decides a criterion (evaluator/collectors/lint.py), and coerce_version (evaluator/collectors/packages.py).
import { get, or, sorted, truthy } from "../lib/py.mjs";

/** [lint, note]: lint is null when ESLint did not run; note says why, or lists the files ESLint could not parse. */
export function usable(m) {
  const lint = or(get(m, "lint"), {});
  if (!truthy(get(lint, "ok")))
    return [null, "ESLint did not run: " + or(get(lint, "error"), "no lint result in metrics.json (evaluate the app again)").slice(0, 160)];
  const pe = or(get(lint, "parse_errors"), []);
  return [lint, pe.length ? `ESLint could not parse ${pe.length} file(s): ` + sorted([...new Set(pe.map((x) => x.file))]).slice(0, 5).join(", ") : null];
}

/** ok of an occurrence count that must be 0: false with any occurrence, null when ESLint did not run or some file did not parse. */
export function decideCount(n, lint, note) {
  if (lint !== null && n) return false;
  return lint === null || note ? null : true;
}

/** "^1.2" -> "1.2.0"; null for git/http/file/link/workspace specs or no version. */
export function coerceVersion(spec) {
  const s = spec || "";
  const m = /(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?/.exec(s);
  if (!m || /^(git|http|file|link|workspace)/.test(s)) return null;
  return m.slice(1).map((x) => (x && /^\d+$/.test(x) ? x : "0")).join(".");
}
