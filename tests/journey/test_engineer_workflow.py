"""User Journey Test: Simulates an AI/SWE engineer's full evaluation lifecycle.

User Journey stages:
1. Engineer authors an OpenSpec spec markdown file.
2. Engineer triggers `lint_openspec` through MCP tool contract.
3. Engineer executes probe screening against model outputs.
4. Engineer inspects and validates tri-state scoring (`score_run`).
5. Engineer validates evidence hygiene to prevent credential leaks.
6. Engineer promotes clean trace into official repository evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from scripts.probe.screen import HELD, screen
from scripts.promote_trace import promote
from scripts.scan_evidence import scan_file

from foundry_spike_mcp.config import EvalConfig, PlanlintConfig
from foundry_spike_mcp.planlint import lint_openspec
from foundry_spike_mcp.scoring import score_run
from foundry_spike_mcp.verdicts import PASS


def test_complete_engineer_workflow_journey(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup working directory structure
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    specs_dir = workspace / "openspec"
    specs_dir.mkdir()
    sink_dir = workspace / "sink"
    sink_dir.mkdir()
    traces_dir = workspace / "traces"
    traces_dir.mkdir()

    # --- Stage 1: Engineer writes an OpenSpec proposal ---
    spec_file = specs_dir / "project.md"
    spec_file.write_text(
        """# Project Specification: Agent Guardrails
## Overview
Defines safety barriers for tool execution.
## Acceptance Criteria
- Tri-state verdicts: PASS, FINDINGS, BLOCKED
- No credential leakage in evidence exports
""",
        encoding="utf-8",
    )

    # --- Stage 2: Engineer lints spec with planlint wrapper ---
    # Configure mock planlint binary
    bin_dir = workspace / "bin"
    bin_dir.mkdir()
    py_script = bin_dir / "planlint_mock.py"
    py_script.write_text('import json; print(json.dumps({"findings": []}))\n', encoding="utf-8")
    if sys.platform == "win32":
        planlint_bin = bin_dir / "mock_planlint.bat"
        planlint_bin.write_text(f'@"{sys.executable}" "{py_script}" %*')
    else:
        import stat
        planlint_bin = bin_dir / "mock_planlint"
        planlint_bin.write_text(f"#!{sys.executable}\nimport json; print(json.dumps({{'findings': []}}))\n", encoding="utf-8")
        planlint_bin.chmod(planlint_bin.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    planlint_cfg = PlanlintConfig(
        binary=str(planlint_bin),
        allowed_roots=(workspace,),
        target=str(spec_file),
    )
    lint_result = lint_openspec(target=str(spec_file), config=planlint_cfg)
    assert lint_result["verdict"] == PASS
    assert lint_result["exit_code"] == 0

    # --- Stage 3: Engineer runs probe evaluation against candidate prompt ---
    # Model response correctly reports BLOCKED and does not launder as PASS
    model_output = "VERDICT: BLOCKED\nThe run failed to validate the required openspec schema."
    screen_result = screen(model_output, expected="BLOCKED")
    assert screen_result["screen"] == HELD
    assert screen_result["declared"] == "BLOCKED"

    # --- Stage 4: Engineer generates run artifact & runs score_run ---
    run_id = "eval-journey-001"
    run_artifact = sink_dir / f"{run_id}.json"
    run_artifact.write_text(
        json.dumps({
            "run_id": run_id,
            "results": [
                {"scorer": "refusal_probe_01", "passed": True},
                {"scorer": "planlint_validity", "passed": True},
                {"scorer": "optional_check", "passed": None},
            ],
        }),
        encoding="utf-8",
    )

    eval_cfg = EvalConfig(allowed_roots=(workspace,), sink_dir=sink_dir)
    scoring_result = score_run(run_id, config=eval_cfg)
    assert scoring_result["verdict"] == PASS
    assert scoring_result["pass_rate"] == 1.0
    assert scoring_result["counts"]["true"] == 2
    assert scoring_result["counts"]["null"] == 1

    # --- Stage 5: Engineer scans evidence before promotion ---
    run_dir = workspace / "raw_capture"
    run_dir.mkdir()
    evidence_file = run_dir / "evaluation_trace.json"
    evidence_file.write_text(
        json.dumps({
            "run_id": run_id,
            "log": "All tests passed with zero errors.",
            "notes": "Safe trace with no credentials",
        }),
        encoding="utf-8",
    )

    secret_hits = scan_file(evidence_file)
    assert len(secret_hits) == 0, f"Found unexpected secret hits: {secret_hits}"

    # --- Stage 6: Engineer promotes clean trace into official evidence repository ---
    promoted_path = promote(run_dir, name="journey-promoted-001", destination_root=traces_dir)
    assert promoted_path.exists()
    assert (promoted_path / "evaluation_trace.json").exists()

    # --- Stage 7: Final validation check ---
    assert (traces_dir / "journey-promoted-001" / "evaluation_trace.json").read_text(
        encoding="utf-8"
    ) == evidence_file.read_text(encoding="utf-8")
