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
