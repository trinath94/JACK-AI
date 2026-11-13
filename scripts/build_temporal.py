"""Build the Temporal CLI (dev server) that JACK runs as a sidecar, from verified source.

The official release binaries aren't on a package registry, so JACK builds the pinned release
from the Go module proxy. Every module is checked against Go's checksum database (sum.golang.org),
and the two source modules are additionally checked against the hashes pinned below.

Usage: python scripts/build_temporal.py <output path> [--goos windows --goarch amd64]
Requires Go (any recent version; the pinned toolchain is fetched through the module proxy).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "v1.9.1"                      # Temporal CLI; bundles Temporal Server 1.32.0
COMMIT = "1de87a9f26991bf4f5c0a5ff96f2cea8d7a3cbde"
MODULE_SUM = "h1:8JXIJyo6H5UPjdw0PSoizOZvlcEEy2R3UBfRD5Obju0="
CLIEXT_VERSION = "v0.0.0-20260914181643-1de87a9f2699"   # nested module at the same commit
CLIEXT_SUM = "h1:bk74/z2yuWsBlCk6E4fIpMA7T79GRdA3hATc4gHtJYQ="
TOOLCHAIN = "go1.26.8"


def go(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    e = {**os.environ, "GOTOOLCHAIN": TOOLCHAIN, "GOFLAGS": "-mod=readonly", **(env or {})}
    r = subprocess.run(["go", *args], cwd=cwd, env=e, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"go {' '.join(args[:3])} failed")
    return r.stdout


def download(module: str, version: str, expected_sum: str) -> Path:
    info = json.loads(go(["mod", "download", "-json", f"{module}@{version}"]))
    if info.get("Sum") != expected_sum:
        raise SystemExit(f"{module}@{version}: checksum {info.get('Sum')} != pinned {expected_sum}")
    return Path(info["Dir"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--goos", default=None)
    ap.add_argument("--goarch", default="amd64")
    a = ap.parse_args()
    out = Path(a.output).resolve()
    src = download("github.com/temporalio/cli", VERSION, MODULE_SUM)
    cliext = download("github.com/temporalio/cli/cliext", CLIEXT_VERSION, CLIEXT_SUM)
    with tempfile.TemporaryDirectory(prefix="temporal-src-") as tmp:
        work = Path(tmp) / "cli"
        shutil.copytree(src, work)
        shutil.rmtree(work / "cliext", ignore_errors=True)
        shutil.copytree(cliext, work / "cliext")
        for p in work.rglob("*"):
            p.chmod(p.stat().st_mode | 0o200)
        env = {"CGO_ENABLED": "0", "GOARCH": a.goarch}
        if a.goos:
            env["GOOS"] = a.goos
        out.parent.mkdir(parents=True, exist_ok=True)
        ldflags = f"-s -w -X github.com/temporalio/cli/internal/temporalcli.Version={VERSION[1:]}"
        go(["build", "-trimpath", "-ldflags", ldflags, "-o", str(out), "./cmd/temporal"],
           cwd=work, env=env)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"temporal {VERSION} -> {out} ({out.stat().st_size // (1 << 20)} MB, sha256 {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
