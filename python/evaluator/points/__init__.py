"""The 11 decision points of Table 26, one module each. EVALUATORS maps a point id to the function that evaluates it:
`fn(m, manual, opts) -> (criteria, metrics, evidence, finding, forced_levels)`; must_criteria() lists the criteria that alone make a
point fail (`must_criteria` in rubric.json).
"""

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
    """Criteria that alone make a point fail (`must_criteria` in rubric.json). Read at call time, like the rest of the rubric."""
    return () if pid.startswith("_") else tuple((RUBRIC.get("must_criteria") or {}).get(pid, ()))
