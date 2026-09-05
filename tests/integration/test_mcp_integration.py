"""Layer 2: Integration tests connecting MCP tools, file system, and probe pipelines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import verifier_probe
from foundry_spike_mcp.planlint import lint_openspec
from foundry_spike_mcp.scoring import score_run
from foundry_spike_mcp.verdicts import BLOCKED, FINDINGS, PASS
from promote_trace import promote
from scan_evidence import scan_file


def test_integration_planlint_and_scoring_pipeline(tmp_path: Path) -> None:
    """Simulate complete pipeline: lint proposals, produce runs, and score them."""
    # 1. Prepare an openspec repository tree
    repo_tree = tmp_path / "repo"
    openspec_dir = repo_tree / "openspec" / "changes" / "feature-1"
    openspec_dir.mkdir(parents=True)
    proposal = openspec_dir / "proposal.md"
    proposal.write_text("# Feature Proposal\n\nValid description.", encoding="utf-8")

    # 2. Run lint_openspec against this tree (target exists, openspec exists)
    result = lint_openspec(target=str(proposal))
    assert result["verdict"] in (PASS, FINDINGS, BLOCKED)

    # 3. Create a valid eval sink artifact and score it
    from foundry_spike_mcp.config import EvalConfig
    sink_file = repo_tree / "run-01.json"
    sink_file.write_text(
        json.dumps({
            "results": [
                {"scorer": "spec012", "passed": True},
                {"scorer": "syntax", "passed": True},
                {"scorer": "coverage", "passed": False},
            ]
        }),
        encoding="utf-8",
    )
    eval_cfg = EvalConfig(sink_dir=repo_tree, allowed_roots=(repo_tree,))
    score_envelope = score_run(run_id="run-01", artifact_path=str(sink_file), config=eval_cfg)
    assert score_envelope["verdict"] == FINDINGS
    assert score_envelope["counts"]["true"] == 2
    assert score_envelope["counts"]["false"] == 1
    assert pytest.approx(score_envelope["pass_rate"], 0.01) == 0.667


def test_integration_evidence_scan_and_promote_pipeline(tmp_path: Path) -> None:
    """Simulate end-to-end evidence capture, hygiene scan, and promotion."""
    raw_dir = tmp_path / "traces" / "raw" / "20260905T120000Z-02-verifier"
    raw_dir.mkdir(parents=True)
    clean_capture = raw_dir / "clean_trace.json"
    clean_capture.write_text(
        json.dumps({"slot": "ollama:qwen", "verdict": "FINDINGS"}),
        encoding="utf-8",
    )

    # Scan the file
    hits = scan_file(clean_capture)
    assert hits == []

    # Promote to tracked traces root
    dest_root = tmp_path / "traces"
    promoted_path = promote(raw_dir, name="promoted-session-02", destination_root=dest_root)
    assert promoted_path.is_dir()
    assert (promoted_path / "clean_trace.json").is_file()


def test_integration_verifier_probe_client_and_screen(monkeypatch: Any) -> None:
    """Test integrated probe client calling model and screening the result."""
    fake_response = {
        "choices": [
            {
                "message": {
                    "content": "Evaluation complete.\nVERDICT: FINDINGS\nFound 2 issues."
                }
            }
        ],
        "usage": {"total_tokens": 128},
    }

    def mock_post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
        return fake_response

    monkeypatch.setattr(verifier_probe, "_post", mock_post)
    row = verifier_probe.call_model(
        "ollama:qwen2.5:14b",
        system="System prompt",
        user="User prompt",
        timeout=10,
    )
    assert row["status"] == "OK"
    assert "VERDICT: FINDINGS" in row["text"]

    screen_res = verifier_probe.screen(row["text"], expected="FINDINGS")
    assert screen_res["screen"] == verifier_probe.HELD
    assert screen_res["basis"] == "declared_verdict_line"
