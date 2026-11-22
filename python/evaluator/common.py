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


def point_weight(pid):
    """Weight of a decision point inside every subcharacteristic it feeds (`point_weights` in rubric.json); 1 when the rubric sets
    none, which makes each subcharacteristic the plain mean of its points. Read at call time, so a test can patch the rubric."""
    pw = RUBRIC.get("point_weights") or {}
    if pid not in pw:
        return 1
    w = pw[pid]
    if isinstance(w, bool) or not isinstance(w, (int, float)) or not (0 < w < float("inf")):
        raise ValueError(f"rubric.json point_weights.{pid} must be a positive number")
    return w


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
