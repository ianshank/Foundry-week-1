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

# Named constants for the same reason `foundry_spike_mcp.config` uses them: a
# typo in an inline literal is a silently-ignored setting. These were read as
# bare strings in `cli.py`, which also kept them invisible to the suite's
# isolation fixture -- and `PROBE_TIMEOUT=abc` in a shell makes `main` exit 2
# through `parser.error` before it reaches a model, which is the same exit
# code `tests/regression/test_probe_exit_contract.py` reads as "no model
# answered". Three guards went green having never run.
ENV_PROBE_MODELS = "PROBE_MODELS"
ENV_PROBE_LIVE = "PROBE_LIVE"
ENV_PROBE_TIMEOUT = "PROBE_TIMEOUT"
ENV_PROBE_TEMPERATURE = "PROBE_TEMPERATURE"
ENV_PROBE_TOP_P = "PROBE_TOP_P"
ENV_PROBE_MAX_TOKENS = "PROBE_MAX_TOKENS"

#: The subset the test suite clears before every test.
#:
#: `ENV_PROBE_LIVE` and `ENV_PROBE_MODELS` are deliberately absent, as are the
#: provider endpoint and credential names reachable through `PROVIDERS`: the
#: opt-in live lane (`make test-live`, `tests/aqa/test_aqa_live_llm.py`) is
#: configured through exactly those, so clearing them would not isolate that
#: lane, it would delete it. Everything listed here is a sampling knob that no
#: test should ever inherit from a developer's shell.
ISOLATED_ENV: tuple[str, ...] = (
    ENV_PROBE_TIMEOUT,
    ENV_PROBE_TEMPERATURE,
    ENV_PROBE_TOP_P,
    ENV_PROBE_MAX_TOKENS,
)


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
