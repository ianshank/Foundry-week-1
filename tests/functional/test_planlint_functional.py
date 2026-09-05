"""Functional tests for planlint execution, argument parsing, and verdict derivation.

Verifies that the planlint functional wrapper adheres to the authority contract:
- Exit code dictates verdict (0 -> PASS, 1 -> FINDINGS, 2+ -> BLOCKED).
- Findings JSON payload is preserved as evidence.
- Non-zero unmapped exit codes collapse to BLOCKED.
- Redaction and guardrails apply to all arguments.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from foundry_spike_mcp.config import PlanlintConfig
from foundry_spike_mcp.planlint import lint_openspec, run_verb
from foundry_spike_mcp.verdicts import (
    BLOCKED,
    BLOCKED_GUARD_REJECTED,
    BLOCKED_PRECONDITION,
    BLOCKED_TOOL_NOT_FOUND,
    BLOCKED_UNEXPECTED_EXIT,
    FINDINGS,
    PASS,
)


@pytest.fixture
def make_planlint(tmp_path: Path):
    """Builds an executable wrapper (batch file on Windows) representing planlint."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target_file = tmp_path / "spec.md"
    target_file.write_text("# OpenSpec Spec\n", encoding="utf-8")

    def _create(exit_code: int = 0, stdout: str = "", stderr: str = "") -> tuple[PlanlintConfig, Path]:
        name = f"planlint_{exit_code}"
        py_script = bin_dir / f"{name}.py"
        py_script.write_text(
            "import sys\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"sys.exit({exit_code!r})\n",
            encoding="utf-8",
        )
        if sys.platform == "win32":
            exec_path = bin_dir / f"{name}.bat"
            exec_path.write_text(f'@"{sys.executable}" "{py_script}" %*')
        else:
            exec_path = bin_dir / name
            exec_path.write_text(f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(), encoding="utf-8")
            exec_path.chmod(exec_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        config = PlanlintConfig(
            binary=str(exec_path),
            allowed_roots=(tmp_path,),
            target=str(target_file),
            timeout_seconds=5,
            json_flag="--format json",
        )
        return config, target_file

    return _create


def test_functional_run_verb_disallowed_verb(make_planlint):
    """Verify that arbitrary or destructive verbs are refused before execution."""
    config, target_file = make_planlint(exit_code=0)
    res = run_verb("destroy", target=str(target_file), config=config)
    assert res["verdict"] == BLOCKED
    assert res["blocked_reason"] == BLOCKED_GUARD_REJECTED
    assert "verb_not_allowed" in res["blocked_detail"]


def test_functional_exit_0_yields_pass(make_planlint):
    """Exit code 0 is authoritative PASS."""
    config, target_file = make_planlint(exit_code=0, stdout=json.dumps({"findings": []}))

    res = run_verb(
        verb="validate",
        target=str(target_file),
        config=config,
    )
    assert res["verdict"] == PASS
    assert res["exit_code"] == 0
    assert res["findings"] == {"findings": []}
    assert res["contract"]["authority"] == "exit_code"


def test_functional_exit_1_yields_findings_with_payload(make_planlint):
    """Exit code 1 is authoritative FINDINGS with parsed findings evidence."""
    mock_findings = {
        "findings": [
            {"rule": "SPEC001", "severity": "ERROR", "message": "Missing spec section"}
        ]
    }
    config, target_file = make_planlint(exit_code=1, stdout=json.dumps(mock_findings))

    res = run_verb(
        verb="validate",
        target=str(target_file),
        config=config,
    )
    assert res["verdict"] == FINDINGS
    assert res["exit_code"] == 1
    assert res["findings"] == mock_findings
    assert res["findings_parse_error"] is None


def test_functional_exit_1_malformed_json_still_yields_findings(make_planlint):
    """Malformed stdout evidence never overrides exit code 1 to BLOCKED."""
    config, target_file = make_planlint(exit_code=1, stdout="NOT A VALID JSON STRING")

    res = run_verb(
        verb="validate",
        target=str(target_file),
        config=config,
    )
    assert res["verdict"] == FINDINGS
    assert res["exit_code"] == 1
    assert res["findings"] is None
    assert "JSONDecodeError" in str(res["findings_parse_error"])


def test_functional_exit_2_yields_precondition_blocked(make_planlint):
    """Exit code 2 is authoritative BLOCKED (precondition error)."""
    config, target_file = make_planlint(exit_code=2, stderr="Precondition failed: config missing")

    res = run_verb(
        verb="validate",
        target=str(target_file),
        config=config,
    )
    assert res["verdict"] == BLOCKED
    assert res["exit_code"] == 2
    assert res["blocked_reason"] == BLOCKED_PRECONDITION


def test_functional_unmapped_exit_yields_unexpected_exit_blocked(make_planlint):
    """Unmapped exit codes (e.g. 137, 42) must collapse to BLOCKED."""
    config, target_file = make_planlint(exit_code=42, stderr="Aborted")

    res = run_verb(
        verb="validate",
        target=str(target_file),
        config=config,
    )
    assert res["verdict"] == BLOCKED
    assert res["exit_code"] == 42
    assert res["blocked_reason"] == BLOCKED_UNEXPECTED_EXIT


def test_functional_missing_binary(tmp_path: Path):
    """Non-existent binary on PATH maps cleanly to BLOCKED."""
    target_file = tmp_path / "spec.md"
    target_file.write_text("# Spec\n", encoding="utf-8")
    config = PlanlintConfig(
        binary="non_existent_binary_xyz123",
        allowed_roots=(tmp_path,),
        target=str(target_file),
    )
    res = run_verb("validate", target=str(target_file), config=config)
    assert res["verdict"] == BLOCKED
    assert res["blocked_reason"] == BLOCKED_TOOL_NOT_FOUND


def test_functional_lint_openspec_fail_on_forwarding(make_planlint):
    """Verify lint_openspec handles fail_on option and passes to validate verb."""
    config, target_file = make_planlint(exit_code=0, stdout=json.dumps({"findings": []}))

    res = lint_openspec(
        target=str(target_file),
        fail_on="WARNING",
        config=config,
    )
    assert res["verdict"] == PASS
    assert res["verb"] == "validate"
