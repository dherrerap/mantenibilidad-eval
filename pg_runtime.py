#!/usr/bin/env python3
"""
pg_runtime.py — Helpers shared by pg_analysis.py (real-database analysis) and run_experiment.py (acceptance gate):
free ports, readiness, killing a process tree on Windows and Linux, database names and URLs, masking of passwords.

Python standard library only. Nothing here is shell-specific: processes are started without a shell.
"""
import os, re, shutil, signal, socket, subprocess, time
from urllib.parse import quote, unquote, urlsplit, urlunsplit


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port, seconds, host="127.0.0.1"):
    end = time.time() + seconds
    while time.time() < end:
        try:
            socket.create_connection((host, port), timeout=1).close()
            return True
        except OSError:
            time.sleep(1)
    return False


def npm():
    """`npm` resolves to npm.cmd on Windows only through shutil.which."""
    return shutil.which("npm") or "npm"


def start_process(cmd, cwd, env, log):
    """Starts `cmd` in its own process group (so the whole tree can be killed later) without a shell."""
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, **kw)


def kill_tree(proc):
    """Ends the process and its children (npm start spawns node)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def eval_db_name(run_id):
    """`claude-n1-ecommerce-r1` -> `eval_claude_n1_ecommerce_r1`: the only kind of database name the evaluator creates or drops."""
    return "eval_" + re.sub(r"[^a-z0-9]+", "_", str(run_id).lower()).strip("_")[:50]


def valid_eval_db(name):
    return bool(re.fullmatch(r"eval_[a-z0-9_]{1,50}", str(name)))


def db_url(base_url, db):
    """The connection string `base_url` pointed at database `db` (credentials and query string are kept)."""
    p = urlsplit(base_url)
    return urlunsplit((p.scheme, p.netloc, "/" + quote(db), p.query, ""))


def build_url(user, password, host, port, db):
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(db)}"


def password_of(url):
    try:
        return unquote(urlsplit(url).password or "")
    except ValueError:
        return ""


def mask(text, *urls):
    """Replaces the passwords found in the given connection strings by ***."""
    for u in urls:
        pw = password_of(u) if u else ""
        if pw:
            text = text.replace(pw, "***")
    return text
