"""Remove copies of the frozen service left behind by crashes.

The packaged service is a PyInstaller one-file executable: each start unpacks it (≈560 MB with
the embedded PostgreSQL) into a ``_MEI…`` folder in the temp directory, which is deleted on a
normal exit but not when the process is killed — exactly the crashes Milestone 6 recovers from.
At start-up JACK deletes earlier copies of *its own* bundle (recognised by its migrations
folder), never the running one, and never a folder a live process is executing from.
"""

from __future__ import annotations

import logging
import shutil
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
MARKER = Path("jack_api") / "migrations"
MIN_AGE_S = 60


def _in_use(folder: Path) -> bool:
    try:
        import psutil

        for p in psutil.process_iter(["exe"]):
            exe = p.info.get("exe")
            if exe and Path(exe).is_relative_to(folder):
                return True
    except Exception:  # noqa: BLE001 - when unsure, keep the folder
        return True
    return False


def clean_stale_extractions(current: Path | None = None) -> int:
    me = current or (Path(sys._MEIPASS) if getattr(sys, "_MEIPASS", None) else None)  # type: ignore[attr-defined]
    if me is None:
        return 0
    removed = 0
    for d in me.parent.glob("_MEI*"):
        try:
            if d.resolve() == me.resolve() or not d.is_dir() or not (d / MARKER).is_dir():
                continue
            if time.time() - d.stat().st_mtime < MIN_AGE_S or _in_use(d):
                continue
            shutil.rmtree(d)  # on Windows, files still in use make this fail: then it stays
            removed += 1
        except OSError:
            continue
    if removed:
        log.info("removed %d unpacked service cop%s left by earlier crashes", removed,
                 "y" if removed == 1 else "ies")
    return removed


def clean_in_background() -> None:
    threading.Thread(target=clean_stale_extractions, name="bundle-cleanup", daemon=True).start()
