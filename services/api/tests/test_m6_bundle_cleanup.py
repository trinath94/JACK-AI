"""Leftover copies of the frozen service are removed; the running copy and others are kept."""

from __future__ import annotations

import os
import time
from pathlib import Path

from jack_api.bundle_cleanup import MARKER, clean_stale_extractions


def _bundle(root: Path, name: str, *, ours: bool = True, age_s: float = 3600) -> Path:
    d = root / name
    (d / MARKER if ours else d / "something").mkdir(parents=True)
    (d / "big.bin").write_bytes(b"x" * 1024)
    t = time.time() - age_s
    os.utime(d, (t, t))
    return d


def test_only_stale_copies_of_jack_are_removed(tmp_path: Path) -> None:
    current = _bundle(tmp_path, "_MEI_current")
    stale = _bundle(tmp_path, "_MEI_crashed")
    fresh = _bundle(tmp_path, "_MEI_just_started", age_s=5)   # maybe another start in progress
    other = _bundle(tmp_path, "_MEI_other_app", ours=False)  # some other PyInstaller program
    plain = tmp_path / "unrelated"
    plain.mkdir()
    assert clean_stale_extractions(current) == 1
    assert not stale.exists()
    assert current.exists() and fresh.exists() and other.exists() and plain.exists()


def test_not_frozen_does_nothing() -> None:
    assert clean_stale_extractions(None) == 0
