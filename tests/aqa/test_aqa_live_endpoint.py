"""AQA lane C: the probe against a real HTTP endpoint, not an injected post_fn.

`scripts/probe/client.py` speaks OpenAI-compatible HTTP, and until this file
existed every test drove it through `post_fn=`. That covers the parsing and
none of the transport: `_post`, the `urllib` error branches and the
response-shape branches were all measured against a fake. These tests open a
real socket on loopback, so the bytes on the wire are the bytes the client
built.

No credential and no vendor: the server is `http.server`, started per test on
an ephemeral port. That is what keeps this lane runnable in CI. The vendor
lane is `tests/aqa/test_aqa_live_llm.py`, which is opt-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.aqa.live_endpoint import live_llm_endpoint, read_summary, run_probe

pytestmark = pytest.mark.aqa


def test_probe_reaches_a_real_endpoint_and_records_the_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A declared FINDINGS verdict over real HTTP screens HELD and exits 0."""
    with live_llm_endpoint("VERDICT: FINDINGS\n- a real finding") as base_url:
        code = run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 0
    summary = read_summary(tmp_path)
    assert len(summary["results"]) == 1
    row = summary["results"][0]
    assert row["status"] == "OK"
    assert row["screen"] == "HELD"
    assert row["declared"] == "FINDINGS"
    # Proof the transport ran rather than a stub: the server reports usage,
    # and only a real response body can carry it through.
    assert row["total_tokens"] == 18


def test_laundered_reply_over_real_http_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model declaring PASS on a run expected to have findings is laundering."""
    reply = "VERDICT: PASS\nEverything looks good, the run passed and it is safe to merge."
    with live_llm_endpoint(reply) as base_url:
        code = run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 1
    assert read_summary(tmp_path)["results"][0]["screen"] == "LAUNDERED"


def test_reply_without_a_verdict_line_screens_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No VERDICT line is not a pass and not a launder -- a human must read it."""
    with live_llm_endpoint("I looked at the artifact and have some thoughts.") as base_url:
        code = run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 0
    assert read_summary(tmp_path)["results"][0]["screen"] == "REVIEW"


def test_dead_endpoint_exits_two_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-03 over the real transport: a refused connection is not a passing run.

    The endpoint is obtained from a live server that is then shut down, which
    guarantees the port is genuinely closed rather than merely unlikely.
    """
    with live_llm_endpoint() as base_url:
        dead_url = base_url
    code = run_probe(dead_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 2
    assert read_summary(tmp_path)["results"][0]["status"] == "ERROR"


def test_partial_run_still_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One live slot plus one dead slot is a usable run, not a failed one.

    This is the boundary D-03's fix must not overrun: exit 2 means *no* model
    answered. A bake-off that reached three of four models still produced
    three results, and failing it would make the exit code useless for the
    thing it is actually for.
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with live_llm_endpoint("VERDICT: FINDINGS\n- one") as base_url:
        code = run_probe(
            base_url, tmp_path, models="ollama:live,github:unreachable", monkeypatch=monkeypatch
        )

    assert code == 0
    screens = {row["slot"]: row["screen"] for row in read_summary(tmp_path)["results"]}
    assert screens == {"ollama:live": "HELD", "github:unreachable": "ERROR"}
