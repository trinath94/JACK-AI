"""Exit when the supervising process disappears (POSIX).

The Tauri supervisor sets ``JACK_EXIT_WITH_PARENT=1``. If our parent dies (including the
PyInstaller one-file bootloader being SIGKILLed), the kernel re-parents us and
``os.getppid()`` changes; we then request a graceful shutdown so no orphaned service keeps
running with a stale token. On Windows the supervisor's Job Object provides this guarantee.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


def watch_parent(
    on_orphaned: Callable[[], None] | None = None,
    interval_s: float = 1.0,
    getppid: Callable[[], int] = os.getppid,
) -> threading.Thread | None:
    if sys.platform == "win32":
        return None
    original = getppid()
    stop = on_orphaned or (lambda: os.kill(os.getpid(), signal.SIGTERM))
    done = threading.Event()

    def run() -> None:
        while not done.wait(interval_s):
            if getppid() != original:
                log.warning("supervisor process %d is gone; shutting down", original)
                stop()
                return

    t = threading.Thread(target=run, name="jack-lifeline", daemon=True)
    t.start()
    return t
