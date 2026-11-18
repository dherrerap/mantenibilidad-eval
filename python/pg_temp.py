#!/usr/bin/env python3
"""
pg_temp.py — A disposable PostgreSQL server for `--postgres` when PG_ADMIN_URL is not set, so that the acceptance gate, the
contract conformance (Prism) and the live database analysis run without Docker and without touching any existing server.

It needs the PostgreSQL server binaries (initdb, pg_ctl), looked for in PG_BIN, the PATH and the usual install folders
(C:/Program Files/PostgreSQL/<major>/bin, /usr/lib/postgresql/<major>/bin, /opt/homebrew/opt/postgresql@<major>/bin…; the highest
major first). The cluster lives in a new temporary folder, listens only on 127.0.0.1 on a free port, its superuser `evaluator` has a
random password (scram-sha-256, never written outside the temporary folder) and the whole folder is deleted when it stops.

    with pg_temp.server() as url:      # url = postgres://evaluator:<random>@127.0.0.1:<port>/postgres
        ...                            # None if no PostgreSQL binaries were found

    python pg_temp.py                  # starts one, prints its version and stops it (a check)
"""
import contextlib, glob, os, re, secrets, shutil, socket, subprocess, sys, tempfile
from pathlib import Path

USER = "evaluator"


def _major(path):
    m = re.search(r"(?:PostgreSQL[/\\]|postgresql[@/])(\d+)", str(path))
    return int(m.group(1)) if m else 0


def find_bin():
    """Folder with initdb and pg_ctl, or None."""
    exe = ".exe" if os.name == "nt" else ""
    cands = [os.environ.get("PG_BIN", "")]
    on_path = shutil.which("pg_ctl")
    if on_path:
        cands.append(str(Path(on_path).parent))
    patterns = ["C:/Program Files/PostgreSQL/*/bin", "/usr/lib/postgresql/*/bin", "/usr/local/pgsql/bin", "/opt/homebrew/opt/postgresql@*/bin",
                "/usr/local/opt/postgresql@*/bin", "/Applications/Postgres.app/Contents/Versions/*/bin"]
    cands += sorted((d for p in patterns for d in glob.glob(p)), key=_major, reverse=True)
    for c in cands:
        if c and all((Path(c) / f"{b}{exe}").exists() for b in ("initdb", "pg_ctl")):
            return Path(c)
    return None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(cmd, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: " + ((p.stderr or p.stdout or "").strip().splitlines() or ["no output"])[-1])
    return p.stdout


@contextlib.contextmanager
def server(bin_dir=None):
    """Starts a disposable server and yields its admin URL (None when there are no binaries); stops it and deletes it on exit."""
    bin_dir = Path(bin_dir) if bin_dir else find_bin()
    if not bin_dir:
        yield None
        return
    exe = ".exe" if os.name == "nt" else ""
    root = Path(tempfile.mkdtemp(prefix="eval-pg-"))
    data, pw, pwfile = root / "data", secrets.token_urlsafe(24), root / "pw"
    pwfile.write_text(pw, encoding="utf-8")
    port, started = free_port(), False
    try:
        _run([str(bin_dir / f"initdb{exe}"), "-D", str(data), "-U", USER, "--pwfile", str(pwfile), "-A", "scram-sha-256", "-E", "UTF8",
              "--locale=C", "--no-sync"])
        pwfile.unlink()
        # No pipes: the server inherits pg_ctl's handles and keeps them open, so reading its output would never end (Windows).
        # Its messages go to server.log, read when the start fails.
        log = root / "server.log"
        rc = subprocess.run([str(bin_dir / f"pg_ctl{exe}"), "-D", str(data), "-l", str(log), "-w", "-t", "60",
                             "-o", f"-p {port} -c listen_addresses=127.0.0.1 -c fsync=off", "start"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120).returncode
        started = True  # stop is attempted even if the wait failed: the server may be up
        if rc != 0:
            tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines() if log.exists() else []
            raise RuntimeError("pg_ctl start failed: " + (tail[-1] if tail else f"exit {rc}"))
        yield f"postgres://{USER}:{pw}@127.0.0.1:{port}/postgres"
    finally:
        if started:
            with contextlib.suppress(Exception):
                _run([str(bin_dir / f"pg_ctl{exe}"), "-D", str(data), "-m", "fast", "-w", "stop"])
        shutil.rmtree(root, ignore_errors=True)


def main():
    b = find_bin()
    if not b:
        sys.exit("No PostgreSQL server binaries (initdb, pg_ctl) found: install PostgreSQL or set PG_BIN.")
    with server(b) as url:
        port = url.rsplit(":", 1)[1].split("/")[0]
        print(f"PostgreSQL from {b}: started on 127.0.0.1:{port} and stopped. --postgres can use it without PG_ADMIN_URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
