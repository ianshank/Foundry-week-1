"""OpenAI-compatible HTTP client for the probe."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    PROVIDERS,
)
from .screen import ERROR

ALLOWED_SCHEMES = frozenset({"http", "https"})


class EndpointError(ValueError):
    """An endpoint URL this script refuses to open."""


def _validate_endpoint(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise EndpointError(
            f"endpoint scheme {parsed.scheme!r} is not one of {sorted(ALLOWED_SCHEMES)}: {url}"
        )
    if not parsed.netloc:
        raise EndpointError(f"endpoint has no host: {url}")
    return url


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - scheme validated above
        _validate_endpoint(url),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8", errors="replace"))


def call_model(
    slot: str,
    system: str,
    user: str,
    timeout: int = DEFAULT_TIMEOUT,
    sampling: dict[str, Any] | None = None,
    post_fn: Any = None,
) -> dict[str, Any]:
    """Send one prompt to one `provider:model` slot. Never raises."""
    actual_post = post_fn if post_fn is not None else _post
    provider, _, model = slot.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if not model:
        return {"status": ERROR, "error": f"slot {slot!r} has no model id; use provider:model"}

    spec = PROVIDERS.get(provider)
    if spec is None:
        return {
            "status": ERROR,
            "error": f"unknown provider {provider!r}; use one of {sorted(PROVIDERS)}",
        }

    base = os.environ.get(spec.endpoint_env, spec.endpoint_default).rstrip("/")
    if not base:
        return {"status": ERROR, "error": f"{spec.endpoint_env} is unset"}

    credential = os.environ.get(spec.credential_env, "").strip()
    if spec.credential_required and not credential:
        return {
            "status": ERROR,
            "error": f"{spec.credential_env} is unset ({spec.credential_hint})",
        }
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        **(sampling or {"temperature": DEFAULT_TEMPERATURE, "max_tokens": DEFAULT_MAX_TOKENS}),
    }

    started = time.monotonic()
    try:
        body = actual_post(f"{base}/chat/completions", payload, headers, timeout)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        return {"status": ERROR, "error": f"HTTP {error.code}", "detail": detail}
    except EndpointError as error:
        return {"status": ERROR, "error": f"refused endpoint: {error}"}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"status": ERROR, "error": f"{type(error).__name__}: {error}"}
    except (json.JSONDecodeError, RecursionError) as error:
        return {
            "status": ERROR,
            "error": f"response was not usable JSON: {type(error).__name__}: {error}",
        }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        text = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return {"status": ERROR, "error": "no choices[0].message.content in response", "raw": body}
    if not isinstance(text, str):
        return {"status": ERROR, "error": "choices[0].message.content is not text", "raw": body}

    usage = body.get("usage")
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        return {"status": ERROR, "error": "usage is not an object", "raw": body}
    return {
        "status": "OK",
        "text": text,
        "latency_ms": elapsed_ms,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }
