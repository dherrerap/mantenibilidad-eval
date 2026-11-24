"""Shared state of the evaluator: the rubric (rubric.json), paths, the generator-model rules and small utilities (subprocesses,
file walking, percentages).
"""
import json
import os
import re
import shutil
import statistics
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent.parent.parent  # repository root (rubric.json, js/tools/, node_modules)


BIN = HERE / "node_modules" / ".bin"


RUBRIC = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))


SKIP_DIRS = {"node_modules", "dist", "build", "coverage", ".git", ".next", "out"}


LEVELS = ["Fails", "Partial", "Meets"]


def point_weights():
    """Weight of every decision point inside every subcharacteristic it feeds (`point_weights` in rubric.json), as {pid: weight}; a
    point the rubric gives no weight weighs 1, which makes each subcharacteristic the plain mean of its points. Checks the whole map:
    every key must be a point of the rubric (or start with "_", like `_comment`) and every value a positive number. Read at call
    time, so a test can patch the rubric; it is also checked once when this module loads, so a bad rubric fails before any collector runs."""
    pw = RUBRIC.get("point_weights") or {}
    for k, w in pw.items():
        if k.startswith("_"):
            continue
        if k not in RUBRIC["points"]:
            raise ValueError(f"rubric.json point_weights.{k} is not a decision point of the rubric")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not (0 < w < float("inf")):
            raise ValueError(f"rubric.json point_weights.{k} must be a positive number")
    return {pid: pw.get(pid, 1) for pid in RUBRIC["points"]}


point_weights()


def point_weight(pid):
    """Weight of one decision point (see point_weights())."""
    return point_weights().get(pid, 1)


def weighted_mean(points, key, w):
    """Weighted mean of `key` over `points` with the weights `w` ({pid: weight}, from point_weights()); None when there are no
    points. The one aggregation rule of a subcharacteristic, shared by scoring.profile() and sensitivity.overall()."""
    if not points:
        return None
    return sum(w.get(p["id"], 1) * p[key] for p in points) / sum(w.get(p["id"], 1) for p in points)


MISSING_MODEL_VALUES = {"", "n/a", "na", "none", "null", "unknown", "?"}


MODEL_WARNING = ("The generator model was not recorded (`--model`). It is a variable of the experiment: without it the result cannot be attributed to "
                 "a model, compared with other models or reproduced.")


MODEL_ERROR = ("The generator model is missing. Pass the model that generated the application with --model \"<model>\" "
               "(for example --model \"claude-sonnet-5-5\"); it is a variable of the experiment and the results cannot be interpreted without it. "
               "To evaluate anyway, add --allow-missing-model: profile.md and report.md will then carry a warning.")


def model_missing(model):
    """True when the generator model was not given (None, empty, n/a, unknown…)."""
    return model is None or str(model).strip().lower() in MISSING_MODEL_VALUES


def record_generator_model(results_dir, model):
    """Writes the generator model into <results>/environment.json, keeping whatever else the file has."""
    f = Path(results_dir) / "environment.json"
    env = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    env["generator_model"] = None if model_missing(model) else str(model)
    env["generator_model_missing"] = model_missing(model)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(env, indent=1, ensure_ascii=False), encoding="utf-8")


def sh(cmd, cwd=None, timeout=600, env=None):
    cmd = [shutil.which(cmd[0]) or cmd[0]] + list(cmd[1:])  # Windows: npm -> npm.cmd
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def walk(app):
    for d, dirs, files in os.walk(app):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".git")]
        for f in files:
            yield Path(d) / f


def rel(p, app):
    return Path(p).resolve().relative_to(Path(app).resolve()).as_posix()


def glob_to_re(g):
    g = re.escape(g).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.compile("^" + g + "$")


def pct(a, b):
    return None if not b else 100.0 * a / b


def median(xs):
    return statistics.median(xs) if xs else None
