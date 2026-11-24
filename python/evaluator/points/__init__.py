"""The 11 decision points of Table 26, one module each. EVALUATORS maps a point id to the function that evaluates it:
`fn(m, manual, opts) -> (criteria, metrics, evidence, finding, forced_levels)`; must_criteria() lists the criteria that alone make a
point fail (`must_criteria` in rubric.json).
"""

import re

from evaluator.common import RUBRIC
from evaluator.points.cohesion import eval_cohesion
from evaluator.points.configuration import eval_configuration
from evaluator.points.contracts import eval_contracts
from evaluator.points.coupling import eval_coupling
from evaluator.points.cyclomatic import eval_cyclomatic
from evaluator.points.data_model import eval_data_model
from evaluator.points.hierarchies import eval_hierarchies
from evaluator.points.layers import eval_layers
from evaluator.points.observability import eval_observability
from evaluator.points.technologies import eval_technologies
from evaluator.points.tests import eval_tests


EVALUATORS = {"layers": eval_layers, "cyclomatic": eval_cyclomatic, "cohesion": eval_cohesion, "hierarchies": eval_hierarchies,
              "technologies": eval_technologies, "coupling": eval_coupling, "data_model": eval_data_model,
              "contracts": eval_contracts, "observability": eval_observability, "tests": eval_tests, "configuration": eval_configuration}


def must_criteria(pid):
    """Criteria that alone make a point fail (`must_criteria` in rubric.json). Read at call time, like the rest of the rubric, and
    checked whole: the map must exist (an absent map would drop the vetoes without a word), every key must be a point of the rubric
    (or start with "_") and every value a list of criterion ids (C1, C2, …). Also checked once when this module loads."""
    mc = RUBRIC.get("must_criteria")
    if not isinstance(mc, dict):
        raise ValueError("rubric.json must_criteria is missing")
    for k, v in mc.items():
        if k.startswith("_"):
            continue
        if k not in RUBRIC["points"]:
            raise ValueError(f"rubric.json must_criteria.{k} is not a decision point of the rubric")
        if not isinstance(v, list) or not all(isinstance(c, str) and re.fullmatch(r"C\d+", c) for c in v):
            raise ValueError(f"rubric.json must_criteria.{k} must be a list of criterion ids (C1, C2, …)")
    return () if pid.startswith("_") else tuple(mc.get(pid, ()))


must_criteria("_")
