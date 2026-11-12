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
