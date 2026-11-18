# Migration to JavaScript

The evaluator is being ported from Python to JavaScript (Node.js ≥ 20.19, ES modules, no build step), so that it needs a single
runtime. Python stays the reference until every module is ported. The rule is that **the JavaScript version must return exactly
the same JSON as the Python one**, so that results stay comparable across the migration.

## How equivalence is checked

1. `python tests/golden/record_relational.py` wraps the public functions of a Python module and runs the whole Python test suite.
   It also evaluates the apps in `apps/`, when there are any. Every distinct call is recorded as `{fn, args, result}`:
   - `tests/golden/relational.json` holds the test suite and fixture calls. It is committed. Absolute paths are replaced.
   - `results/_golden/relational-apps.json` holds the calls on the generated apps. It stays local, because `apps/` is not versioned.
2. `npm run test:js` replays every recorded call on the JavaScript port. It requires the same JSON, including **key order**,
   because Python dicts are ordered and the reports are built from them.
3. When the Python code changes, record again, then fix the port until the JavaScript tests pass.

`js/lib/py.mjs` holds the Python semantics the port relies on:
- truthiness (`[]` and `{}` are false);
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
| `evaluator/points/*`, `evaluator/scoring.py`, `evaluator/criteria.py` | — | pending |
| `evaluator/collectors/*` (tools run as subprocesses) | — | pending |
| `evaluate.py`, `cli.py`, `manual_template.py`, `judge.py`, `token_usage.py` | — | pending |
| `pg_*.py`, `acceptance_check.py`, `contract_conformance.py`, `run_experiment.py` | — | pending |

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
