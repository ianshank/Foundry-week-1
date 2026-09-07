"""A real OpenAI-compatible HTTP endpoint for the AQA lane.

Not a mock and not a fixture: a `ThreadingHTTPServer` on loopback, bound to an
ephemeral port so tests can run in parallel and never collide. It exists so
the probe's transport is exercised by the transport, and it deliberately holds
no assertions -- the tests own those.

Port 0 rather than a constant: a hard-coded port makes the suite fail for
whoever already has that port, and makes two of these tests unrunnable at once.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from probe.cli import main as probe_main


def _handler_for(reply: str, status: int, body: bytes | None) -> type[BaseHTTPRequestHandler]:
    """Build a handler class closed over one scripted response."""

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            payload = body if body is not None else json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": reply}}],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                    },
                }
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            """Silence the default stderr access log; pytest captures enough."""

    return _Handler


@contextmanager
def live_llm_endpoint(
    reply: str = "VERDICT: FINDINGS\n- a real finding",
    *,
    status: int = 200,
    body: bytes | None = None,
) -> Iterator[str]:
    """Serve one scripted OpenAI-compatible reply; yield the `/v1` base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(reply, status, body))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_probe(
    base_url: str,
    out_dir: Path,
    *,
    models: str = "ollama:probe-test",
    expect: str = "FINDINGS",
    extra: list[str] | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    """Drive the probe CLI at `base_url` and return its exit code.

    `ollama` is the slot used throughout because it is the one provider whose
    `credential_required` is False, so the lane needs no secret to run.
    """
    monkeypatch.setenv("OLLAMA_ENDPOINT", base_url)
    argv = [
        "--models", models,
        "--expect", expect,
        "--timeout", "15",
        "--out", str(out_dir),
        *(extra or []),
    ]
    return probe_main(argv)


def read_summary(out_dir: Path) -> dict[str, Any]:
    """Parse the one `summary.json` the probe wrote under `out_dir`."""
    summaries = sorted(out_dir.glob("*/summary.json"))
    if len(summaries) != 1:
        raise AssertionError(f"expected exactly one summary.json under {out_dir}, got {summaries}")
    return json.loads(summaries[0].read_text(encoding="utf-8"))
