"""Input artifacts (protocol step 2, Table 27): which exist, classified as core, complementary or optional, and the findings
recorded for the missing complementary ones.
"""
import re
from pathlib import Path

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_analysis as ra  # noqa: E402
import relational_schema as rs  # noqa: E402
from evaluator.common import RUBRIC


def embedded_diagram(text):
    """Does a Markdown text embed an architecture diagram: a Mermaid block other than an erDiagram (that one is the ER model,
    a separate artifact) or a PlantUML one?"""
    if re.search(r"@startuml", text or ""):
        return True
    for block in re.findall(r"```[ \t]*mermaid[ \t]*\r?\n(.*?)```", text or "", re.S | re.I):
        first = next((ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("%%")), "")
        if first and not re.match(r"erDiagram\b", first):
            return True
    return False


def inventory_artifacts(m, files):
    """Step 2 / Table 27: which input artifacts exist, classified as core, complementary or optional.
    `files` = relative paths of the application. Each entry of rubric.json "artifacts" gets `present` and a `detail`."""
    low = [f.lower() for f in files]
    found = lambda rx: [f for f, l in zip(files, low) if re.search(rx, l)]
    deps = {d for p in m["packages"]["packages"] for d in {**p["dependencies"], **p["devDependencies"]}}
    obs_libs = sorted(deps & set(RUBRIC["libs_logger"] + RUBRIC["libs_request_logger"] + RUBRIC["libs_metrics"]))
    prod = [f for f in m["ast"]["files"] if not f["test"]]
    ts, tr = m["tests_static"], m["tests_run"]
    lock = found(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$")
    contract = list(m["contract"]["files"]) + found(r"\.schema\.json$|(^|/)dtos?/|\.dto\.[jt]s$")
    deploy = found(r"(^|/)dockerfile|docker-compose|\.github/workflows/|\.gitlab-ci|jenkinsfile|\.circleci/") + ([".env.example"] if m["env_example"] else [])
    adrs = found(r"(^|/)(adrs?|docs?)/.*\.md$")
    diagrams = found(r"\.(puml|drawio|mmd|plantuml)$|(architecture|diagram)[^/]*\.(png|svg|jpe?g)$")
    if embedded_diagram(m.get("readme", "")):
        diagrams.append("README (embedded diagram)")
    for f in adrs if m.get("app") else []:  # docs/**/*.md with a Mermaid or PlantUML diagram (docs/R2/architecture.md…)
        try:
            text = (Path(m["app"]) / f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if embedded_diagram(text):
            diagrams.append(f"{f} (embedded diagram)")
    agent = found(r"(^|/)(prompt|session|transcript)[^/]*\.(md|txt|log|jsonl?)$|(^|/)(technical-n\d|requirements[\w-]*)\.md$")
    glossary = found(r"glossary|ontology") + (["README (glossary section)"] if re.search(r"^#+\s*glossary", m.get("readme", ""), re.I | re.M) else [])
    state = {
        "source_code": (bool(prod), f"{len(prod)} production files"),
        "data_schema": (bool(m["schema"]["tables"]), rs.summary(m["schema"]) if m["schema"]["tables"] else "no relational schema found (SQL, Sequelize migrations or models)"),
        "er_model": (bool(m["er"]["found"] and m["er"]["diagram"]),
                     (f"{m['er']['file']}: {len(m['er']['entities'])} entities" if m["er"]["diagram"] else f"{m['er']['file']} has no erDiagram block") if m["er"]["found"]
                     else "not found (looked for " + ra.er_searched(RUBRIC["relational"]) + ")"),
        "manifests": (bool(m["packages"]["packages"]), f"{len(m['packages']['packages'])} package.json" + ("" if lock else "; no lockfile")),
        "test_suite": (ts["test_cases"] > 0, f"{ts['test_cases']} test cases" + ("; coverage report produced" if tr.get("executed") and tr.get("lines_total") else "; no coverage report")),
        "contract_spec": (bool(contract), ", ".join(contract[:3]) or "none"),
        "config_deploy": (bool(deploy), ", ".join(deploy[:4]) or "none"),
        "logging_config": (bool(obs_libs), ", ".join(obs_libs) or "no logging or metrics library"),
        "readme_docs": (bool(m.get("readme") or adrs), ("README" if m.get("readme") else "no README") + (f"; {len(adrs)} doc/ADR files" if adrs else "")),
        "diagrams": (bool(diagrams), ", ".join(diagrams[:3]) or "none"),
        "agent_log": (bool(agent), ", ".join(agent[:3]) or "none"),
        "glossary": (bool(glossary), ", ".join(glossary[:2]) or "none"),
    }
    return [{**a, "present": state[a["id"]][0], "detail": state[a["id"]][1]} for a in RUBRIC["artifacts"]]


def artifact_findings(m):
    """Missing complementary artifacts, recorded as findings (a missing test suite is a high-severity finding, not missing data)."""
    out = []
    for a in m.get("artifacts") or []:
        if a["level"] == "complementary" and not a["present"]:
            sev = "Critical" if a.get("absence") == "high_finding" else "Marginal"
            out.append({"artifact": a["id"], "name": a["name"], "severity": sev, "affected_points": a["feeds"],
                        "note": "absence recorded as a finding" + ("; it is not treated as missing data" if sev == "Critical" else ("; lowers the confidence of the affected points" if a["feeds"] else "; context for step 1 only"))})
    return out


def refresh_schema_artifact(m):
    """The data_schema artifact also counts as present when the live database (pg_schema.json) has tables, even if the code
    builds its schema in a way the static extraction cannot read."""
    live = (m.get("pg") or {}).get("tables")
    for a in m.get("artifacts") or []:
        if a["id"] == "data_schema" and not a["present"] and live:
            a["present"], a["detail"] = True, f"{len(live)} table(s) from the live database (the static extraction found none)"
    return m
