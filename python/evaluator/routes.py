"""Express routes: full paths through the app.use mounts, matching against the contract, and health-check routes.
"""
import re

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_schema as rs  # noqa: E402


ROOT_OBJECTS = re.compile(r"^(?:app|server|application|api|this\.app)$")  # the Express application itself, not a router


def join_path(*parts):
    return "/" + "/".join(s for p in parts for s in str(p).split("/") if s)


def mount_prefixes(mounts):
    """{router file: [full prefixes]} from the app.use(prefix, router) calls whose router resolved to a file, following nested
    routers (app.use('/api', api) and, inside api, router.use('/orders', orders)). A file nobody mounts is the application root."""
    by_target = {}
    for mt in mounts or []:
        if mt.get("target"):
            by_target.setdefault(mt["target"], []).append(mt)
    memo = {}

    def prefixes(f, seen=()):
        if f not in by_target or f in seen:
            return [""]
        if f not in memo:
            memo[f] = sorted({join_path(p, mt["path"]) for mt in by_target[f] for p in prefixes(mt["file"], seen + (f,))})
        return memo[f]
    return {f: prefixes(f) for f in by_target}


def full_routes(ast):
    """Routes with their full path (`full_path`, mount prefixes included) and whether that path is certain (`resolved`): the file
    is mounted through a resolved app.use, or the route is declared on the application object itself."""
    pref = mount_prefixes(ast.get("mounts"))
    out = []
    for r in ast.get("routes", []):
        if r["file"] in pref:
            out += [{**r, "full_path": join_path(p, r["path"]), "resolved": True} for p in pref[r["file"]]]
        else:
            out.append({**r, "full_path": join_path(r["path"]), "resolved": bool(ROOT_OBJECTS.match(str(r.get("obj", ""))))})
    return out


def norm_route(p):
    """Path with every parameter (:id, {orderId}) generalized to {} so that parameter names do not matter."""
    return join_path(*[("{}" if s.startswith(":") or (s.startswith("{") and s.endswith("}")) else s) for s in str(p).split("/") if s])


def route_match(contract_paths, route, bases=()):
    """Does the contract declare this route? Exact match of method and normalized full path, the contract's paths taken alone
    or under one of its base paths (servers[].url / basePath). Only when the route's prefix is unknown (its router was mounted in a
    way the analysis could not resolve) a match of whole trailing segments is accepted."""
    r = norm_route(route.get("full_path", route["path"]))
    for meth, p in contract_paths:
        if meth != route["method"]:
            continue
        cands = {norm_route(p)} | {norm_route(join_path(b, p)) for b in bases or ()}
        if r in cands:
            return True
        if not route.get("resolved"):
            rs = r.split("/")[1:]
            for c in cands:
                cs = c.split("/")[1:]
                n = min(len(rs), len(cs))
                if n and rs[-n:] == cs[-n:]:
                    return True
    return False


HEALTH_SEGMENTS = {"health", "healthz", "healthcheck", "health-check", "ready", "readyz", "readiness", "live", "livez", "liveness",
                   "ping", "status", "metrics"}


def is_health_route(path):
    """A health, readiness or metrics endpoint: its last segment is one of HEALTH_SEGMENTS and it has no parameters, so that a
    resource sub-route such as PATCH /orders/:id/status (required by the e-commerce spec) is not taken for one."""
    segs = [s for s in str(path).lower().split("/") if s]
    return bool(segs) and segs[-1] in HEALTH_SEGMENTS and not any(s.startswith(":") or "{" in s for s in segs) and len(segs) <= 3
