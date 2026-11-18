# Migration to JavaScript

The evaluator is being ported from Python to JavaScript (Node.js ≥ 20.19, ES modules, no build step), so that it needs a single
runtime. Python stays the reference until every module is ported. The rule is that **the JavaScript version must return exactly
the same JSON as the Python one**, so that results stay comparable across the migration.

## How equivalence is checked

1. `python tests/golden/record_relational.py` and `record_scoring.py` wrap the public functions of the Python modules and run the
   whole Python test suite.
   It also evaluates the apps in `apps/`, when there are any. Every distinct call is recorded as `{fn, args, result}`:
   - `tests/golden/*.json` holds the test suite and fixture calls. It is committed. Absolute paths are replaced.
   - `results/_golden/*-apps.json` holds the calls on the generated apps. It stays local, because `apps/` is not versioned. The
     scoring records use the same inputs as `evaluate.py rescore`: `metrics.json`, the manual review, DV8, the live database and
     the judge.
   - A scoring record also keeps what the call read from disk, such as the error middleware's file and the design documents. The
     replay serves those files from the record instead of the disk.
   - A Python test that replaces `EVALUATORS` with stubs is not recorded, because it does not exercise the real points.
2. `npm run test:js` replays every recorded call on the JavaScript port. It requires the same JSON, including **key order**,
   because Python dicts are ordered and the reports are built from them.
3. When the Python code changes, record again, then fix the port until the JavaScript tests pass.

`js/lib/py.mjs` holds the Python semantics the port relies on:
- truthiness (`[]` and `{}` are false);
- the int/float distinction, which JSON and JavaScript numbers lose but Python prints (`50.0` against `50`). A float that Python
  would print is wrapped in `PyFloat`, which serializes as a plain number. `loadJson` reads a number written with a decimal point or
  an exponent as a `PyFloat`, as Python's `json` reads it as a float. This applies to the rubric and to the recorded inputs;
- `format()` (`:.1f` rounds half to even, and `:g`) and `str.format` for the templates of `rubric.json`;
- `str()` and `repr()` (`True`, `None`, `1e-05`);
- `round()`, which rounds half to even on the exact binary value;
- ordering of mixed values;
- `re.match` (anchored at the start), `re.findall` and `splitlines`.

The port also sorts folder listings without regard to case on Windows, as `WindowsPath` does.

## Status

| Python module | JavaScript | Equivalence |
|---|---|---|
| `relational_schema.py` | `js/relational/schema.mjs` | ✔ every recorded call. That covers the test suite, the fixtures and the 3 ecommerce apps. |
| `relational_analysis.py` | `js/relational/analysis.mjs` | ✔ the same, plus `load_er` on `tests/fixtures/er_versions`. |
| `evaluator/points/*` (the 11 points) | `js/evaluator/points/*.mjs` | ✔ every recorded call of each point. |
| `evaluator/criteria.py`, `scoring.py`, `ascmm.py` (profile), `supplementary.py`, `graph.py`, `routes.py` | `js/evaluator/*.mjs` | ✔ `evaluate_profile` and `risk_summary` on the 3 ecommerce apps, plus every call from the test suite. |
| `evaluator/outputs.py`, `dashboard.py`, `sensitivity.py`, the Markdown of `ascmm.py` | — | pending |
| `evaluator/collectors/*` (tools run as subprocesses) | — | pending |
| `evaluate.py`, `cli.py`, `manual_template.py`, `judge.py`, `token_usage.py` | — | pending |
| `pg_*.py`, `acceptance_check.py`, `contract_conformance.py`, `run_experiment.py` | — | pending |

**One change to Python came out of the port.** `graph.cliques` visited each module's neighbours from a `set`. The order of a set of
strings is a hash order that changes between runs, so the order of the cliques in the evidence was not reproducible. The neighbours
now keep their import order in both versions.

The Python evaluator does not call the ported modules yet. Each one is switched over once everything that depends on it has
been ported as well.

## Order

1. **Leaves with the most logic.** These are the relational modules (done), then the decision points, the criteria and the scoring.
   They are pure functions over `metrics.json`, which the recorder can check call by call.
2. **Collectors.** They run ESLint, Knip, dependency-cruiser, jscpd and the other tools. In JavaScript these can run in-process
   where the tool offers an API.
3. **Entry points.** These are `evaluate`, `cli`, the judge, tokens and the acceptance gate. Here the check is end to end: the
   `metrics.json`, `scorecard.json` and `profile.json` of every app must be identical to Python's.
4. **Retire Python** once those three files match for every app, and remove the Python tests that have a JavaScript equivalent.
