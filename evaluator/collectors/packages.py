"""Packages: package.json manifests and their dependency counts; for every direct dependency the version the app installs, the
latest version and the age between both (libyear) and its deprecation, from the npm registry; known vulnerabilities of every
installed package (OSV); supported runtime versions (endoflife.date) and PostgreSQL images of docker-compose.

Everything that depends on time is computed as of a reference date (`as_of`, by default the evaluation date): the versions npm
would install, the latest version, the advisories in force and the supported runtimes. Fixing it (for example to the generation
date) makes a re-evaluation give the same result.
"""
import datetime
import json
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import pg_runtime  # noqa: E402
from evaluator.collectors import osv
from evaluator.common import RUBRIC, rel, sh, walk


def find_packages(app):
    return sorted({p.parent for p in walk(app) if p.name == "package.json"})


def read_pkg(d):
    try:
        return json.loads((d / "package.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def coerce_version(spec):
    m = re.search(r"(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?", spec or "")
    if not m or re.match(r"^(git|http|file|link|workspace)", spec or ""):
        return None
    return ".".join(x if (x and x.isdigit()) else "0" for x in m.groups())


STABLE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def today():
    return datetime.date.today().isoformat()


def end_of(as_of):
    return f"{as_of}T23:59:59Z"


def semver_key(v):
    m = STABLE.match(str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def direct_version(lock, name):
    """Version a lockfile installs for a direct dependency (lockfileVersion 2/3 `packages`, or 1 `dependencies`)."""
    return ((lock.get("packages") or {}).get(f"node_modules/{name}") or {}).get("version") or \
        ((lock.get("dependencies") or {}).get(name) or {}).get("version")


def lock_packages(lock):
    """Every package a lockfile installs: [{"name", "version", "dev"}] (transitive ones included; links and the root left out)."""
    out = []
    for key, v in (lock.get("packages") or {}).items():
        if key and v.get("version") and not v.get("link") and "node_modules/" in key:
            out.append({"name": v.get("name") or key.rsplit("node_modules/", 1)[-1], "version": v["version"], "dev": bool(v.get("dev"))})
    if not lock.get("packages"):  # lockfileVersion 1
        def walk_v1(deps):
            for name, v in (deps or {}).items():
                if v.get("version"):
                    out.append({"name": name, "version": v["version"], "dev": bool(v.get("dev"))})
                walk_v1(v.get("dependencies"))
        walk_v1(lock.get("dependencies"))
    return out


def resolve_lock(d, as_of):
    """(lockfile, source) of a package directory: the app's own package-lock.json when it pins every direct dependency, otherwise
    the one npm resolves now with the registry as it was at `as_of` (`--before`, scripts not run). (None, None) without a network."""
    pkg = read_pkg(d); names = set(pkg.get("dependencies", {})) | set(pkg.get("devDependencies", {}))
    own = d / "package-lock.json"
    if own.exists():
        try:
            lock = json.loads(own.read_text(encoding="utf-8"))
            if all(direct_version(lock, n) for n in names):
                return lock, "lockfile"
        except (OSError, ValueError):
            pass
    with tempfile.TemporaryDirectory() as t:
        shutil.copy(d / "package.json", t)
        sh(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund", f"--before={end_of(as_of)}"], cwd=t, timeout=300)
        try:
            return json.loads((Path(t) / "package-lock.json").read_text(encoding="utf-8")), f"npm as of {as_of}"
        except (OSError, ValueError):
            return None, None


def npm_json(args):
    rc, so, _ = sh(["npm", "view", *args, "--json"], timeout=60)
    if rc != 0 or not so.strip():
        return None
    try:
        return json.loads(so)
    except ValueError:
        return None


def dependency(item, as_of):
    """Fills a direct dependency with its registry data as of `as_of`: latest stable version published by then, release dates,
    libyear (Cox et al., ICSE 2015: years between the release of the version in use and the release of the latest) and the
    deprecation message of the version in use."""
    end = end_of(as_of)
    times = npm_json([item["pkg"], "time"]) or {}
    stable = [(semver_key(v), v, t) for v, t in times.items() if semver_key(v) and t <= end]
    latest = max(stable)[1] if stable else None
    used = item["resolved"]
    item.update({"latest": latest, "latest_date": times.get(latest), "resolved_date": times.get(used), "libyear": None, "deprecated": None})
    # a version published after as_of: the reference date is earlier than the app (npm could not resolve the range as of then)
    item["after_as_of"] = bool(item["resolved_date"] and item["resolved_date"] > end)
    if item["resolved_date"] and item["latest_date"] and not item["after_as_of"]:
        d0 = datetime.datetime.fromisoformat(item["resolved_date"].replace("Z", "+00:00"))
        d1 = datetime.datetime.fromisoformat(item["latest_date"].replace("Z", "+00:00"))
        item["libyear"] = round(max((d1 - d0).days, 0) / 365.25, 2)
    if used:
        dep = npm_json([f"{item['pkg']}@{used}", "deprecated"])
        item["deprecated"] = dep or None
    return item


def analyze_packages(app, offline, include_dev_unused, as_of=None):
    """Manifests, and unless offline the registry data of every direct dependency and the vulnerabilities of every installed package
    (both as of `as_of`, default today)."""
    as_of = as_of or today()
    # unused dependencies are measured by Knip (evaluator/collectors/knip.py); `direct` is the denominator of coupling.C4
    res = {"packages": [], "direct": 0, "unused_dev_incl": include_dev_unused, "as_of": as_of,
           "npm": {"ok": False, "items": []}, "vulnerabilities": {"ok": False, "source": "OSV", "as_of": as_of}}
    items, installed = [], []
    for d in find_packages(app):
        pkg = read_pkg(d)
        deps = dict(pkg.get("dependencies", {}))
        dev = dict(pkg.get("devDependencies", {}))
        rd = rel(d, app) or "."
        res["packages"].append({"dir": rd, "name": pkg.get("name"), "dependencies": deps, "devDependencies": dev,
                                "scripts": pkg.get("scripts", {}), "engines": pkg.get("engines", {}), "main": pkg.get("main")})
        res["direct"] += len(deps) + (len(dev) if include_dev_unused else 0)
        if offline:
            continue
        lock, source = resolve_lock(d, as_of)
        res["packages"][-1]["lock_source"] = source
        if lock:
            installed += lock_packages(lock)
        for group, specs in (("dependencies", deps), ("devDependencies", dev)):
            for name, spec in specs.items():
                v = direct_version(lock, name) if lock else None
                items.append({"pkg": name, "spec": spec, "dir": rd, "dev": group == "devDependencies",
                              "resolved": v or coerce_version(spec), "resolved_source": source if v else "range lower bound"})
    if offline or not items:
        return res
    with ThreadPoolExecutor(8) as ex:
        items = list(ex.map(lambda i: dependency(i, as_of), items))
    res["npm"] = {"ok": any(i["latest"] for i in items), "items": items}
    if installed:
        res["vulnerabilities"] = osv.vulnerabilities(installed, as_of)
    return res


def fetch_eol(offline, as_of=None):
    """Supported major versions according to endoflife.date for the products in rubric.json (supported_runtimes.eol_products: node, react,
    express, postgresql) as of `as_of` (default today): released by then and not yet at end of life. Offline returns {} and the
    rubric.json table is used."""
    if offline:
        return {}
    import urllib.request
    day = as_of or today(); res = {}
    for key, product in RUBRIC["supported_runtimes"]["eol_products"].items():
        try:
            with urllib.request.urlopen(f"https://endoflife.date/api/{product}.json", timeout=15) as r:
                cycles = json.loads(r.read().decode("utf-8"))
            res[key] = sorted({int(c["cycle"].split(".")[0]) for c in cycles
                               if (c["eol"] is False or (isinstance(c["eol"], str) and c["eol"] > day))
                               and str(c.get("releaseDate") or "") <= day})
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
