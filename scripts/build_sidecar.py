"""Freeze services/api into a single-file executable for the Tauri sidecar.

Output: apps/desktop/src-tauri/binaries/jack-service-<rust-target-triple>[.exe]
(Tauri's `externalBin` naming convention).

Usage (from repo root):  uv run --project services/api python scripts/build_sidecar.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
OUT = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"


def target_triple() -> str:
    if env := os.environ.get("TAURI_TARGET_TRIPLE"):
        return env
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("could not determine rust host triple")


def main() -> int:
    triple = target_triple()
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    work = API / "build" / "pyinstaller"
    migrations = API / "src" / "jack_api" / "migrations"
    sep = os.pathsep
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "jack-service",
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "build"),
        "--specpath", str(work),
        "--paths", str(API / "src"),
        # Alembic loads env.py and revision files from disk by path.
        "--add-data", f"{migrations}{sep}jack_api/migrations",
        "--collect-submodules", "uvicorn",
        # Speech stack (M3): native libraries and model assets are not found by import
        # analysis alone.
        "--collect-all", "ctranslate2",
        "--collect-data", "faster_whisper",  # bundled Silero VAD model
        "--collect-binaries", "onnxruntime",
        "--collect-data", "onnxruntime",
        "--collect-all", "tokenizers",
        "--collect-binaries", "av",
        "--hidden-import", "jack_api.app",
        # Console subsystem on purpose: the supervisor spawns with CREATE_NO_WINDOW, and a
        # windowed build would leave sys.stderr = None and break logging.
        "--console",
        str(API / "src" / "jack_api" / "__main__.py"),
    ]
    if sys.platform == "win32":
        cmd[-1:-1] = ["--collect-submodules", "comtypes"]  # SAPI text-to-speech via COM
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=API)

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"jack-service-{triple}{exe_suffix}"
    dest.unlink(missing_ok=True)
    shutil.copy2(work / "dist" / f"jack-service{exe_suffix}", dest)
    print(f"sidecar -> {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
