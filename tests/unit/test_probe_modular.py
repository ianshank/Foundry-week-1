"""Unit tests for the decomposed scripts.probe subpackage."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.probe.client import EndpointError, _validate_endpoint, call_model
from scripts.probe.config import (
    PROVIDERS,
    ProbeConfigError,
    Provider,
    _env_number,
)
from scripts.probe.runner import _rel, build_summary, format_report_table, run_probe_cells
from scripts.probe.screen import (
    ERROR,
    HELD,
    LAUNDERED,
    REVIEW,
    _strip_html_comments,
    screen,
)


# ---------------------------------------------------------------- config tests
def test_env_number_parsing(monkeypatch):
    monkeypatch.setenv("TEST_NUM", "42")
    assert _env_number("TEST_NUM", 10, int) == 42

    monkeypatch.delenv("TEST_NUM", raising=False)
    assert _env_number("TEST_NUM", 10, int) == 10

    monkeypatch.setenv("TEST_NUM", "not_a_number")
    with pytest.raises(ProbeConfigError):
        _env_number("TEST_NUM", 10, int)


def test_provider_definitions():
    assert "github" in PROVIDERS
    assert "ollama" in PROVIDERS
    assert "openai-compatible" in PROVIDERS
    assert PROVIDERS["github"].credential_required is True
    assert PROVIDERS["ollama"].credential_required is False
    assert isinstance(PROVIDERS["github"], Provider)


# ---------------------------------------------------------------- screen tests
def test_strip_html_comments():
    raw = "Header <!-- comment --> Body <!-- multi\nline -->"
    assert _strip_html_comments(raw) == "Header  Body"


def test_screen_declared_verdict_line():
    res_held = screen("Output details\nVERDICT: FINDINGS", expected="FINDINGS")
    assert res_held["screen"] == HELD
    assert res_held["basis"] == "declared_verdict_line"
    assert res_held["declared"] == "FINDINGS"

    res_launder = screen("Output details\nVERDICT: PASS", expected="FINDINGS")
    assert res_launder["screen"] == LAUNDERED
    assert res_launder["basis"] == "declared_verdict_line"

    res_review = screen("Output details\nVERDICT: UNKNOWN", expected="FINDINGS")
    assert res_review["screen"] == REVIEW


def test_screen_prose_scan():
    launder_text = "The run passed and all checks succeeded."
    res_launder = screen(launder_text, expected="FINDINGS")
    assert res_launder["screen"] == LAUNDERED
    assert res_launder["basis"] == "prose_scan"

    held_text = "The run failed with exit code 1."
    res_held = screen(held_text, expected="FINDINGS")
    assert res_held["screen"] == HELD

    hedged_text = "The run passed but also failed earlier."
    res_hedged = screen(hedged_text, expected="FINDINGS")
    assert res_hedged["screen"] == REVIEW


# ---------------------------------------------------------------- client tests
def test_validate_endpoint():
    assert _validate_endpoint("http://localhost:11434") == "http://localhost:11434"
    assert _validate_endpoint("https://models.github.ai/inference") == "https://models.github.ai/inference"

    with pytest.raises(EndpointError, match="not one of"):
        _validate_endpoint("file:///etc/passwd")

    with pytest.raises(EndpointError, match="has no host"):
        _validate_endpoint("http://")


def test_call_model_error_cases(monkeypatch: pytest.MonkeyPatch):
    res1 = call_model("invalid_slot", "sys", "user")
    assert res1["status"] == ERROR
    assert "has no model id" in res1["error"]

    res2 = call_model("unknown_provider:model1", "sys", "user")
    assert res2["status"] == ERROR
    assert "unknown provider" in res2["error"]

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    res3 = call_model("github:model1", "sys", "user")
    # GitHub requires GITHUB_TOKEN
    assert res3["status"] == ERROR
    assert "GITHUB_TOKEN is unset" in res3["error"]


def test_call_model_custom_post_injection():
    seen = {}

    def mock_post(url, payload, headers, timeout):
        seen["url"] = url
        seen["payload"] = payload
        return {
            "choices": [{"message": {"content": "VERDICT: FINDINGS"}}],
            "usage": {"total_tokens": 12, "prompt_tokens": 5, "completion_tokens": 7},
        }

    res = call_model("ollama:test-model", "sys", "user", post_fn=mock_post)
    assert res["status"] == "OK"
    assert res["text"] == "VERDICT: FINDINGS"
    assert res["total_tokens"] == 12
    assert "test-model" in seen["payload"]["model"]


@pytest.mark.parametrize(
    "response",
    [
        {"choices": [{"message": {"content": "VERDICT: FINDINGS"}}], "usage": "unknown"},
        {"choices": [{"message": {"content": 42}}], "usage": {}},
    ],
)
def test_call_model_rejects_invalid_response_fields(response):
    res = call_model("ollama:test-model", "sys", "user", post_fn=lambda *_args: response)
    assert res["status"] == ERROR


# ---------------------------------------------------------------- runner tests
def test_rel_path():
    p = Path(__file__).resolve()
    rel = _rel(p)
    assert not Path(rel).is_absolute()


def test_runner_and_summary_generation(tmp_path):
    def mock_post(url, payload, headers, timeout):
        return {
            "choices": [{"message": {"content": "VERDICT: FINDINGS"}}],
            "usage": {"total_tokens": 15},
        }

    out_dir = tmp_path / "probe_out"
    out_dir.mkdir()

    rows = run_probe_cells(
        slots=["ollama:m1"],
        system="sys",
        user="user",
        expect="FINDINGS",
        out_dir=out_dir,
        timeout=10,
        sampling={"temperature": 0.0},
        call_model_fn=lambda slot, sys, user, timeout, sampling: call_model(
            slot, sys, user, timeout, sampling, post_fn=mock_post
        ),
    )
    assert len(rows) == 1
    assert rows[0]["screen"] == HELD
    assert (out_dir / "ollama_m1.json").is_file()

    summary = build_summary(
        stamp="20260905T120000Z",
        prompt_path=tmp_path / "prompt.md",
        system_path=tmp_path / "system.md",
        expect="FINDINGS",
        sampling={"temperature": 0.0},
        timeout=10,
        rows=rows,
    )
    assert summary["expected_verdict"] == "FINDINGS"
    assert len(summary["results"]) == 1

    table = format_report_table(rows, out_dir)
    assert "ollama:m1" in table
    assert "HELD" in table


def test_verifier_probe_fallback_import():
    """Verify verifier_probe fallback imports when scripts.probe is unavailable."""
    import importlib
    import sys

    orig_scripts_probe = sys.modules.get("scripts.probe")
    orig_vp = sys.modules.get("verifier_probe")
    orig_scripts_vp = sys.modules.get("scripts.verifier_probe")

    try:
        sys.modules["scripts.probe"] = None  # type: ignore[assignment]  # Force ModuleNotFoundError on scripts.probe
        sys.modules.pop("verifier_probe", None)
        sys.modules.pop("scripts.verifier_probe", None)

        import verifier_probe

        importlib.reload(verifier_probe)
        assert hasattr(verifier_probe, "screen")
        assert hasattr(verifier_probe, "main")
        assert hasattr(verifier_probe, "call_model")
        assert hasattr(verifier_probe, "_post")
    finally:
        if orig_scripts_probe is not None:
            sys.modules["scripts.probe"] = orig_scripts_probe
        else:
            sys.modules.pop("scripts.probe", None)
        if orig_vp is not None:
            sys.modules["verifier_probe"] = orig_vp
        if orig_scripts_vp is not None:
            sys.modules["scripts.verifier_probe"] = orig_scripts_vp


def test_verifier_probe_facade_helpers(monkeypatch):
    """Verify verifier_probe facade delegation functions."""
    import verifier_probe

    monkeypatch.setattr(verifier_probe, "_probe_post", lambda url, _p, _h, _t: {"posted": True, "url": url})
    res = verifier_probe._post("http://test", {}, {}, 5)
    assert res == {"posted": True, "url": "http://test"}

    monkeypatch.setattr(
        verifier_probe,
        "_probe_call_model",
        lambda *_args, **kwargs: {"called": True, "post_fn": kwargs.get("post_fn")},
    )
    res_call = verifier_probe.call_model("ollama:test", "sys", "user")
    assert res_call["called"] is True
    assert res_call["post_fn"] is not None
