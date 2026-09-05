"""Configuration and provider definitions for the verifier probe."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PROBES = REPO / "configs" / "probes"

DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_TOKENS = 800
DEFAULT_TIMEOUT = 180


class ProbeConfigError(ValueError):
    """A PROBE_* variable was set to something unusable."""


def _env_number(name: str, default: float, cast: Any) -> Any:
    """Read one numeric setting. Absent -> default; malformed -> raise."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError as error:
        raise ProbeConfigError(f"{name}={raw!r} is not a valid {cast.__name__}") from error


@dataclass(frozen=True)
class Provider:
    """Where one provider's OpenAI-compatible endpoint and credential live."""

    endpoint_env: str
    endpoint_default: str
    credential_env: str
    credential_hint: str
    credential_required: bool = False


PROVIDERS: dict[str, Provider] = {
    "github": Provider(
        endpoint_env="GITHUB_MODELS_ENDPOINT",
        endpoint_default="https://models.github.ai/inference",
        credential_env="GITHUB_TOKEN",  # noqa: S106 - an env var name, not a value
        credential_hint="a fine-grained PAT with the models:read permission",
        credential_required=True,
    ),
    "ollama": Provider(
        endpoint_env="OLLAMA_ENDPOINT",
        endpoint_default="http://localhost:11434/v1",
        credential_env="OLLAMA_API_KEY",  # noqa: S106 - an env var name, not a value
        credential_hint="not needed for a local Ollama",
    ),
    "openai-compatible": Provider(
        endpoint_env="OPENAI_COMPATIBLE_ENDPOINT",
        endpoint_default="",
        credential_env="OPENAI_COMPATIBLE_KEY",  # noqa: S106 - an env var name, not a value
        credential_hint="whatever the endpoint expects, if anything",
    ),
}
