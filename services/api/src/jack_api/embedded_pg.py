"""Embedded PostgreSQL 16 owned by the JACK service (decision D-1, Milestone 6).

The binaries come from the ``pixeltable-pgserver`` wheel and are used as plain files (the
package is never imported). The cluster lives in ``<data_dir>/pg16``, listens on
``127.0.0.1:<random port>`` only, and is reached with role ``jack`` and a SCRAM password
generated on first start. The password is kept in the OS credential store (Windows Credential
Manager); on POSIX development builds without a secure keyring it is a 0600 file next to the
cluster, which is no weaker than the cluster's own files.

Process ownership:
* Windows: ``pg_ctl`` starts the server (it drops administrator rights, which ``postgres.exe``
  insists on); the server stays inside the supervisor's Job Object, so it dies with JACK.
* POSIX: ``postgres`` runs as our direct child with a parent-death signal (Linux), so a killed
  service can't orphan it. A server left over from a crash is stopped before starting.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from jack_api.ai.credentials import CredentialStore
from jack_api.redaction import register_secret

log = logging.getLogger(__name__)

PG_MAJOR = "16"
ROLE = "jack"
DATABASE = "jack"
CRED_NAME = "postgres:jack"
READY_TIMEOUT_S = 60.0
WIN = sys.platform == "win32"
EXE = ".exe" if WIN else ""


class PostgresUnavailable(Exception):
    """Embedded PostgreSQL can't be used here; the reason is shown to the user."""


def find_binaries(override: str | None = None) -> Path | None:
    """The ``pginstall`` directory with ``bin/postgres``: env override, PyInstaller bundle, or
    the installed wheel (located without importing it)."""
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "pixeltable_pgserver" / "pginstall")
    spec = importlib.util.find_spec("pixeltable_pgserver")
    if spec and spec.submodule_search_locations:
        candidates.append(Path(list(spec.submodule_search_locations)[0]) / "pginstall")
    for c in candidates:
        if (c / "bin" / f"postgres{EXE}").exists():
            return c
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _pdeathsig() -> None:  # pragma: no cover - runs in the child between fork and exec
    """Linux: deliver SIGTERM to the child when the service (its parent) dies."""
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass
    os.setpgrp()  # own group: Ctrl+C in a dev terminal doesn't hit the server directly


@dataclass
class PgStatus:
    running: bool
    port: int | None
    detail: str


class EmbeddedPostgres:
    def __init__(self, data_dir: Path, creds: CredentialStore, *,
                 binaries: Path | None = None, logs_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self.cluster = data_dir / f"pg{PG_MAJOR}"
        self.binaries = binaries if binaries is not None else find_binaries(
            os.environ.get("JACK_PG_BINARIES"))
        self.logs_dir = logs_dir or data_dir
        self._creds = creds
        self._proc: subprocess.Popen[bytes] | None = None
        self.port: int | None = None
        self._password: str | None = None

    # ------------------------------------------------------------------ checks
    def check(self) -> None:
        if self.binaries is None:
            raise PostgresUnavailable("PostgreSQL binaries are not bundled with this build")
        if not WIN and hasattr(os, "geteuid") and os.geteuid() == 0:
            raise PostgresUnavailable("PostgreSQL refuses to run as root; start JACK as a "
                                      "normal user")
        if WIN:
            ok, detail = self._creds.available()
            if not ok or not self._creds.secure:
                raise PostgresUnavailable("No secure store for the database password "
                                          f"(Windows Credential Manager): {detail}")

    def _bin(self, name: str) -> str:
        assert self.binaries is not None
        return str(self.binaries / "bin" / f"{name}{EXE}")

    # ------------------------------------------------------------------ password
    def _password_file(self) -> Path:
        return self.data_dir / f"pg{PG_MAJOR}.pass"

    def _get_password(self) -> str | None:
        if self._creds.secure:
            with contextlib.suppress(Exception):
                pw = self._creds.get(CRED_NAME)
                if pw:
                    return pw
        f = self._password_file()
        if not WIN and f.exists():
            return f.read_text().strip() or None
        return None

    def _store_password(self, pw: str) -> None:
        if self._creds.secure:
            self._creds.set(CRED_NAME, pw)
            return
        if WIN:
            raise PostgresUnavailable("No secure store for the database password")
        f = self._password_file()
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(pw)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> str:
        """Start (initialising on first use) and return the SQLAlchemy URL."""
        self.check()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if not (self.cluster / "PG_VERSION").exists():
            self._initdb()
        pw = self._get_password()
        if pw is None:
            raise PostgresUnavailable("The database password is missing from the credential "
                                      "store, so the existing database can't be opened")
        self._password = pw
        register_secret(pw)
        self._stop_stale()
        self.port = free_port()
        logf = self.logs_dir / "postgres.log"
        opts = ["-p", str(self.port), "-c", "listen_addresses=127.0.0.1",
                "-c", "unix_socket_directories=", "-c", "max_connections=40",
                "-c", "shared_buffers=32MB", "-c", "password_encryption=scram-sha-256",
                "-c", "timezone=UTC"]
        if WIN:
            r = subprocess.run([self._bin("pg_ctl"), "start", "-D", str(self.cluster), "-w",
                                "-t", str(int(READY_TIMEOUT_S)), "-l", str(logf),
                                "-o", " ".join(opts)],
                               capture_output=True, text=True, timeout=READY_TIMEOUT_S + 10)
            if r.returncode != 0:
                raise PostgresUnavailable(f"PostgreSQL did not start: {_tail(logf, r.stderr)}")
        else:
            self._proc = subprocess.Popen(  # noqa: S603 - fixed binary, no shell
                [self._bin("postgres"), "-D", str(self.cluster), *opts],
                stdin=subprocess.DEVNULL, stdout=open(logf, "ab"),  # noqa: SIM115
                stderr=subprocess.STDOUT, preexec_fn=_pdeathsig if sys.platform.startswith(
                    "linux") else os.setpgrp)
        self._wait_ready()
        log.info("embedded PostgreSQL %s ready on 127.0.0.1:%d", PG_MAJOR, self.port)
        return self.url

    @property
    def url(self) -> str:
        assert self.port is not None and self._password is not None
        return (f"postgresql+psycopg://{ROLE}:{self._password}@127.0.0.1:{self.port}/"
                f"{DATABASE}")

    def stop(self) -> None:
        if WIN:
            if self.binaries is not None and (self.cluster / "postmaster.pid").exists():
                subprocess.run([self._bin("pg_ctl"), "stop", "-D", str(self.cluster), "-m",
                                "fast", "-w", "-t", "30"], capture_output=True, timeout=40)
            return
        p = self._proc
        self._proc = None
        if p is None or p.poll() is not None:
            return
        p.send_signal(signal.SIGINT)  # fast shutdown: roll back clients, checkpoint, exit
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(5)

    def status(self) -> PgStatus:
        if self.port is None:
            return PgStatus(False, None, "not started")
        if not WIN and (self._proc is None or self._proc.poll() is not None):
            return PgStatus(False, self.port, "server process exited")
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                pass
        except OSError as exc:
            return PgStatus(False, self.port, f"not accepting connections: {exc}")
        return PgStatus(True, self.port, f"PostgreSQL {PG_MAJOR} on 127.0.0.1:{self.port}")

    # ------------------------------------------------------------------ internals
    def _initdb(self) -> None:
        pw = secrets.token_urlsafe(32)
        tmp = self.data_dir / f"pg{PG_MAJOR}.init"
        shutil.rmtree(tmp, ignore_errors=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=self.data_dir,
                                         prefix=".pwfile-") as fh:
            fh.write(pw)
            pwfile = fh.name
        try:
            os.chmod(pwfile, 0o600)
            r = subprocess.run([self._bin("initdb"), "-D", str(tmp), "-U", ROLE,
                                f"--pwfile={pwfile}", "--auth=scram-sha-256", "-E", "UTF8",
                                "--locale=C", "--no-instructions"],
                               capture_output=True, text=True, timeout=180)
        finally:
            with contextlib.suppress(OSError):
                os.remove(pwfile)
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise PostgresUnavailable(f"initdb failed: {(r.stderr or r.stdout).strip()[-400:]}")
        # Local connections are also password-protected (no trust anywhere).
        (tmp / "pg_hba.conf").write_text(
            "# JACK AI: loopback only, SCRAM passwords\n"
            "host all all 127.0.0.1/32 scram-sha-256\n"
            "host all all ::1/128 scram-sha-256\n")
        self._store_password(pw)
        tmp.rename(self.cluster)
        self._password = pw
        # Create the application database.
        self.port = free_port()
        self._stop_stale()
        logf = self.logs_dir / "postgres.log"
        if WIN:
            subprocess.run([self._bin("pg_ctl"), "start", "-D", str(self.cluster), "-w", "-l",
                            str(logf), "-o", f"-p {self.port} -c listen_addresses=127.0.0.1"],
                           capture_output=True, timeout=READY_TIMEOUT_S + 10, check=True)
        else:
            self._proc = subprocess.Popen(  # noqa: S603
                [self._bin("postgres"), "-D", str(self.cluster), "-p", str(self.port),
                 "-c", "listen_addresses=127.0.0.1", "-c", "unix_socket_directories="],
                stdin=subprocess.DEVNULL, stdout=open(logf, "ab"),  # noqa: SIM115
                stderr=subprocess.STDOUT, preexec_fn=_pdeathsig if sys.platform.startswith(
                    "linux") else os.setpgrp)
        try:
            self._wait_ready(dbname="postgres")
            import psycopg

            with psycopg.connect(host="127.0.0.1", port=self.port, user=ROLE, password=pw,
                                 dbname="postgres", autocommit=True) as conn:
                conn.execute(f"CREATE DATABASE {DATABASE} OWNER {ROLE}")
        finally:
            self.stop()
            self.port = None
        log.info("initialised embedded PostgreSQL cluster in %s", self.cluster)

    def _stop_stale(self) -> None:
        """Stop a server left running by a crashed previous service (same cluster)."""
        pidfile = self.cluster / "postmaster.pid"
        if not pidfile.exists():
            return
        if WIN:
            r = subprocess.run([self._bin("pg_ctl"), "status", "-D", str(self.cluster)],
                               capture_output=True, timeout=20)
            if r.returncode == 0:
                log.warning("stopping a PostgreSQL server left over from a previous run")
                subprocess.run([self._bin("pg_ctl"), "stop", "-D", str(self.cluster), "-m",
                                "fast", "-w", "-t", "30"], capture_output=True, timeout=40)
            return
        try:
            pid = int(pidfile.read_text().splitlines()[0])
        except (OSError, ValueError, IndexError):
            return
        if pid == os.getpid() or not _alive(pid):
            return  # postgres removes a stale pid file itself
        cmd = _cmdline(pid)
        if "postgres" not in cmd:
            return
        log.warning("stopping PostgreSQL (pid %d) left over from a previous run", pid)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGINT)
        deadline = time.monotonic() + 30
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        if _alive(pid):
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)

    def _wait_ready(self, dbname: str = DATABASE) -> None:
        import psycopg

        deadline = time.monotonic() + READY_TIMEOUT_S
        last: Exception | None = None
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise PostgresUnavailable("PostgreSQL exited during start-up: "
                                          + _tail(self.logs_dir / "postgres.log", ""))
            try:
                with psycopg.connect(host="127.0.0.1", port=self.port, user=ROLE,
                                     password=self._password, dbname=dbname,
                                     connect_timeout=2):
                    return
            except psycopg.OperationalError as exc:
                last = exc
                time.sleep(0.2)
        raise PostgresUnavailable(f"PostgreSQL did not become ready: {last}")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        try:
            import psutil

            return " ".join(psutil.Process(pid).cmdline())
        except Exception:  # noqa: BLE001
            return ""


def _tail(logf: Path, extra: str) -> str:
    try:
        lines = logf.read_text(errors="replace").strip().splitlines()[-3:]
    except OSError:
        lines = []
    return " | ".join([*(x for x in lines), extra.strip()])[-500:]
