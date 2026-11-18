# Python reference (deprecated)

This folder holds the Python version of the evaluator, the one the JavaScript version in `../js/` was ported from. **It is
deprecated since v0.5.0 and will be removed in v0.6.0.** Use `node js/cli.mjs …` (see the README at the repository root).

It is kept for one version for two reasons:
- to compare the results of both versions on new apps (the `tests/js/*.slow.mjs` tests run both);
- to re-record the golden cases of the JavaScript tests (`golden/record_*.py` write `../tests/golden/*.json` and
  `../results/_golden/`), while the two versions are still kept in step.

It reads its resources from the repository root: `rubric.json`, `specs/`, `node_modules/` and the helpers in `js/tools/`.

```
python python/cli.py doctor
python python/cli.py evaluate --model "<generator model>"
python -m unittest discover -s python/tests        # its own test suite (244 tests)
python python/golden/record_relational.py          # and record_scoring.py, record_outputs.py, record_collect.py
```

How the two versions were compared, and the differences that are expected (newlines on Windows, the Environment section of
report.md), are in [../docs/js-migration.md](../docs/js-migration.md).
