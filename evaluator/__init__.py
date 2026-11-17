"""evaluator — the maintainability evaluation framework as a package.

Layout (protocol steps of section 5.3.3):
  collectors/    evidence collection, one module per tool or source: source (AST), dependencies (graph), packages (npm versions,
                 libyear, runtimes), osv (vulnerabilities), contract, testing, mutation (StrykerJS), duplication (jscpd), layers,
                 lint (ESLint + SonarJS), knip (dead files, unused dependencies), documents; collectors.collect() runs them all
  artifacts      input artifacts (Table 27)
  points/        the 11 decision points (Table 26), one module each; points.EVALUATORS maps id -> function
  criteria       criteria, manual review / judge, levels and ranges
  graph, routes  measures shared by several points
  scoring        the 11 points, the profile per subcharacteristic and the risk list (step 9)
  ascmm          ISO/IEC 5055 occurrences of the detected weaknesses and their density per KLOC (informational)
  sensitivity    the overall score and the ranking of the runs under other weights (informational)
  dashboard      the risk dashboard (step 10, Table 29)
  supplementary  informational indicators (not scored)
  outputs        the files written for each run
  pipeline       scoring of a run from its saved evidence (metrics.json): used by run, rescore and aggregate

evaluate.py is the command line (run, rescore, aggregate) and re-exports these names for `import evaluate as ev`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # relational_schema, relational_analysis, pg_runtime and token_usage live at the repository root
    sys.path.insert(0, str(ROOT))
