"""Decision point *Configuration* (Modifiability): C1 network literals (CWE-1051), C2 duplicated literals (SonarQube
S1192, measured with eslint-plugin-sonarjs; pending if ESLint did not run), C3 external configuration.
"""
import re

from evaluator.collectors.lint import decide_count, usable
from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual


def eval_configuration(m, manual, opts):
    T = RUBRIC["thresholds"]["configuration"]; a = m["ast"]
    lits = [x for x in a["networkLiterals"] if not (T["cwe1051_ignore_env_fallback"] and x["envFallback"])]
    kloc = sum(f["loc"] for f in a["files"] if not f["test"]) / 1000.0
    # C2: SonarQube rule S1192 itself (eslint-plugin-sonarjs no-duplicate-string, per file). Pending when ESLint did not run, or when
    # it found nothing but could not parse some file.
    lint, note = usable(m)
    flagged = {f"{(x['literal'] or '«?»')[1:-1]} ({x['file']})": x["times"] for x in (lint or {}).get("dup_strings", [])}  # literal without quotes
    excess = sum((t or 0) - 1 for t in flagged.values()); dens = excess / kloc if kloc else 0.0  # informational only
    c2 = decide_count(len(flagged), lint, note)
    s1192_source = f"pending ({note})" if c2 is None else f"auto (eslint-plugin-sonarjs {lint['versions'].get('eslint-plugin-sonarjs')})"
    cfg_mod = any(re.search(r"(^|/)config(\.|/)", f) for f in a["envFiles"])
    crit = {"C1": C(len(lits) == 0, "0 network literals (URL/IP/port) (CWE-1051)", len(lits)),
            "C2": C(c2, f"0 literals of ≥10 characters repeated ≥{T['dup_literal_threshold']} times in a file (SonarQube S1192)",
                    flagged or (None if lint is None else 0), source=s1192_source),
            "C3": C(m["env_example"] or cfg_mod, "External configuration (.env.example or configuration module)", {"env_example": m["env_example"], "config_module": cfg_mod})}
    apply_manual("configuration", crit, manual)
    ev = [f"{x['file']}:{x['line']} {x['value']}" + (" [env fallback]" if x["envFallback"] else "") for x in lits[:6]]
    return crit, {"network_literals": len(lits), "dup_per_kloc": dens, "kloc": kloc, "s1192_literals": flagged}, ev, \
        f"{len(lits)} network literals; " + (f"{len(flagged)} duplicated literal(s) per S1192 ({dens:.1f} extra repetitions/KLOC, informational)"
                                              if lint else "S1192 not measured") + (f". {note}." if note else "."), None
