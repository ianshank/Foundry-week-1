#!/usr/bin/env python3
"""Headless backstop for the bake-off's verifier cell (runbook step 2, prompt 2).

This module serves as the backwards-compatible CLI entry point and facade, delegating
to the modular `scripts.probe` package.
"""

from __future__ import annotations

import sys
import urllib
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

try:
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
except (ImportError, ModuleNotFoundError):
    from probe import (  # type: ignore[import-not-found,no-redef]  # noqa: E402
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
        screen,
    )
    from probe import (  # type: ignore[no-redef]  # noqa: E402
        _post as _probe_post,
    )
    from probe import (  # type: ignore[no-redef]  # noqa: E402
        call_model as _probe_call_model,
    )
    from probe import (  # type: ignore[no-redef]  # noqa: E402
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
    "call_model",
    "main",
    "screen",
    "urllib",
]

if __name__ == "__main__":
    sys.exit(main())
