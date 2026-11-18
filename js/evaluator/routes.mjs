// routes.mjs — Express routes: full paths through the app.use mounts, matching against the contract, and health-check routes.
// Port of evaluator/routes.py.
import { get, sorted, str } from "../lib/py.mjs";

const ROOT_OBJECTS = /^(?:app|server|application|api|this\.app)$/;  // the Express application itself, not a router

export const joinPath = (...parts) => "/" + parts.flatMap((p) => str(p).split("/")).filter(Boolean).join("/");

/** {router file: [full prefixes]} from the app.use(prefix, router) calls whose router resolved to a file, following nested routers. */
export function mountPrefixes(mounts) {
  const byTarget = new Map();
  for (const mt of mounts || []) {
    if (!get(mt, "target")) continue;
    if (!byTarget.has(mt.target)) byTarget.set(mt.target, []);
    byTarget.get(mt.target).push(mt);
  }
  const memo = new Map();
  const prefixes = (f, seen = []) => {
    if (!byTarget.has(f) || seen.includes(f)) return [""];
    if (!memo.has(f)) memo.set(f, sorted([...new Set(byTarget.get(f).flatMap((mt) => prefixes(mt.file, [...seen, f]).map((p) => joinPath(p, mt.path))))]));
    return memo.get(f);
  };
  return Object.fromEntries([...byTarget.keys()].map((f) => [f, prefixes(f)]));
}

/** Routes with their full path (`full_path`) and whether that path is certain (`resolved`). */
export function fullRoutes(ast) {
  const pref = mountPrefixes(get(ast, "mounts"));
  const out = [];
  for (const r of get(ast, "routes", [])) {
    if (Object.prototype.hasOwnProperty.call(pref, r.file)) for (const p of pref[r.file]) out.push({ ...r, full_path: joinPath(p, r.path), resolved: true });
    else out.push({ ...r, full_path: joinPath(r.path), resolved: ROOT_OBJECTS.test(str(get(r, "obj", ""))) });
  }
  return out;
}

/** Path with every parameter (:id, {orderId}) generalized to {}. */
export const normRoute = (p) => joinPath(...str(p).split("/").filter(Boolean).map((s) => (s.startsWith(":") || (s.startsWith("{") && s.endsWith("}")) ? "{}" : s)));

/** Does the contract declare this route? (see routes.py) */
export function routeMatch(contractPaths, route, bases = []) {
  const r = normRoute(get(route, "full_path", route.path));
  for (const [meth, p] of contractPaths) {
    if (meth !== route.method) continue;
    const cands = new Set([normRoute(p), ...(bases || []).map((b) => normRoute(joinPath(b, p)))]);
    if (cands.has(r)) return true;
    if (!get(route, "resolved")) {
      const rs = r.split("/").slice(1);
      for (const c of cands) {
        const cs = c.split("/").slice(1);
        const n = Math.min(rs.length, cs.length);
        if (n && rs.slice(-n).every((x, i) => x === cs.slice(-n)[i])) return true;
      }
    }
  }
  return false;
}

const HEALTH_SEGMENTS = new Set(["health", "healthz", "healthcheck", "health-check", "ready", "readyz", "readiness", "live", "livez", "liveness", "ping", "status", "metrics"]);

/** A health, readiness or metrics endpoint: last segment in HEALTH_SEGMENTS, no parameters, at most 3 segments. */
export function isHealthRoute(p) {
  const segs = str(p).toLowerCase().split("/").filter(Boolean);
  return segs.length > 0 && HEALTH_SEGMENTS.has(segs.at(-1)) && !segs.some((s) => s.startsWith(":") || s.includes("{")) && segs.length <= 3;
}
