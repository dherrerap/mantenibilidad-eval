"""Decision point *Configuration* (Modifiability): C1 network literals (CWE-1051), C2 duplicated literals (SonarQube
S1192), C3 external configuration.
"""
import re

from evaluator.common import RUBRIC
from evaluator.criteria import C, apply_manual


def eval_configuration(m, manual, opts):
    T = RUBRIC["thresholds"]["configuration"]; a = m["ast"]
    lits = [x for x in a["networkLiterals"] if not (T["cwe1051_ignore_env_fallback"] and x["envFallback"])]
    kloc = sum(f["loc"] for f in a["files"] if not f["test"]) / 1000.0
    occ = a["literalOccurrences"]
    dups = {k: v for k, v in occ.items() if len(v) > 1 and len(k) >= 4}
    excess = sum(len(v) - 1 for v in dups.values()); dens = excess / kloc if kloc else 0.0  # informational only
    # SonarQube rule S1192 (eslint-plugin-sonarjs no-duplicate-string): threshold, minimum length, no "\w*" or ignored literals
    flagged = {k: len(v) for k, v in occ.items()
               if len(v) >= T["dup_literal_threshold"] and len(k) >= T["dup_literal_min_len"]
               and not (T["dup_literal_ignore_word_only"] and re.fullmatch(r"\w*", k, re.ASCII)) and k not in T["dup_literal_ignore"]}
    cfg_mod = any(re.search(r"(^|/)config(\.|/)", f) for f in a["envFiles"])
    crit = {"C1": C(len(lits) == 0, "0 network literals (URL/IP/port) (CWE-1051)", len(lits)),
            "C2": C(not flagged, f"0 literals of ≥{T['dup_literal_min_len']} characters repeated ≥{T['dup_literal_threshold']} times (SonarQube S1192)",
                    flagged or 0),
            "C3": C(m["env_example"] or cfg_mod, "External configuration (.env.example or configuration module)", {"env_example": m["env_example"], "config_module": cfg_mod})}
    apply_manual("configuration", crit, manual)
    ev = [f"{x['file']}:{x['line']} {x['value']}" + (" [env fallback]" if x["envFallback"] else "") for x in lits[:6]]
    return crit, {"network_literals": len(lits), "dup_per_kloc": dens, "kloc": kloc, "s1192_literals": flagged}, ev, \
        f"{len(lits)} network literals; {len(flagged)} duplicated literal(s) per S1192 ({dens:.1f} repetitions/KLOC, informational).", None
