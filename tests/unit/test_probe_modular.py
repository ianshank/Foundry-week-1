"""Unit tests for the decomposed scripts.probe subpackage."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from scripts.probe.client import EndpointError, _validate_endpoint, call_model
from scripts.probe.config import (
    HTTP_ERROR_DETAIL_CHARS,
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


def test_the_facade_exports_exactly_what_the_package_does():
    """`verifier_probe` is advertised as the backwards-compatible facade.

    It was not one. `probe.__all__` listed `build_parser`, `build_summary`,
    `format_report_table` and `run_probe_cells`; the facade neither imported
    nor re-exported them, so `from verifier_probe import build_parser` raised
    `ImportError` while the package advertised the name. And the facade
    listed `urllib`, which `probe` does not export -- a facade that *adds*
    surface is not a facade.

    This matters more than a tidy `__all__`: `verifier_probe` is the name in
    `docs/architecture/C4.md`, two Makefile targets, two shipped skills and
    one shipped agent. It is the published interface, and it was a strict
    subset of the thing it fronts.

    Three checks, because the first two alone allow a name to be listed and
    never imported -- which is the shape the drift actually had.
    """
    import probe
    import verifier_probe

    missing = sorted(set(probe.__all__) - set(verifier_probe.__all__))
    assert not missing, f"probe exports {missing}; the facade does not"

    extra = sorted(set(verifier_probe.__all__) - set(probe.__all__))
    assert not extra, (
        f"the facade exports {extra} that `probe` does not. A facade that "
        "adds surface is not a facade."
    )

    unbound = [name for name in verifier_probe.__all__ if not hasattr(verifier_probe, name)]
    assert not unbound, f"listed in __all__ and never imported: {unbound}"


def test_the_facade_repo_root_is_the_package_repo_root():
    """`REPO` is on the backwards-compatibility list and is bound twice --
    once locally at module top, then again by the names imported from
    `probe.config` (`parents[2]` there against `parents[1]` here, resolving to
    the same directory). Pinned so a reordering cannot silently change it."""
    import probe
    import verifier_probe

    assert verifier_probe.REPO == probe.REPO


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


# ---------------------------------------------------------------------------
# The recovery paths somebody wrote and nobody fired.
#
# Each of these is an `except` arm whose comment explains a real failure and
# whose body has never executed. A recovery path that has never run is a
# hypothesis about what happens when things go wrong, not a behaviour -- and
# these are the arms that decide whether a spent run is recorded or lost.
# ---------------------------------------------------------------------------


def test_a_transcript_that_cannot_be_written_does_not_lose_the_run(tmp_path, monkeypatch):
    """The most expensive possible failure, per the code's own comment.

    `runner.py` says it plainly: "The model has already been called and the
    tokens already spent, so losing the run because the transcript could not be
    written is the most expensive possible failure." The row stays in memory,
    gets a `transcript_error`, and still reaches `summary.json`.

    That reasoning was carried over from `cli.py`'s handling of `--out`, and the
    comment notes it "was not carried through here" -- so the arm existed
    because someone reasoned about it, and then nothing exercised it. This is
    the difference between a recovery path and a recovery hypothesis.
    """
    real_write = Path.write_text

    def _refuse_transcripts(self, *args, **kwargs):
        if self.suffix == ".json" and self.parent == tmp_path:
            raise OSError(28, "No space left on device")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _refuse_transcripts)

    rows = run_probe_cells(
        slots=["ollama:unreachable-on-purpose"],
        system="s",
        user="u",
        expect="FINDINGS",
        out_dir=tmp_path,
        timeout=1,
        sampling={},
        call_model_fn=lambda *_a, **_k: {"status": ERROR, "error": "no endpoint"},
    )

    assert len(rows) == 1, "the run was lost because a transcript could not be written"
    assert "transcript_error" in rows[0], (
        "the row survived but does not record that its transcript is missing, so "
        "`summary.json` would describe a capture whose files are not there"
    )
    assert "No space left" in rows[0]["transcript_error"]


def test_an_http_error_body_is_truncated_and_reported_as_a_row():
    """A 401 from a vendor is a row, not an exception.

    `docs/roadmap/2026-09-06-review.md` flags this branch as the one that can
    carry a vendor's error body -- which may echo an `Authorization` header --
    into `detail`. It had never executed, so neither the truncation nor the
    reporting had ever been observed.
    """
    import urllib.error

    def _unauthorised(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="http://localhost:11434/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"x" * 5000),
        )

    row = call_model(
        "ollama:qwen2.5:14b", "sys", "user", timeout=1, post_fn=_unauthorised
    )

    assert row["status"] == ERROR
    assert row["error"] == "HTTP 401"
    assert len(row["detail"]) <= HTTP_ERROR_DETAIL_CHARS, (
        "a vendor error body reached `detail` untruncated; the whole body may "
        "echo the request, and this row is written into a tracked transcript"
    )


def test_a_response_with_no_choices_is_an_error_row_not_a_crash():
    """`{"choices": []}` is the realistic malformed vendor response.

    A provider that returns 200 with an empty `choices` list -- rate limited,
    content filtered, or just wrong -- must produce an ERROR row carrying the
    raw body for a human, not an `IndexError` that ends the sweep with the
    other slots unrun.
    """
    row = call_model(
        "ollama:qwen2.5:14b", "sys", "user", timeout=1,
        post_fn=lambda *_a, **_k: {"choices": []},
    )

    assert row["status"] == ERROR
    assert "choices" in row["error"]
    assert row["raw"] == {"choices": []}, "the body was not kept for diagnosis"
