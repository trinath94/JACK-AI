"""Temporal dev server owned by the JACK service (Milestone 6).

``temporal server start-dev`` (Temporal CLI 1.9.1, MIT) keeps workflow history in
``<data_dir>/temporal/temporal.db`` and listens on ``127.0.0.1`` only, headless. Like the
embedded PostgreSQL it is a child of the service: on Linux it gets a parent-death signal, on
Windows it lives in the supervisor's Job Object. A server left over from a crash is stopped
before a new one starts (pid file).

The gRPC port has no authentication. JACK therefore never trusts what arrives through it:
workflows only carry ids, and approvals are verified in JACK's own database (threat T28).
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from jack_api.embedded_pg import _alive, _cmdline, _pdeathsig

log = logging.getLogger(__name__)

WIN = sys.platform == "win32"
EXE = ".exe" if WIN else ""
NAMESPACE = "default"
READY_TIMEOUT_S = 60.0


class TemporalUnavailable(Exception):
    pass


def find_binary(override: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    # Packaged: Tauri places sidecars next to each other (…/jack-service[.exe], …/temporal[.exe]).
    candidates.append(Path(sys.executable).resolve().parent / f"temporal{EXE}")
    for c in candidates:
        if c.is_file():
            return c
    return None


class TemporalServer:
    def __init__(self, data_dir: Path, *, binary: Path | None = None,
                 logs_dir: Path | None = None) -> None:
        self.dir = data_dir / "temporal"
        self.binary = binary if binary is not None else find_binary(
            os.environ.get("JACK_TEMPORAL_BIN"))
        self.logs_dir = logs_dir or data_dir
        self.port: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def target(self) -> str:
        assert self.port is not None
        return f"127.0.0.1:{self.port}"

    def start(self) -> str:
        try:
            return self._start_once()
        except TemporalUnavailable as first:
            # One retry with fresh ports: an early exit is usually a port taken in between.
            log.warning("Temporal didn't start (%s); trying once more", first)
            self.stop()
            return self._start_once()

    def _start_once(self) -> str:
        if self.binary is None:
            raise TemporalUnavailable("the Temporal server is not bundled with this build")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._stop_stale()
        self.port, http_port, metrics_port = _distinct_ports(3)
        args = [str(self.binary), "server", "start-dev", "--headless",
                "--ip", "127.0.0.1", "--port", str(self.port),
                "--http-port", str(http_port), "--metrics-port", str(metrics_port),
                "--db-filename", str(self.dir / "temporal.db"),
                "--namespace", NAMESPACE, "--log-level", "warn"]
        logf = open(self.logs_dir / "temporal.log", "ab")  # noqa: SIM115 - owned by the child
        kwargs: dict[str, object] = {}
        if WIN:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        else:
            kwargs["preexec_fn"] = _pdeathsig if sys.platform.startswith("linux") else os.setpgrp
        self._proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=logf,  # type: ignore[call-overload]
                                      stderr=subprocess.STDOUT, **kwargs)
        (self.dir / "server.pid").write_text(str(self._proc.pid))
        self._wait_ready()
        log.info("Temporal server ready on %s", self.target)
        return self.target

    def stop(self) -> None:
        p = self._proc
        self._proc = None
        if p is None or p.poll() is not None:
            return
        if WIN:
            p.terminate()
        else:
            p.send_signal(signal.SIGTERM)
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(5)
        with contextlib.suppress(OSError):
            (self.dir / "server.pid").unlink()

    def running(self) -> bool:
        if self._proc is None or self._proc.poll() is not None or self.port is None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                return True
        except OSError:
            return False

    def _wait_ready(self) -> None:
        assert self.port is not None and self._proc is not None
        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise TemporalUnavailable("the Temporal server exited during start-up: "
                                          + _log_tail(self.logs_dir / "temporal.log"))
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return
            except OSError:
                time.sleep(0.2)
        raise TemporalUnavailable("the Temporal server did not become ready")

    def _stop_stale(self) -> None:
        pidfile = self.dir / "server.pid"
        try:
            pid = int(pidfile.read_text().strip())
        except (OSError, ValueError):
            return
        if pid == os.getpid() or not _alive(pid) or "temporal" not in _cmdline(pid):
            return
        log.warning("stopping a Temporal server (pid %d) left over from a previous run", pid)
        with contextlib.suppress(OSError):
            if WIN:
                import psutil

                psutil.Process(pid).terminate()
            else:
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 20
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)


def _distinct_ports(n: int) -> list[int]:
    """Pick n free loopback ports at once (holding them, so they can't repeat)."""
    socks = []
    try:
        for _ in range(n):
            sk = socket.socket()
            sk.bind(("127.0.0.1", 0))
            socks.append(sk)
        return [int(sk.getsockname()[1]) for sk in socks]
    finally:
        for sk in socks:
            sk.close()


def _log_tail(path: Path) -> str:
    try:
        lines = path.read_text(errors="replace").strip().splitlines()[-3:]
    except OSError:
        return "see temporal.log"
    return " | ".join(x[:200] for x in lines) or "see temporal.log"
