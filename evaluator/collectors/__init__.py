"""Evidence collection (protocol steps 3-4): runs every collector over an app and returns the metrics dictionary `m`.
"""
import datetime
from pathlib import Path

import evaluator  # noqa: F401  (puts the repository root on sys.path)
import relational_analysis as ra  # noqa: E402
import relational_schema as rs  # noqa: E402
from evaluator.artifacts import inventory_artifacts
from evaluator.collectors.contract import find_contracts, run_contract
from evaluator.collectors.dependencies import run_depcruise
from evaluator.collectors.documents import read_sql_files, readme_text
from evaluator.collectors.duplication import run_duplication
from evaluator.collectors.layers import classify_layers
from evaluator.collectors.packages import analyze_packages, fetch_eol, postgres_images
from evaluator.collectors.source import run_ast
from evaluator.collectors.testing import run_tests, static_tests
from evaluator.common import RUBRIC, rel, walk


def collect(app, out, opts):
    app = Path(app).resolve()
    m = {"app": str(app), "date": datetime.datetime.now().isoformat(timespec="seconds")}
    m["ast"] = run_ast(app, out)
    m["schema"] = rs.extract(read_sql_files(app), m["ast"], RUBRIC["relational"])
    m["er"] = ra.load_er(app, RUBRIC["relational"])
    m["postgres_images"] = postgres_images(app)
    m["graph"] = run_depcruise(app, out)
    inc_dev = RUBRIC["thresholds"]["coupling"]["include_devdependencies"]
    m["packages"] = analyze_packages(app, opts.offline, inc_dev)
    m["contract"] = run_contract(app, out, find_contracts(app))
    m["eol"] = fetch_eol(opts.offline)
    m["tests_static"] = static_tests(m["ast"], app)
    m["tests_run"] = run_tests(app, m["packages"]["packages"], opts.test_cmd, out) if opts.run_tests else {"executed": False}
    m["duplication"] = run_duplication(app, out)
    m["layers"], m["layers_origin"] = classify_layers(m["ast"], app, opts.layers or (app / ".layers.json"))
    m["readme"] = readme_text(app)
    m["env_example"] = any(p.name in (".env.example", ".env.sample", ".env.template", "env.example") for p in walk(app))
    m["artifacts"] = inventory_artifacts(m, [rel(p, app) for p in walk(app)])
    return m
