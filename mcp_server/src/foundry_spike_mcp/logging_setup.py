"""Logging for a stdio MCP server, where stdout is not yours to write to.

**The sharp edge:** an MCP stdio server speaks JSON-RPC over stdout. A single
stray `print()`, a library that logs to stdout, or `logging.basicConfig()`
with its default handler pointed the wrong way, and the client sees a framed
message with garbage in it. The symptom is not a log line in the wrong place;
it is the tool silently disappearing from Agent Builder, or a parse error with
no obvious cause. Every handler this module installs writes to **stderr**, and
`test_logging.py` asserts it -- because this is exactly the kind of invariant
that survives review and dies to a convenience `print` three weeks later.

**What gets logged.** Enough to answer "why did that call return BLOCKED?"
without re-running it: the resolved argv, the exit code, the duration, and the
reason attached to every refusal. Never the findings payload (it is large and
it is the caller's to read), and never raw stderr (it goes through
`guards.clean` first, at the call site).

**Levels.** Default WARNING, so a normally-behaving server is silent and the
operator's terminal stays readable. `FOUNDRY_SPIKE_LOG_LEVEL=DEBUG` turns on
the per-call detail that session 3 and 4 will want when a tool misbehaves
inside the Toolkit and there is no other window into it.

**Format.** `text` by default for a human at a terminal; `json` for when a
trace is going into evidence and needs to be machine-readable alongside the
`traces/` captures.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any

from .config import LogConfig, load_log_config

LOGGER_NAME = "foundry_spike_mcp"

#: Keys that carry structured context on a log record. Anything else attached
#: via `extra=` still works, but these are the ones the JSON formatter lifts to
#: the top level so a trace can be grepped by them.
_CONTEXT_KEYS = (
    "tool",
    "verdict",
    "exit_code",
    "blocked_reason",
    "duration_ms",
    "target",
    "run_id",
    "command",
)

_configured = False


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, with known context keys lifted to the top."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """Human format with the context keys appended as `k=v` pairs."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        pairs = [
            f"{key}={getattr(record, key)!r}"
            for key in _CONTEXT_KEYS
            if getattr(record, key, None) is not None
        ]
        return f"{base} {' '.join(pairs)}" if pairs else base


def configure(config: LogConfig | None = None, *, force: bool = False) -> logging.Logger:
    """Install the stderr handler. Idempotent unless `force`.

    Idempotence matters: `configure()` is called from the server entry point
    *and* defensively from the tool modules, so that a caller importing
    `lint_openspec` as a library still gets diagnostics. Without the guard
    that would stack handlers and duplicate every line.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured and not force:
        return logger
    if force:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)

    config = config or load_log_config()
    # stderr. Not stdout. See the module docstring -- this single argument is
    # the difference between a working server and an unexplainable one.
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter() if config.fmt == "json" else _TextFormatter())
    logger.addHandler(handler)

    level = getattr(logging, config.level, None)
    logger.setLevel(level if isinstance(level, int) else logging.WARNING)
    # Do not hand records to the root logger, whose handlers this module does
    # not control and cannot promise are pointed at stderr.
    logger.propagate = False
    _configured = True
    return logger


def get_logger(suffix: str | None = None) -> logging.Logger:
    """Child logger under the package namespace, configured on first use."""
    configure()
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}" if suffix else LOGGER_NAME)


def log_result(logger: logging.Logger, tool: str, result: Mapping[str, Any]) -> None:
    """Emit one record per tool call, at a level matched to the verdict.

    BLOCKED is a WARNING: it is not an error -- the contract says so, loudly --
    but it is the state an operator most often needs to explain, and it is the
    one that should not require DEBUG to see.
    """
    verdict = result.get("verdict")
    context = {
        "tool": tool,
        "verdict": verdict,
        "exit_code": result.get("exit_code"),
        "blocked_reason": result.get("blocked_reason"),
        "duration_ms": result.get("duration_ms"),
        "target": result.get("target"),
        "run_id": result.get("run_id"),
    }
    context = {key: value for key, value in context.items() if value is not None}
    if verdict == "BLOCKED":
        logger.warning("%s could not evaluate", tool, extra=context)
    else:
        logger.info("%s returned %s", tool, verdict, extra=context)
