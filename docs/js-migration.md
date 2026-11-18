# Migration to JavaScript

The evaluator is being ported from Python to JavaScript (Node.js ≥ 20.19, ES modules, no build step), so that it needs a single
runtime. Python stays the reference until every module is ported. The rule is that **the JavaScript version must return exactly
the same JSON as the Python one**, so that results stay comparable across the migration.

## How equivalence is checked

1. `python tests/golden/record_relational.py`, `record_scoring.py` and `record_outputs.py` wrap the public functions of the Python modules and run the
   whole Python test suite.
   It also evaluates the apps in `apps/`, when there are any. Every distinct call is recorded as `{fn, args, result}`:
   - `tests/golden/*.json` holds the test suite and fixture calls. It is committed. Absolute paths are replaced.
   - `results/_golden/*-apps.json` holds the calls on the generated apps. It stays local, because `apps/` is not versioned. The
     scoring records use the same inputs as `evaluate.py rescore`: `metrics.json`, the manual review, DV8, the live database and
     the judge.
   - A scoring record also keeps what the call read from disk, such as the error middleware's file and the design documents. The
     replay serves those files from the record instead of the disk.
   - A Python test that replaces `EVALUATORS` with stubs is not recorded, because it does not exercise the real points.
   - An outputs record keeps the content of every file `write_outputs` wrote, and the replay compares them as text. On each
     evaluated run it also keeps the inputs of the scoring, so the replay runs the whole chain in JavaScript: `metrics.json` →
     `evaluateProfile` → `writeOutputs`. The files must come out identical to Python's.
2. `npm run test:js` replays every recorded call on the JavaScript port. It requires the same JSON, including **key order**,
   because Python dicts are ordered and the reports are built from them.
3. When the Python code changes, record again, then fix the port until the JavaScript tests pass.

The collectors are checked end to end instead, because they run tools. `python tests/golden/record_collect.py` runs Python's
`collect()` on every app of `apps/` and on the fixture apps, with the reference date fixed. It records the `metrics.json` it
produced and every network answer it received: `npm view`, the lockfile npm resolved, OSV and endoflife.date.
`npm run test:js:collect` then runs the JavaScript `collect()` on the same apps with those answers replayed. The tools run again:
ast_metrics.js, dependency-cruiser, jscpd, Spectral, Knip and ESLint, plus c8 and StrykerJS on the fixture whose tests run. The
resulting metrics must be the same field by field: same keys in the same order, same values, and the same int/float kind. Only the
time of the run and the test runner's raw output (it carries durations) are left out. It is slow, so it is not part of
`npm run test:js`. Its records stay in `results/_golden/collect/`, since they hold absolute paths and the generated apps.

The entry points are checked end to end with `npm run test:js:entry`. Every run of `results/` is copied twice. The Python command
runs on one copy and the JavaScript one on the other, and every file they write must be the same text. The commands covered are
`evaluate rescore`, `manual_template`, `dv8_metrics` (when DV8 is installed), `evaluate aggregate` (comparison.csv, comparison.md,
sensitivity.json) and `evaluate run --offline` on a fixture app. Only the time of the run is aligned before the comparison.

`npm run test:js:cli` does the same for the rest of the command line:
- `cli report`;
- `cli evaluate --rescore` on the whole batch, which also runs rescore, aggregate and report;
- `cli evaluate` from scratch on a fixture app;
- the judge, on every run;
- `token_usage scan`, `show` and `record`.

The judge runs with a deterministic stand-in model (`tests/js/fake_judge.mjs`). Its answers depend on the SHA-256 of each prompt and
on how many times that prompt was asked, so both versions get the same votes only if they send the same prompts in the same order.
`judge.json` must then be identical, except its date: the prompts' SHA-256, the decisions (non-unanimous ones and "I don't know"
votes included) and the audit sample. Python picks that sample with `random.Random(seed).shuffle`, so `js/lib/pyrandom.mjs`
reimplements CPython's Mersenne Twister, its str seeding and its `shuffle`. Python's `report.md` is compared without its
"Generated:" line and its Environment section, which name the moment and the interpreter.

`js/lib/py.mjs` holds the Python semantics the port relies on:
- truthiness (`[]` and `{}` are false);
- the int/float distinction, which JSON and JavaScript numbers lose but Python prints (`50.0` against `50`). A float that Python
  would print is wrapped in `PyFloat`, which serializes as a plain number. `loadJson` reads a number written with a decimal point or
  an exponent as a `PyFloat`, as Python's `json` reads it as a float. This applies to the rubric and to the recorded inputs;
- `format()` (`:.1f` rounds half to even, and `:g`) and `str.format` for the templates of `rubric.json`;
- `json.dumps(indent=1, ensure_ascii=False)` (`dumps`), its default `ensure_ascii=True` (`dumpsAscii`, used for meta.json,
  manual.json, detected_layers.json and DV8's matrix), and the `csv` writer (`csvRow`), so that the files are the same byte for byte;
- `str()` and `repr()` (`True`, `None`, `1e-05`);
- `round()`, which rounds half to even on the exact binary value;
- ordering of mixed values;
- `re.match` (anchored at the start), `re.findall` and `splitlines`;
- `read_text` (`readText`), which reads in text mode: `

` becomes `
`. Two of the ecommerce apps have documents with CRLF.

The port also sorts folder listings without regard to case on Windows, as `WindowsPath` does.

## Status

| Python module | JavaScript | Equivalence |
|---|---|---|
| `relational_schema.py` | `js/relational/schema.mjs` | ✔ every recorded call. That covers the test suite, the fixtures and the 3 ecommerce apps. |
| `relational_analysis.py` | `js/relational/analysis.mjs` | ✔ the same, plus `load_er` on `tests/fixtures/er_versions`. |
| `evaluator/points/*` (the 11 points) | `js/evaluator/points/*.mjs` | ✔ every recorded call of each point. |
| `evaluator/criteria.py`, `scoring.py`, `ascmm.py` (profile), `supplementary.py`, `graph.py`, `routes.py` | `js/evaluator/*.mjs` | ✔ `evaluate_profile` and `risk_summary` on the 3 ecommerce apps, plus every call from the test suite. |
| `evaluator/outputs.py`, `dashboard.py`, `sensitivity.py`, the Markdown of `ascmm.py`, the summary part of `token_usage.py` | `js/evaluator/{outputs,dashboard,sensitivity,ascmm,tokens}.mjs` | ✔ the 11 files of every recorded `write_outputs`, the same text as Python's. On the 3 ecommerce apps the files also come out the same from `metrics.json` through the JS scoring. Also every recorded call of the sensitivity and the ASCMM comparison. |
| `evaluator/collectors/*` (ast, schema, ER, dependency graph, packages with npm/OSV/endoflife, contract and Spectral, tests and coverage, mutation, jscpd, Knip, ESLint, layers, README, artifacts) | `js/evaluator/collectors/*.mjs`, `js/evaluator/sys.mjs` | ✔ the same `metrics.json` as Python on the 3 ecommerce apps and the 6 fixture apps. That includes `--run-tests --mutation` on `mutation_app`, run on a fresh copy, because the tests write into the app. |
| `evaluate.py` (run, rescore, aggregate), `evaluator/pipeline.py`, `manual_template.py`, `dv8_metrics.py` | `js/evaluate.mjs`, `js/evaluator/pipeline.mjs`, `js/manual_template.mjs`, `js/dv8_metrics.mjs` | ✔ the same files as Python on every run of `results/` (rescore, manual review templates, DV8, comparison) and for `run --offline` on a fixture app. |
| `cli.py` (doctor, evaluate, report), `judge.py`, `token_usage.py`, `pg_temp.py` | `js/cli.mjs`, `js/judge.mjs`, `js/token_usage.mjs`, `js/pg_temp.mjs` | ✔ the same files and judge.json as Python (see `npm run test:js:cli`). `js/cli.mjs` still runs `pg_analysis.py` for `--postgres` until it is ported. |
| `pg_*.py`, `acceptance_check.py`, `contract_conformance.py`, `run_experiment.py` | — | pending |

**Newlines.** Python's `Path.write_text` turns `
` into `

` on Windows, so profile.md and the JSON files have CRLF there. The
JavaScript version writes LF on every platform. The CSV files keep their `

` in both, because Python opens them with `newline=""`.

**Two changes to Python came out of the port**, both for reproducibility:
- `graph.cliques` visited each module's neighbours from a `set`. The order of a set of strings is a hash order that changes
  between runs, so the order of the cliques in the evidence was not reproducible. The neighbours now keep their import order.
- StrykerJS lists the mutants in the order its workers finished them, so the 20 surviving mutants kept as evidence changed between
  runs. They are now sorted by file, line and mutator before being cut.

**A third change to Python**: `judge.py` passed `--cmd` through `shlex.split(posix=False)`, which keeps the quotes of a quoted path.
A `--cmd` such as `"C:\Program Files\nodejs\node.exe" judge.mjs` therefore reached Windows with its quotes and failed ("Access is
denied"). The quotes are now removed, as the JavaScript version does, and a test covers it.

**Test runner.** The JavaScript `sh` does not pass `NODE_TEST_CONTEXT` on to the commands it runs. Under `node --test`, that variable
made the app's own `node --test` report to the evaluator's runner, without running its suite or writing coverage.

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
