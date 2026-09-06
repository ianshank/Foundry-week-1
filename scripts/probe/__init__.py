"""The verifier probe subpackage."""

from __future__ import annotations

from .cli import build_parser, main
from .client import (
    ALLOWED_SCHEMES,
    EndpointError,
    _post,
    _validate_endpoint,
    call_model,
)
from .config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DEFAULT_TOP_P,
    PROBES,
    PROVIDERS,
    REPO,
    ProbeConfigError,
    Provider,
    _env_number,
)
from .runner import build_summary, format_report_table, run_probe_cells
from .screen import (
    _HELD,
    _LAUNDER,
    _NEGATION_BEFORE,
    ERROR,
    HELD,
    LAUNDERED,
    REVIEW,
    VERDICT_LINE,
    _strip_html_comments,
    _unnegated_hit,
    screen,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TOP_P",
    "ERROR",
    "EndpointError",
    "HELD",
    "LAUNDERED",
    "PROBES",
    "PROVIDERS",
    "ProbeConfigError",
    "Provider",
    "REPO",
    "REVIEW",
    "VERDICT_LINE",
    "_HELD",
    "_LAUNDER",
    "_NEGATION_BEFORE",
    "_env_number",
    "_post",
    "_strip_html_comments",
    "_unnegated_hit",
    "_validate_endpoint",
    "build_parser",
    "build_summary",
    "call_model",
    "format_report_table",
    "main",
    "run_probe_cells",
    "screen",
]
