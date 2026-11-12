"""A local stand-in for the Anthropic Messages API, served over real HTTP so the official SDK
runs its normal request/response path (auth header, JSON parsing, typed errors)."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

VALID_KEY = "sk-ant-api03-" + "T" * 40


def presented_key(request: Request) -> str | None:
    """SDK 2.x sends the key as a Bearer token (API version 2026-10-21); older ones used
    x-api-key. Accept both, as the API does."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.headers.get("x-api-key")


class FakeAnthropic:
    def __init__(self) -> None:
        self.mode = "ok"  # ok | rate_limit | server_error | refusal | fallback
        self.reply = "OK"
        self.usage = {"input_tokens": 12, "output_tokens": 5,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.requests: list[dict[str, Any]] = []
        self.app = FastAPI()
        self._routes()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                     log_level="warning"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> FakeAnthropic:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        return self

    def __exit__(self, *_: object) -> None:
        self._server.should_exit = True
        self._thread.join(5)

    def _routes(self) -> None:
        app = self.app

        def error(status: int, etype: str, message: str) -> JSONResponse:
            return JSONResponse(status_code=status, headers={"request-id": "req_fake_err"},
                                content={"type": "error",
                                         "error": {"type": etype, "message": message}})

        @app.post("/v1/messages")
        async def messages(request: Request) -> Any:
            body = await request.json()
            self.requests.append({"headers": dict(request.headers), "body": body,
                                  "query": dict(request.query_params)})
            if presented_key(request) != VALID_KEY:
                return error(401, "authentication_error", "invalid API key")
            if self.mode == "rate_limit":
                return error(429, "rate_limit_error", "slow down")
            if self.mode == "server_error":
                return error(500, "api_error", "boom")
            model = body["model"]
            content: list[dict[str, Any]] = [{"type": "text", "text": self.reply}]
            usage: dict[str, Any] = dict(self.usage)
            stop_reason, stop_details = "end_turn", None
            served = model
            if self.mode == "refusal":
                content = []
                stop_reason = "refusal"
                stop_details = {"type": "refusal", "category": "cyber", "explanation": "no"}
            elif self.mode == "fallback":
                served = "claude-opus-4-8"
                content = [{"type": "fallback", "from": {"model": model},
                            "to": {"model": served}, "trigger": {"type": "refusal"}},
                           {"type": "text", "text": self.reply}]
                usage["iterations"] = [
                    {"type": "message", "model": model, "input_tokens": 100,
                     "output_tokens": 10, "cache_read_input_tokens": 0,
                     "cache_creation_input_tokens": 0},
                    {"type": "fallback_message", "model": served, "input_tokens": 100,
                     "output_tokens": 50, "cache_read_input_tokens": 0,
                     "cache_creation_input_tokens": 0},
                ]
            return JSONResponse(headers={"request-id": "req_fake_123"}, content={
                "id": "msg_fake", "type": "message", "role": "assistant", "model": served,
                "content": content, "stop_reason": stop_reason, "stop_sequence": None,
                "stop_details": stop_details, "usage": usage})

        @app.get("/v1/models")
        async def models(request: Request) -> Any:
            if presented_key(request) != VALID_KEY:
                return error(401, "authentication_error", "invalid API key")
            data = [{"type": "model", "id": i, "display_name": n,
                     "created_at": "2026-01-01T00:00:00Z",
                     "max_input_tokens": 1_000_000, "max_tokens": 128_000}
                    for i, n in (("claude-opus-5-5", "Claude Opus 5.5"),
                                 ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
                                 ("claude-future-9", "Claude Future 9"))]
            return {"data": data, "has_more": False, "first_id": data[0]["id"],
                    "last_id": data[-1]["id"]}


FAKE_CLAUDE = r"""#!/bin/sh
# Stand-in for the Claude Code CLI. Records how it was called.
LOG="$(dirname "$0")/calls.log"
echo "ARGS: $*" >> "$LOG"
if [ -n "$JACK_SESSION_TOKEN" ]; then echo "LEAK: JACK_SESSION_TOKEN" >> "$LOG"; fi
echo "CWD: $(pwd)" >> "$LOG"
echo "CWD_FILES: $(ls -A | wc -l)" >> "$LOG"
case "$1" in
  --version) echo "2.1.322 (Claude Code)"; exit 0 ;;
  auth) echo '{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty"}'; exit 0 ;;
  -p)
    PROMPT="$(cat)"
    echo "STDIN: $PROMPT" >> "$LOG"
    if [ -f "$(dirname "$0")/fail" ]; then echo "Error: not logged in" >&2; exit 1; fi
    printf '{"type":"result","subtype":"success","is_error":false,"result":"Hello from Claude Code","total_cost_usd":0.0421,"usage":{"input_tokens":30,"output_tokens":7,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"modelUsage":{"claude-sonnet-5-5":{"inputTokens":30,"outputTokens":7,"cacheReadInputTokens":0,"cacheCreationInputTokens":0}}}\n'
    exit 0 ;;
esac
exit 2
"""
