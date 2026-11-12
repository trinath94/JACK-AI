"""Entry point: ``jack-service`` / ``python -m jack_api``.

Launched by the Tauri supervisor with JACK_SESSION_TOKEN and JACK_PORT in the environment.
"""

from __future__ import annotations

import logging
import sys

import uvicorn
from pydantic import ValidationError

from jack_api import redaction
from jack_api.app import create_app
from jack_api.config import Settings


def main() -> int:
    try:
        settings = Settings()  # values come from the environment
    except ValidationError as exc:
        # Do not echo the input values: they may contain the token.
        fields = ", ".join(".".join(map(str, e["loc"])) + f" ({e['msg']})" for e in exc.errors())
        print(f"jack-service: invalid configuration: {fields}", file=sys.stderr)
        return 2
    redaction.install(settings.log_level)
    redaction.register_secret(settings.session_token.get_secret_value())
    app = create_app(settings)
    logging.getLogger(__name__).info("starting jack-service on %s:%d", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None,
                access_log=False, ws_max_size=1 << 20, timeout_graceful_shutdown=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
