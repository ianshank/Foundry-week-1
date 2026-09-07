"""Regression guard: D-03 -- the probe must not exit 0 on a run that never happened.

Before this guard, `main` returned `1 if any laundered else 0`. One byte
carried one fact (did anything launder) while every caller read two (did the
run happen, and did it launder). An unreachable endpoint, a misspelled
provider and a missing credential all produced exit 0, so `make probe` was
green for a bake-off in which no model was ever contacted.

The three cases below are the three ways a row reaches ERROR without any
network being available, which is what makes them runnable anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probe.cli import main as probe_main

pytestmark = pytest.mark.regression

NO_USABLE_ROW = 2


def _run(out_dir: Path, models: str) -> int:
    return probe_main(["--models", models, "--expect", "FINDINGS",
                       "--timeout", "5", "--out", str(out_dir)])


def test_unknown_provider_does_not_exit_zero(tmp_path: Path) -> None:
    """A misspelled provider never reaches a model, so the run is not usable."""
    assert _run(tmp_path, "notaprovider:some-model") == NO_USABLE_ROW


def test_missing_required_credential_does_not_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """github requires a token; without one the slot errors before any request."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert _run(tmp_path, "github:gpt-4o") == NO_USABLE_ROW


def test_unset_endpoint_does_not_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openai-compatible has no default endpoint; unset means no request."""
    monkeypatch.delenv("OPENAI_COMPATIBLE_ENDPOINT", raising=False)
    assert _run(tmp_path, "openai-compatible:whatever") == NO_USABLE_ROW
