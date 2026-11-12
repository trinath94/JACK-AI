"""Exit when the supervising desktop process disappears (POSIX).

The Tauri supervisor sets ``JACK_EXIT_WITH_PARENT=1`` and ``JACK_SUPERVISOR_PID``. We shut
down gracefully when either
  * the supervisor PID no longer exists (covers the desktop app being SIGKILLed while the
    PyInstaller one-file bootloader between us survives), or
  * our own parent changes (we were re-parented because the bootloader died).
On Windows the supervisor's Job Object provides this guarantee instead.
"""

from __future__ import annotations

import errno
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # signal 0: existence/permission check only (POSIX)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def watch_parent(
    on_orphaned: Callable[[], None] | None = None,
    interval_s: float = 1.0,
    supervisor_pid: int | None = None,
    getppid: Callable[[], int] = os.getppid,
    is_alive: Callable[[int], bool] = pid_alive,
) -> threading.Thread | None:
    if sys.platform == "win32":
        return None
    original_parent = getppid()
    stop = on_orphaned or (lambda: os.kill(os.getpid(), signal.SIGTERM))
    done = threading.Event()

    def run() -> None:
        while not done.wait(interval_s):
            if supervisor_pid is not None and not is_alive(supervisor_pid):
                log.warning("supervisor process %d is gone; shutting down", supervisor_pid)
            elif getppid() != original_parent:
                log.warning("parent process %d is gone; shutting down", original_parent)
            else:
                continue
            stop()
            return

    t = threading.Thread(target=run, name="jack-lifeline", daemon=True)
    t.start()
    return t
