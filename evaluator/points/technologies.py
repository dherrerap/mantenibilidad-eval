"""Decision point *Technologies* (Analyzability, Modifiability): C1 deprecated packages, C2 supported runtimes,
framework and PostgreSQL, C3 outdated major versions, C4 high/critical vulnerabilities.
"""

from evaluator.collectors.packages import coerce_version
from evaluator.common import RUBRIC, pct
from evaluator.criteria import C, apply_manual


def eval_technologies(m, manual, opts):
    T = RUBRIC["thresholds"]["technologies"]; S = {**RUBRIC["supported_runtimes"], **(m.get("eol") or {})}
    eol_source = "endoflife.date: " + ", ".join(sorted(m.get("eol") or {})) if m.get("eol") else "rubric.json table"
    pk = m["packages"]; npm = pk["npm"]
    if not npm["ok"]:
        crit = {k: C(None, d, source="pending (offline)") for k, d in
                [("C1", "No deprecated packages"), ("C2", "Runtime and framework supported"), ("C3", "≤ 20% of direct dependencies with an outdated major version"), ("C4", "0 high/critical vulnerabilities")]}
        apply_manual("technologies", crit, manual)
        return crit, {}, [], "The npm registry was not queried (offline mode or no network).", None
    items = npm["items"]
    dep = [i for i in items if i["deprecated"]]
    outdated = []
    for i in items:
        b, l = coerce_version(i["spec"]), i["latest"]
        if b and l and int(b.split(".")[0]) < int(str(l).split(".")[0]):
            outdated.append(f"{i['pkg']} {i['spec']} (latest {l})")
    po = pct(len(outdated), len(items))
    unsupported = []
    for pkg in pk["packages"]:
        for name, spec in {**pkg["dependencies"], **pkg["devDependencies"]}.items():
            if name in S and coerce_version(spec) and int(coerce_version(spec).split(".")[0]) not in S[name]:
                unsupported.append(f"{name} {spec}")
        eng = pkg["engines"].get("node")
        if eng and coerce_version(eng) and int(coerce_version(eng).split(".")[0]) not in S["node"]:
            unsupported.append(f"node {eng}")
    images = m.get("postgres_images") or []
    unsupported += [f"postgresql {i['major']} ({i['image']} in {i['file']})" for i in images if i["major"] is not None and i["major"] not in S["postgresql"]]
    unversioned = [f"{i['image']} in {i['file']}" for i in images if i["major"] is None]
    vuln = pk["audit"]["high"] + pk["audit"]["critical"] if pk["audit"]["ok"] else None
    crit = {"C1": C(not dep, "No deprecated packages", [i["pkg"] for i in dep]),
            "C2": C(not unsupported, f"Runtime, framework and PostgreSQL supported ({eol_source}; rest: rubric.json table, {RUBRIC['supported_runtimes']['date']}; "
                                     f"postgresql/sequelize/pg unverified since {RUBRIC['supported_runtimes']['unverified']['date']})",
                    unsupported if not unversioned else {"unsupported": unsupported, "postgres_image_without_version_not_checked": unversioned}),
            "C3": C(po <= T["pct_major_outdated_max"], "≤ 20% of direct dependencies with an outdated major version", f"{len(outdated)}/{len(items)} = {po:.1f}%"),
            "C4": C(None if vuln is None else vuln <= T["vuln_high_critical_max"], "0 high or critical vulnerabilities", vuln, source="auto" if vuln is not None else "pending (npm audit)")}
    apply_manual("technologies", crit, manual)
    return crit, {"direct": len(items), "deprecated": len(dep), "outdated": len(outdated)}, outdated[:6] + unsupported[:4], \
        f"{len(items)} direct dependencies: {len(dep)} deprecated, {len(outdated)} with an outdated major, {vuln if vuln is not None else '?'} high/critical vulnerabilities.", None
