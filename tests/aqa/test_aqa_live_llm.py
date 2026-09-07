"""AQA lane D: the probe against a real vendor LLM. Opt-in, never in CI.

Lane C (`test_aqa_live_endpoint.py`) proves the transport works by serving
loopback HTTP. It cannot prove that a real vendor's response shape, latency
and content still fit the screen -- only a vendor can, and no vendor
credential belongs in this repository's CI.

So this lane is opt-in twice over: `PROBE_LIVE=1` must be set *and* the slot's
endpoint or credential must resolve. Both conditions skip with a stated
reason rather than passing, because an acceptance test that goes green
without contacting anything is the same defect as D-03.

    PROBE_LIVE=1 PROBE_MODELS=ollama:llama3.1 make test-live
    PROBE_LIVE=1 PROBE_MODELS=github:gpt-4o GITHUB_TOKEN=... make test-live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from tests.aqa.live_endpoint import read_summary

from probe.client import call_model
from probe.config import PROBES, PROVIDERS

pytestmark = [pytest.mark.aqa, pytest.mark.live_llm]


def _slots() -> list[str]:
    return [slot.strip() for slot in os.environ.get("PROBE_MODELS", "").split(",") if slot.strip()]


def _skip_unless_configured() -> list[str]:
    """Return the runnable slots, or skip with the reason there are none."""
    if os.environ.get("PROBE_LIVE") != "1":
        pytest.skip("live vendor lane is opt-in: set PROBE_LIVE=1 to run it")
    slots = _slots()
    if not slots:
        pytest.skip("PROBE_LIVE=1 but PROBE_MODELS is empty; nothing to contact")
    for slot in slots:
        provider = slot.partition(":")[0].strip().lower()
        spec = PROVIDERS.get(provider)
        if spec is None:
            pytest.skip(f"slot {slot!r} names an unknown provider {provider!r}")
        if not os.environ.get(spec.endpoint_env, spec.endpoint_default):
            pytest.skip(f"{spec.endpoint_env} is unset for slot {slot!r}")
        if spec.credential_required and not os.environ.get(spec.credential_env, "").strip():
            pytest.skip(f"{spec.credential_env} is unset for slot {slot!r} ({spec.credential_hint})")
    return slots


def test_live_model_answers_over_the_real_transport() -> None:
    """Every configured slot returns usable content from a real vendor.

    Asserting on `status` and not on the verdict is deliberate: which verdict
    a given model declares is the bake-off's *question*, and a test that
    demanded a particular answer would be scoring the model rather than
    checking the harness.
    """
    slots = _skip_unless_configured()
    system = (PROBES / "system-prompt.md").read_text(encoding="utf-8")
    user = (PROBES / "02-verifier.md").read_text(encoding="utf-8")

    for slot in slots:
        result = call_model(slot, system, user, timeout=120)
        # Deliberately omits result.get("detail"): a vendor's raw HTTP error
        # body can run to 600 characters and, if the vendor ever echoes a
        # request header back on failure, could carry the bearer token into
        # this assertion's message and from there into captured test output.
        # `error` is a fixed, code-shaped string (e.g. "HTTP 401"); it never
        # contains request content.
        assert result["status"] == "OK", f"{slot} did not answer: {result.get('error', 'unknown error')}"
        assert result["text"].strip(), f"{slot} returned empty content"
        assert result["latency_ms"] > 0


def test_live_probe_run_produces_a_promotable_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live run writes a summary that the D-04 promotion gate accepts.

    This is the end-to-end claim the week's evidence chain rests on: a real
    model was contacted, the capture records it, and promotion will take it.
    """
    from probe.cli import main as probe_main
    from promote_trace import promote

    slots = _skip_unless_configured()
    code = probe_main([
        "--models", ",".join(slots),
        "--expect", "FINDINGS",
        "--timeout", "120",
        "--out", str(tmp_path / "raw"),
    ])
    assert code in (0, 1), f"live probe exited {code}; 2 means no model answered"

    summary = read_summary(tmp_path / "raw")
    assert any(row["status"] == "OK" for row in summary["results"])

    capture = next((tmp_path / "raw").glob("*/"))
    promoted = promote(capture, destination_root=tmp_path / "traces")
    assert (promoted / "summary.json").is_file()
