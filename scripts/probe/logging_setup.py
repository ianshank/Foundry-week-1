"""Logging for the probe plane.

`scripts/probe/` had no logging at all. Every diagnostic was a bare
`print(..., file=sys.stderr)`, which meant an operator seeing the probe exit 2
could not tell "no endpoint answered" from "PROBE_TIMEOUT was malformed and
argparse exited" -- both are exit 2, and nothing recorded which one happened.
That ambiguity is the same class of defect the exit code itself was widened to
fix; the runtime half was left open.

This reuses `foundry_spike_mcp.logging_setup` rather than defining a second
logging discipline, for the reason `scan_evidence.py` gives for reusing
`guards.SECRET_PATTERNS`: two definitions of one thing drift, and the one that
drifts is the one nobody reads. That module already enforces the property that
matters here -- **handlers write to stderr, never stdout** -- and already
supports `FOUNDRY_SPIKE_LOG_FORMAT=json` for records that land in evidence.

The import is guarded because the probe must keep running when the package is
not importable: the Docker `contract` stage installs nothing, and `make probe`
puts only the repo root and `scripts/` on the path. A probe that refused to run
because it could not configure logging would be a worse failure than one that
runs quietly.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PACKAGE_SRC = _REPO / "mcp_server" / "src"
if str(_PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SRC))

try:
    from foundry_spike_mcp.logging_setup import configure as _configure
    from foundry_spike_mcp.logging_setup import get_logger as _get_logger

    _SHARED = True
except ImportError:  # pragma: no cover - the package is absent from this tree
    _SHARED = False


def get_logger(suffix: str) -> logging.Logger:
    """A stderr logger for one probe module.

    Falls back to a plain stdlib logger with an explicit stderr handler when
    the package is unavailable, so the stdout-is-JSON-RPC invariant holds
    either way.
    """
    if _SHARED:
        return _get_logger(f"probe.{suffix}")

    logger = logging.getLogger(f"foundry_spike_mcp.probe.{suffix}")
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    return logger


def configure(verbose: bool = False) -> None:
    """Set the level once, at the CLI boundary.

    `--verbose` maps to the same `FOUNDRY_SPIKE_LOG_LEVEL=DEBUG` the server
    honours, so one switch means the same thing on both planes rather than the
    probe inventing a second vocabulary.
    """
    if _SHARED:
        _configure(force=True)
    root = logging.getLogger("foundry_spike_mcp")
    if verbose:
        root.setLevel(logging.DEBUG)
