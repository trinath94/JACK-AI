from __future__ import annotations

import sys
import threading

import pytest

from jack_api.lifeline import watch_parent


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses a Job Object instead")
def test_triggers_when_reparented() -> None:
    parents = iter([100, 100, 1, 1, 1])
    fired = threading.Event()
    t = watch_parent(on_orphaned=fired.set, interval_s=0.01, getppid=lambda: next(parents))
    assert t is not None
    assert fired.wait(2)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses a Job Object instead")
def test_quiet_while_parent_alive() -> None:
    fired = threading.Event()
    watch_parent(on_orphaned=fired.set, interval_s=0.01, getppid=lambda: 100)
    assert not fired.wait(0.1)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses a Job Object instead")
def test_triggers_when_supervisor_dies_even_if_parent_unchanged() -> None:
    alive = iter([True, True, False])
    fired = threading.Event()
    watch_parent(on_orphaned=fired.set, interval_s=0.01, supervisor_pid=4242,
                 getppid=lambda: 100, is_alive=lambda _pid: next(alive, False))
    assert fired.wait(2)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")
def test_pid_alive() -> None:
    import os
    import subprocess

    from jack_api.lifeline import pid_alive

    assert pid_alive(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not pid_alive(p.pid)
