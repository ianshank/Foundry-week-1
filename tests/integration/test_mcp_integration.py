"""Layer 2: Integration tests connecting MCP tools, file system, and probe pipelines."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure repository root, scripts, and mcp_server/src are on sys.path for IDEs and standalone execution
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts", _REPO_ROOT / "mcp_server" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from foundry_spike_mcp.config import EvalConfig, PlanlintConfig  # noqa: E402
from foundry_spike_mcp.planlint import lint_openspec  # noqa: E402
from foundry_spike_mcp.scoring import score_run  # noqa: E402
from foundry_spike_mcp.verdicts import FINDINGS, PASS  # noqa: E402

try:
    from scripts import verifier_probe  # noqa: E402
    from scripts.promote_trace import promote  # noqa: E402
    from scripts.scan_evidence import scan_file  # noqa: E402
except ImportError:
    import verifier_probe  # type: ignore[no-redef]  # noqa: E402
    from promote_trace import promote  # type: ignore[no-redef]  # noqa: E402
    from scan_evidence import scan_file  # type: ignore[no-redef]  # noqa: E402




def test_integration_planlint_and_scoring_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate complete pipeline: lint proposals, produce runs, and score them."""
    # 1. Prepare an openspec repository tree
    repo_tree = tmp_path / "repo"
    openspec_dir = repo_tree / "openspec" / "changes" / "feature-1"
    openspec_dir.mkdir(parents=True)
    proposal = openspec_dir / "proposal.md"
    proposal.write_text("# Feature Proposal\n\nValid description.", encoding="utf-8")

    # 2. Run lint_openspec against a real stand-in binary.
    #
    # This step used to monkeypatch `foundry_spike_mcp.planlint.subprocess.run`.
    # That seam disappeared when `run_verb` moved to `Popen`, so a timeout could
    # reap the whole process group -- and the patch silently stopped
    # intercepting, leaving the test to execute the real interpreter and read
    # its exit 2 as a genuine BLOCKED.
    #
    # Repointed at a fake binary rather than at the new symbol, which is what
    # the rest of this suite does and what `mcp_server/tests/conftest.py`
    # argues for: the failure modes here are properties of real process
    # handling, and a patched `subprocess` tests the patch.
    # Create a cross-platform stub binary.
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    stub_py = stub_dir / "planlint.py"
    # Use sys.stdout.buffer for binary-safe output to avoid cp1252 on Windows.
    stub_py.write_text(
        "import sys\n"
        'sys.stdout.buffer.write(b\'{"findings": []}\')\n'
        "sys.stdout.buffer.flush()\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        stub = stub_dir / "planlint.bat"
        stub.write_text(f'@"{sys.executable}" "{stub_py}" %*')
    else:
        import stat

        stub = stub_dir / "planlint"
        stub.write_text(
            f"#!/usr/bin/env {sys.executable}\n" + stub_py.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    planlint_cfg = PlanlintConfig(
        binary=str(stub),
        target=str(proposal),
        allowed_roots=(repo_tree,),
    )
    result = lint_openspec(target=str(proposal), config=planlint_cfg)
    assert result["verdict"] == PASS

    # 3. Create a valid eval sink artifact and score it
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
