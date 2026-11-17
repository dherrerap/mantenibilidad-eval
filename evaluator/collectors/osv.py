"""Known vulnerabilities of the exact package versions an app installs, from OSV (https://osv.dev, which carries the GitHub Advisory
Database that `npm audit` also uses), as of a reference date.

`npm audit` only answers for today's advisory database. OSV records carry their publication and withdrawal dates, so the count can be
fixed at the reference date of the experiment (`as_of`): an advisory published after it is not counted, which makes a re-evaluation
months later give the same result. The severity is the one the record has today (GitHub's `database_specific.severity`).

Only package names and versions are sent to the service, never code or paths of the app.
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://api.osv.dev/v1"
BATCH = 500  # querybatch accepts up to 1000 queries


def post(url, body, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def query_ids(pkgs):
    """{(name, version): [vulnerability ids]} for [(name, version)] (paginated per query when OSV says so)."""
    out = {}
    pending = [{"package": {"name": n, "ecosystem": "npm"}, "version": v} for n, v in pkgs]
    while pending:
        nxt = []
        for i in range(0, len(pending), BATCH):
            chunk = pending[i:i + BATCH]
            res = post(f"{API}/querybatch", {"queries": chunk})["results"]
            for q, r in zip(chunk, res):
                key = (q["package"]["name"], q["version"])
                out.setdefault(key, []).extend(v["id"] for v in r.get("vulns", []))
                if r.get("next_page_token"):
                    nxt.append({**q, "page_token": r["next_page_token"]})
        pending = nxt
    return out


def severity(rec):
    """HIGH, CRITICAL, MODERATE, LOW or None. Malicious-package records (MAL-…) carry no severity and count as CRITICAL."""
    s = (rec.get("database_specific") or {}).get("severity")
    if s:
        return str(s).upper()
    return "CRITICAL" if rec["id"].startswith("MAL-") else None


def vulnerabilities(pkgs, as_of):
    """pkgs: [{"name", "version", "dev"}] (every package of the lockfiles). Returns {"ok", "source", "as_of", "queried", "items",
    "high", "critical", "unknown_severity", "published_after_as_of"}: items are the (package, advisory) pairs in force at `as_of`."""
    end = f"{as_of}T23:59:59Z"
    try:
        ids = query_ids(sorted({(p["name"], p["version"]) for p in pkgs}))
        uniq = sorted({i for v in ids.values() for i in v})
        with ThreadPoolExecutor(8) as ex:
            recs = dict(zip(uniq, ex.map(lambda i: get(f"{API}/vulns/{i}"), uniq)))
    except Exception as e:  # no network, rate limit, API change
        return {"ok": False, "source": "OSV", "as_of": as_of, "error": str(e)[:300]}
    dev = {}
    for p in pkgs:  # a package counts as production if any lockfile installs it outside devDependencies
        dev[(p["name"], p["version"])] = dev.get((p["name"], p["version"]), True) and bool(p.get("dev"))
    items, later = [], 0
    for (name, version), vs in ids.items():
        for i in sorted(set(vs)):
            rec = recs[i]
            if (rec.get("published") or "") > end:
                later += 1
                continue
            if rec.get("withdrawn") and rec["withdrawn"] <= end:
                continue
            items.append({"pkg": name, "version": version, "id": i, "aliases": rec.get("aliases", []), "severity": severity(rec),
                          "published": rec.get("published"), "dev": dev.get((name, version), False), "summary": (rec.get("summary") or "")[:120]})
    count = lambda s: sum(1 for x in items if x["severity"] == s)  # noqa: E731
    return {"ok": True, "source": "OSV", "as_of": as_of, "queried": len(ids), "items": items, "high": count("HIGH"), "critical": count("CRITICAL"),
            "unknown_severity": count(None), "published_after_as_of": later}
