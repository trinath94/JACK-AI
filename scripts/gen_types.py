"""Regenerate packages/shared-types from the service OpenAPI schema.

Usage: uv run --project services/api python scripts/gen_types.py [--check]
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packages" / "shared-types"


def main() -> int:
    from jack_api.app import create_app
    from jack_api.config import Settings

    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(Settings(session_token="x" * 64, data_dir=Path(tmp)))
        schema = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    target = PKG / "openapi.json"
    gen = PKG / "src" / "api.gen.ts"
    before = (target.read_text() if target.exists() else "",
              gen.read_text() if gen.exists() else "")
    target.write_text(schema)
    pnpm = "pnpm.cmd" if sys.platform == "win32" else "pnpm"
    subprocess.run([pnpm, "--filter", "@jack/shared-types", "run", "generate"],
                   check=True, cwd=ROOT)
    after = (target.read_text(), gen.read_text())
    if "--check" in sys.argv and before != after:
        print("shared-types are out of date: run `pnpm gen:types` and commit", file=sys.stderr)
        return 1
    print("shared-types up to date" if before == after else "shared-types regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
