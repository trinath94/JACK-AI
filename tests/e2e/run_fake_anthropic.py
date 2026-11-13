"""Run the fake Anthropic Messages API (services/api/tests/fake_anthropic.py) for e2e tests.

Usage: uv run --project services/api python tests/e2e/run_fake_anthropic.py <port-file>
Writes the base URL to <port-file>, logs each request as a JSON line next to it, and runs
until terminated.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "api" / "tests"))

from fake_anthropic import FakeAnthropic  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1])
    log = out.with_suffix(".requests.jsonl")
    stop = False

    def handle(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle)
    with FakeAnthropic() as fake:
        out.write_text(fake.base_url)
        seen = 0
        while not stop:
            while seen < len(fake.requests):
                r = fake.requests[seen]
                # Never log the credential itself, only that one was presented.
                auth = r["headers"].get("authorization", "")
                with log.open("a") as f:
                    f.write(json.dumps({"model": r["body"].get("model"),
                                        "bearer_present": auth.startswith("Bearer sk-ant-"),
                                        "effort": (r["body"].get("output_config") or {}).get("effort"),
                                        "fallbacks": r["body"].get("fallbacks")}) + "\n")
                seen += 1
            time.sleep(0.1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
