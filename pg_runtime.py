#!/usr/bin/env python3
"""
pg_runtime.py — Helpers shared by pg_analysis.py (real-database analysis) and run_experiment.py (acceptance gate):
free ports, readiness, killing a process tree on Windows and Linux, database names and URLs, masking of passwords.

Python standard library only. Nothing here is shell-specific: processes are started without a shell.
"""
import json, os, re, shutil, signal, socket, subprocess, time
from pathlib import Path
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


# ───────────────────────── Docker Compose (acceptance gate) ─────────────────────────
COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
PG_IMAGE = re.compile(r"(^|/)(postgres|postgis/postgis|bitnami/postgresql|timescale/timescaledb)(:|@|$)", re.I)


def find_compose(project):
    """The docker-compose file at the root of the evaluated project, or None."""
    return next((Path(project) / n for n in COMPOSE_NAMES if (Path(project) / n).is_file()), None)


def docker_status():
    """(compose command, None) when Docker and Docker Compose work, else (None, reason). Nothing is started."""
    if not shutil.which("docker"):
        return None, "Docker is not installed or not on PATH"
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=60).returncode != 0:
            return None, "the Docker daemon is not running (docker info failed)"
        if subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=60).returncode == 0:
            return ["docker", "compose"], None
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"Docker did not respond ({e})"
    if shutil.which("docker-compose"):
        return ["docker-compose"], None
    return None, "Docker Compose is not available (neither `docker compose` nor `docker-compose`)"


def service_env(service):
    """Environment of a service from `docker compose config --format json` (a dict; older versions print a list of K=V)."""
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = {k: v for k, v in (x.split("=", 1) for x in env if "=" in x)}
    return {k: ("" if v is None else str(v)) for k, v in env.items()}


def pick_postgres_service(config):
    """Name of the PostgreSQL service in a normalized compose config, or None. Matches by image, then by POSTGRES_* variables."""
    services = (config or {}).get("services") or {}
    for name, svc in services.items():
        if PG_IMAGE.search(str(svc.get("image") or "")):
            return name
    for name, svc in services.items():
        if any(k in service_env(svc) for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRESQL_PASSWORD")):
            return name
    return None


def pg_credentials(service):
    """(user, password, default database) the container is created with; the official image defaults apply when unset."""
    env = service_env(service)
    user = env.get("POSTGRES_USER") or env.get("POSTGRESQL_USERNAME") or "postgres"
    password = env.get("POSTGRES_PASSWORD") or env.get("POSTGRESQL_PASSWORD") or ""
    return user, password, env.get("POSTGRES_DB") or env.get("POSTGRESQL_DATABASE") or user


def parse_published_port(text):
    """`0.0.0.0:49153` / `[::]:49153` / one such line per address -> 49153; None if there is no port."""
    m = re.findall(r":(\d+)\s*$", str(text), re.M)
    return int(m[0]) if m else None


class Compose:
    """Thin wrapper over `docker compose -f <file> -p <project> …`. Output goes to the log file; secrets are never printed by it."""

    def __init__(self, cmd, file, project, log_path):
        self.cmd, self.file, self.project, self.log_path = list(cmd), Path(file), project, Path(log_path)

    def run(self, *args, timeout=300):
        full = self.cmd + ["-f", str(self.file), "-p", self.project] + list(args)
        try:
            p = subprocess.run(full, cwd=self.file.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except OSError as e:
            return 127, "", str(e)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write("$ " + " ".join(args) + "\n" + p.stdout + p.stderr + "\n")
        return p.returncode, p.stdout, p.stderr

    def config(self):
        rc, out, err = self.run("config", "--format", "json", timeout=60)
        if rc != 0:
            raise RuntimeError("docker compose config failed (Docker Compose v2 is required): " + (err or out)[-300:])
        return json.loads(out)

    def up(self, service):
        return self.run("up", "-d", service, timeout=900)

    def port(self, service, container_port=5432):
        rc, out, _ = self.run("port", service, str(container_port), timeout=60)
        return parse_published_port(out) if rc == 0 else None

    def wait_ready(self, service, user, seconds=90):
        """pg_isready over TCP inside the container: true only once the final server (not the init one) accepts connections."""
        end = time.time() + seconds
        while time.time() < end:
            if self.run("exec", "-T", service, "pg_isready", "-h", "127.0.0.1", "-U", user, "-d", "postgres", timeout=30)[0] == 0:
                return True
            time.sleep(2)
        return False

    def create_database(self, service, user, db):
        assert valid_eval_db(db), db
        return self.run("exec", "-T", service, "psql", "-U", user, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", f'CREATE DATABASE "{db}"', timeout=60)

    def down(self):
        """Removes the containers and their volumes: the disposable database goes with them."""
        return self.run("down", "-v", "--remove-orphans", timeout=180)
