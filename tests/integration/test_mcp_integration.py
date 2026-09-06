"""Layer 2: Integration tests connecting MCP tools, file system, and probe pipelines.

sys.path is managed by pytest.ini pythonpath and tests/conftest.py.
Fixtures make_stub and spec_repo are provided by tests/conftest.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from foundry_spike_mcp.config import EvalConfig, PlanlintConfig
from foundry_spike_mcp.planlint import lint_openspec
from foundry_spike_mcp.scoring import score_run
from foundry_spike_mcp.verdicts import FINDINGS, PASS

try:
    from scripts import verifier_probe
    from scripts.promote_trace import promote
    from scripts.scan_evidence import scan_file
except ImportError:
    import verifier_probe  # type: ignore[no-redef]
    from promote_trace import promote  # type: ignore[no-redef]
    from scan_evidence import scan_file  # type: ignore[no-redef]


def test_integration_planlint_and_scoring_pipeline(
    tmp_path: Path,
    make_stub,  # type: ignore[no-untyped-def]
) -> None:
    """Simulate complete pipeline: lint proposals, produce runs, and score them."""
    repo_tree = tmp_path / "repo"
    openspec_dir = repo_tree / "openspec" / "changes" / "feature-1"
    openspec_dir.mkdir(parents=True)
    proposal = openspec_dir / "proposal.md"
    proposal.write_text("# Feature Proposal\n\nValid description.", encoding="utf-8")

    # make_stub is the canonical cross-platform factory from tests/conftest.py.
    # It writes a .bat launcher on Windows and a shebang script on POSIX.
    stub = make_stub(
        "import sys\n"
        'sys.stdout.buffer.write(b\'{"findings": []}\')\n'
        "sys.stdout.buffer.flush()\n"
        "sys.exit(0)\n",
    )
    planlint_cfg = PlanlintConfig(
        binary=str(stub),
        target=str(proposal),
        allowed_roots=(repo_tree,),
    )
    result = lint_openspec(target=str(proposal), config=planlint_cfg)
    assert result["verdict"] == PASS

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
    hits = scan_file(clean_capture)
    assert hits == []

    dest_root = tmp_path / "traces"
    promoted_path = promote(raw_dir, name="promoted-session-02", destination_root=dest_root)
    assert promoted_path.is_dir()
    assert (promoted_path / "clean_trace.json").is_file()


def test_integration_verifier_probe_client_and_screen(monkeypatch: Any) -> None:
    """Test integrated probe client calling model and screening the result."""
    fake_response = {
        "choices": [
            {"message": {"content": "Evaluation complete.\nVERDICT: FINDINGS\nFound 2 issues."}}
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
