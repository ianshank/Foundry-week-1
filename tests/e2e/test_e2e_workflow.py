"""End-to-End (E2E) tests executing repository CLI tools via real subprocesses.

Validates:
- `scripts/scan_evidence.py` against repository evidence trees.
- `scripts/promote_trace.py` promoting trace artifacts across directories.
- `scripts/verifier_probe.py` argument parsing and screening CLI.
- `foundry-spike-mcp` CLI entrypoint execution.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_e2e_scan_evidence_cli_clean_execution():
    """Verify scan_evidence.py CLI executes cleanly on repository targets."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scan_evidence.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "0 hit(s)" in result.stdout or "scanned" in result.stdout


def test_e2e_promote_trace_cli(tmp_path: Path):
    """Verify promote_trace.py CLI copies and structures run artifacts end-to-end."""
    src_dir = tmp_path / "source_run"
    src_dir.mkdir()
    dst_dir = tmp_path / "promoted_traces"
    dst_dir.mkdir()

    trace_data = {
        "run_id": "run-e2e-100",
        "timestamp": "2026-09-05T12:00:00Z",
        "clean_text": "no credentials here",
    }
    trace_file = src_dir / "trace.json"
    trace_file.write_text(json.dumps(trace_data), encoding="utf-8")

    # Run promote_trace with positional source, --as and --dest-root argument
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "promote_trace.py"),
            str(src_dir),
            "--as",
            "run-e2e-100",
            "--dest-root",
            str(dst_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""},
    )
    assert result.returncode == 0
    assert (dst_dir / "run-e2e-100" / "trace.json").exists()


def test_e2e_verifier_probe_cli_help():
    """Verify verifier_probe.py CLI entrypoint operates seamlessly."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verifier_probe.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "--model" in result.stdout


def test_e2e_mcp_server_module_help():
    """Verify the foundry_spike_mcp module entrypoint help invocation."""
    result = subprocess.run(
        [sys.executable, "-m", "foundry_spike_mcp", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        env={"PYTHONPATH": f"{REPO_ROOT / 'mcp_server' / 'src'};{REPO_ROOT}"},
    )
    assert result.returncode == 0
    assert "foundry-spike-mcp" in result.stdout.lower() or "usage:" in result.stdout.lower()
