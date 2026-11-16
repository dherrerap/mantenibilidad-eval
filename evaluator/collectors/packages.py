"""Packages: package.json manifests, unused dependencies (depcheck), npm registry versions and deprecations,
vulnerabilities (npm audit), supported runtime versions (endoflife.date) and PostgreSQL images of docker-compose.
"""
import datetime
import json
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import pg_runtime  # noqa: E402
from evaluator.common import BIN, RUBRIC, rel, sh, walk


def find_packages(app):
    return sorted({p.parent for p in walk(app) if p.name == "package.json"})


def read_pkg(d):
    try:
        return json.loads((d / "package.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_depcheck(pkgdir, include_dev):
    rc, so, se = sh([str(BIN / "depcheck"), str(pkgdir), "--json"], timeout=300)
    try:
        d = json.loads(so)
    except Exception:
        return None
    unused = list(d.get("dependencies", []))
    if include_dev:
        unused += d.get("devDependencies", [])
    return unused


def coerce_version(spec):
    m = re.search(r"(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?", spec or "")
    if not m or re.match(r"^(git|http|file|link|workspace)", spec or ""):
        return None
    return ".".join(x if (x and x.isdigit()) else "0" for x in m.groups())


def npm_view(args):
    pkg, spec = args
    base = coerce_version(spec)
    r = {"pkg": pkg, "spec": spec, "base": base, "latest": None, "deprecated": None}
    rc, so, _ = sh(["npm", "view", pkg, "dist-tags.latest", "--json"], timeout=60)
    if rc == 0:
        try:
            r["latest"] = json.loads(so)
        except Exception:
            pass
    if base:
        rc, so, _ = sh(["npm", "view", f"{pkg}@{base}", "deprecated", "--json"], timeout=60)
        if rc == 0 and so.strip():
            try:
                r["deprecated"] = json.loads(so) or None
            except Exception:
                pass
    return r


def run_audit(pkgdir):
    with tempfile.TemporaryDirectory() as t:
        for fn in ("package.json", "package-lock.json"):
            if (pkgdir / fn).exists():
                shutil.copy(pkgdir / fn, t)
        sh(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=t, timeout=300)
        rc, so, _ = sh(["npm", "audit", "--json"], cwd=t, timeout=120)
    try:
        v = json.loads(so)["metadata"]["vulnerabilities"]
        return {"high": v.get("high", 0), "critical": v.get("critical", 0)}
    except Exception:
        return None


def analyze_packages(app, offline, include_dev_unused):
    res = {"packages": [], "unused": [], "direct": 0, "unused_dev_incl": include_dev_unused,
           "npm": {"ok": False, "items": []}, "audit": {"ok": False, "high": 0, "critical": 0}}
    pairs, ok_dc = [], True
    for d in find_packages(app):
        pkg = read_pkg(d)
        deps = dict(pkg.get("dependencies", {}))
        dev = dict(pkg.get("devDependencies", {}))
        rd = rel(d, app) or "."
        res["packages"].append({"dir": rd, "name": pkg.get("name"), "dependencies": deps, "devDependencies": dev,
                                "scripts": pkg.get("scripts", {}), "engines": pkg.get("engines", {}), "main": pkg.get("main")})
        res["direct"] += len(deps) + (len(dev) if include_dev_unused else 0)
        u = run_depcheck(d, include_dev_unused)
        if u is None:
            ok_dc = False
        else:
            res["unused"] += [f"{rd}:{x}" for x in u]
        pairs += list({**deps, **dev}.items())
    res["depcheck_ok"] = ok_dc
    if offline or not pairs:
        return res
    with ThreadPoolExecutor(8) as ex:
        items = list(ex.map(npm_view, pairs))
    res["npm"] = {"ok": any(i["latest"] for i in items), "items": items}
    hi = cr = 0
    ok = False
    for d in find_packages(app):
        a = run_audit(d)
        if a:
            ok = True
            hi += a["high"]; cr += a["critical"]
    res["audit"] = {"ok": ok, "high": hi, "critical": cr}
    return res


def fetch_eol(offline):
    """Supported major versions according to endoflife.date for the products in rubric.json (supported_runtimes.eol_products: node, react,
    express, postgresql). Offline returns {} and the rubric.json table is used."""
    if offline:
        return {}
    import urllib.request
    today = datetime.date.today().isoformat(); res = {}
    for key, product in RUBRIC["supported_runtimes"]["eol_products"].items():
        try:
            with urllib.request.urlopen(f"https://endoflife.date/api/{product}.json", timeout=15) as r:
                cycles = json.loads(r.read().decode("utf-8"))
            res[key] = sorted({int(c["cycle"].split(".")[0]) for c in cycles
                               if c["eol"] is False or (isinstance(c["eol"], str) and c["eol"] > today)})
        except Exception:
            continue
    return res


def postgres_images(app):
    """PostgreSQL images declared in the app's docker-compose files and their major version: [{file, image, major}].
    `major` is None when the tag does not say it (postgres, postgres:latest, postgres:alpine)."""
    out = []
    for p in walk(app):
        if p.name in pg_runtime.COMPOSE_NAMES:
            for m in re.finditer(r"^\s*image:\s*[\"']?([^\s\"'#]+)", p.read_text(encoding="utf-8", errors="replace"), re.M):
                img = m.group(1)
                if pg_runtime.PG_IMAGE.search(img):
                    tag = img.split(":", 1)[1] if ":" in img.rsplit("/", 1)[-1] else ""
                    mm = re.match(r"(\d+)", tag)
                    out.append({"file": rel(p, app), "image": img, "major": int(mm.group(1)) if mm else None})
    return out
