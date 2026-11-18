"""Decision point *Technologies* (Analyzability, Modifiability): C1 deprecated packages, C2 supported runtimes, framework and
PostgreSQL, C3 outdated major versions, C4 high/critical vulnerabilities.

All of them are measured on the version each dependency resolves to (the app's lockfile, or what npm installs as of the reference
date `as_of`), not on the lower bound of its declared range, and as of `as_of`: the latest version is the highest stable one published
by then, and C4 counts the OSV advisories published by then. Dependency age (libyear, Cox et al., ICSE 2015) is informational.
"""

from evaluator.collectors.packages import coerce_version
from evaluator.common import RUBRIC, pct
from evaluator.criteria import C, apply_manual

DESC = {"C1": "No deprecated packages", "C2": "Runtime and framework supported",
        "C3": "≤ 20% of direct dependencies with an outdated major version", "C4": "0 high/critical vulnerabilities"}


def major(v):
    v = coerce_version(v)
    return int(v.split(".")[0]) if v else None


def libyear_summary(items):
    """Dependency freshness (libyear): sum, mean and the oldest, for dependencies and devDependencies separately."""
    out = {}
    for group, dev in (("dependencies", False), ("devDependencies", True)):
        xs = [i for i in items if i["dev"] == dev and i.get("libyear") is not None]
        out[group] = {"total": round(sum(i["libyear"] for i in xs), 2), "mean": round(sum(i["libyear"] for i in xs) / len(xs), 2) if xs else None,
                      "measured": len(xs), "oldest": [f"{i['pkg']} {i['resolved']} ({i['libyear']} y behind {i['latest']})"
                                                       for i in sorted(xs, key=lambda i: -i["libyear"])[:5] if i["libyear"] > 0]}
    return out


def unsupported_runtimes(m, S, resolved):
    out = []
    for pkg in m["packages"]["packages"]:
        d = pkg.get("dir", ".")
        for name, spec in {**pkg["dependencies"], **pkg["devDependencies"]}.items():
            v = resolved.get((d, name)) or spec
            if name in S and major(v) is not None and major(v) not in S[name]:
                out.append(f"{name} {v}")
        eng = pkg["engines"].get("node")
        if eng and major(eng) is not None and major(eng) not in S["node"]:
            out.append(f"node {eng}")
    images = m.get("postgres_images") or []
    out += [f"postgresql {i['major']} ({i['image']} in {i['file']})" for i in images if i["major"] is not None and i["major"] not in S["postgresql"]]
    return out, [f"{i['image']} in {i['file']}" for i in images if i["major"] is None]


def normalized(i):
    """An npm item of an older metrics.json (declared range only, no resolved version or libyear) in the current shape."""
    if "resolved" in i:
        return i
    return {**i, "resolved": i.get("base") or coerce_version(i.get("spec")), "resolved_source": "range lower bound", "dev": False,
            "dir": i.get("dir", "."), "libyear": None}


def vulnerability_count(pk):
    """(high + critical, source, error) from OSV, or from the npm audit of an older metrics.json."""
    vu = pk.get("vulnerabilities") or {}
    if vu.get("ok"):
        return vu["high"] + vu["critical"], "auto (OSV)", None
    au = pk.get("audit") or {}
    if not vu and au.get("ok"):
        return au["high"] + au["critical"], "auto (npm audit, older evaluation: not fixed at as_of)", None
    return None, None, vu.get("error") or "not queried"


def eval_technologies(m, manual, opts):
    T = RUBRIC["thresholds"]["technologies"]; S = {**RUBRIC["supported_runtimes"], **(m.get("eol") or {})}
    pk = m["packages"]; npm = pk["npm"]; as_of = pk.get("as_of") or m.get("as_of")
    eol_source = (f"endoflife.date as of {as_of}: " + ", ".join(sorted(m["eol"]))) if m.get("eol") else "rubric.json table"
    if not npm["ok"]:
        crit = {k: C(None, d, source="pending (offline)") for k, d in DESC.items()}
        apply_manual("technologies", crit, manual)
        return crit, {}, [], "The npm registry was not queried (offline mode or no network).", None
    items = [normalized(i) for i in npm["items"]]
    dep = [i for i in items if i["deprecated"]]
    newer = [f"{i['pkg']} {i['resolved']}" for i in items if i.get("after_as_of")]
    outdated = [f"{i['pkg']} {i['resolved']} (latest {i['latest']} as of {as_of})" for i in items if not i.get("after_as_of")
                and major(i["resolved"]) is not None and major(i["latest"]) is not None and major(i["resolved"]) < major(i["latest"])]
    po = pct(len(outdated), len(items))
    unsupported, unversioned = unsupported_runtimes(m, S, {(i["dir"], i["pkg"]): i["resolved"] for i in items})
    vu = pk.get("vulnerabilities") or {}
    vuln, vsource, verr = vulnerability_count(pk)
    crit = {"C1": C(not dep, DESC["C1"], [f"{i['pkg']} {i['resolved']}" for i in dep]),
            "C2": C(not unsupported, f"Runtime, framework and PostgreSQL supported ({eol_source}; rest: rubric.json table, {RUBRIC['supported_runtimes']['date']}; "
                                     f"postgresql/sequelize/pg unverified since {RUBRIC['supported_runtimes']['unverified']['date']})",
                    unsupported if not unversioned else {"unsupported": unsupported, "postgres_image_without_version_not_checked": unversioned}),
            "C3": C(None if newer else po <= T["pct_major_outdated_max"], DESC["C3"], f"{len(outdated)}/{len(items)} = {po:.1f}%",
                    source=f"pending (as_of {as_of} is earlier than {len(newer)} of the app's versions)" if newer else "auto"),
            "C4": C(None if vuln is None else vuln <= T["vuln_high_critical_max"], DESC["C4"] + f" (OSV, advisories published by {as_of})", vuln,
                    source=vsource if vuln is not None else f"pending (OSV: {verr[:120]})")}
    apply_manual("technologies", crit, manual)
    ly = libyear_summary(items)
    sources = sorted({i["resolved_source"] for i in items})
    met = {"direct": len(items), "deprecated": len(dep), "outdated": len(outdated), "as_of": as_of, "libyear": ly, "resolved_from": sources,
           "newer_than_as_of": newer}
    ev = outdated[:6] + unsupported[:4]
    if vu.get("ok"):
        hi = [x for x in vu["items"] if x["severity"] in ("HIGH", "CRITICAL")]
        met.update({"vulnerabilities_high_critical_production": sum(not x["dev"] for x in hi), "vulnerabilities_unknown_severity": vu["unknown_severity"],
                    "advisories_published_after_as_of": vu["published_after_as_of"], "installed_packages_queried": vu["queried"]})
        ev += [f"{x['severity'].lower()}: {x['pkg']} {x['version']} {x['id']}" + (" (dev)" if x["dev"] else "") for x in hi[:4]]
    ev += ly["dependencies"]["oldest"][:3]
    lyd = ly["dependencies"]
    finding = (f"{len(items)} direct dependencies (versions from: {', '.join(sources)}; as of {as_of}): {len(dep)} deprecated, {len(outdated)} with an "
               f"outdated major, {vuln if vuln is not None else '?'} high/critical vulnerabilities. Dependency age: {lyd['total']} libyears over "
               f"{lyd['measured']} production dependencies (mean {lyd['mean']}; informational).")
    if newer:
        finding += (f" WARNING: {len(newer)} dependencies were published after the reference date {as_of} ({', '.join(newer[:4])}): as_of is earlier "
                    "than the app, so their age and C3 are not measured; set --as-of to the generation date or later.")
    return crit, met, ev, finding, None
