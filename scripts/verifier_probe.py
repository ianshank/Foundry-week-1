#!/usr/bin/env python3
"""Headless backstop for the bake-off's verifier cell (runbook step 2, prompt 2).

This module serves as the backwards-compatible CLI entry point and facade, delegating
to the modular `scripts.probe` package.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

# One arm, not two.
#
# The `except (ImportError, ModuleNotFoundError)` fallback that used to sit
# here was unreachable: the `sys.path` inserts above run first, so
# `scripts.probe` always resolves. It showed as covered only because
# `tests/unit/test_probe_modular.py` set `sys.modules['scripts.probe'] = None`
# to manufacture the failure -- a test of a fallback, not a use of one, which
# is how 35 dead lines came to read as 100% covered.
#
# `scripts.` is the spelling mypy resolves: `mypy_path` has the repo root and
# not `scripts/`, because adding the latter would make every script a
# duplicate module.
from scripts.probe import (  # noqa: E402
    _HELD,
    _LAUNDER,
    _NEGATION_BEFORE,
    ALLOWED_SCHEMES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DEFAULT_TOP_P,
    ERROR,
    HELD,
    LAUNDERED,
    PROBES,
    PROVIDERS,
    REVIEW,
    VERDICT_LINE,
    EndpointError,
    ProbeConfigError,
    Provider,
    _env_number,
    _strip_html_comments,
    _unnegated_hit,
    _validate_endpoint,
    build_parser,
    build_summary,
    format_report_table,
    run_probe_cells,
    screen,
)
from scripts.probe import (  # noqa: E402
    _post as _probe_post,
)
from scripts.probe import (  # noqa: E402
    call_model as _probe_call_model,
)
from scripts.probe import (  # noqa: E402
    main as _probe_main,
)


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    return _probe_post(url, payload, headers, timeout)


def call_model(*args: Any, **kwargs: Any) -> dict[str, Any]:
    if "_post" in globals():
        kwargs.setdefault("post_fn", globals()["_post"])
    return _probe_call_model(*args, **kwargs)


def main(argv: list[str] | None = None) -> int:
    return _probe_main(argv, call_model_fn=globals().get("call_model"))


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
    "main",
    "format_report_table",
    "run_probe_cells",
    "screen",
]

if __name__ == "__main__":
    sys.exit(main())
