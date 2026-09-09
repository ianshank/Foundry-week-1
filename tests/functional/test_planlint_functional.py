"""Functional tests for planlint execution, argument parsing, and verdict derivation.

Verifies that the planlint functional wrapper adheres to the authority contract:
- Exit code dictates verdict (0 -> PASS, 1 -> FINDINGS, 2+ -> BLOCKED).
- Findings JSON payload is preserved as evidence.
- Non-zero unmapped exit codes collapse to BLOCKED.
- Redaction and guardrails apply to all arguments.
"""

from __future__ import annotations

import json
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
def make_planlint(tmp_path: Path, make_stub):
    """A planlint stand-in plus the config that points at it.

    Delegates the launcher to `tests/conftest.py::make_stub`, the canonical
    cross-platform executable factory, rather than building its own. This
    fixture used to build one, and it was the last place in the repository where
    **both halves of D-02 were still live**:

    * D-02b -- its `.bat` did not set `PYTHONUTF8=1`.
    * D-02a -- it wrote a **caller-supplied** payload with `sys.stdout.write`,
      i.e. through the console code page.

    Measured on a cp1252 console, with a CJK payload:

        WITHOUT PYTHONUTF8   returncode 1, stdout b'',
                             UnicodeEncodeError: 'charmap' codec can't encode
        WITH PYTHONUTF8=1    returncode 0, stdout b'\\xe6\\x97\\xa5...'

    Latent only because every payload passed here today is ASCII -- and the
    failure would not have looked like an encoding bug: the child exits 1, which
    `verdict_for_exit_code` maps to FINDINGS, so a test expecting PASS fails as
    a wrong-verdict mystery. The D-02 regression guards could not see it because
    they drive `make_stub`, which was never the factory at fault.
    """
    target_file = tmp_path / "spec.md"
    target_file.write_text("# OpenSpec Spec\n", encoding="utf-8")

    def _create(exit_code: int = 0, stdout: str = "", stderr: str = "") -> tuple[PlanlintConfig, Path]:
        exec_path = make_stub(
            "import sys\n"
            f"sys.stdout.buffer.write({stdout.encode('utf-8')!r})\n"
            f"sys.stderr.buffer.write({stderr.encode('utf-8')!r})\n"
            f"sys.exit({exit_code!r})\n",
            name=f"planlint_{exit_code}",
        )

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


def test_functional_a_non_ascii_payload_survives_the_stub(make_planlint):
    """The defect this fixture carried, now impossible to reintroduce silently.

    `make_planlint` took a caller-supplied `stdout` and wrote it in text mode
    under a `.bat` with no `PYTHONUTF8=1`. On a cp1252 console the child died
    with `UnicodeEncodeError` and exited 1 -- so `verdict_for_exit_code` mapped
    it to FINDINGS and the symptom was a wrong verdict, not an encoding error.

    Every payload passed here was ASCII, so it never fired.

    Measured, because it is not what it looks like: the two halves of D-02 are
    individually *sufficient* and jointly *necessary*. Reverting either one
    alone leaves this test green -- `PYTHONUTF8=1` rescues a text write, and a
    `sys.stdout.buffer` write does not care about the code page. Only reverting
    both reproduces the failure, and both is exactly what the original factory
    had. That is also why the source guard in
    `tests/regression/test_regression_suite.py` enforces each half
    unconditionally rather than reasoning about whether a given site is safe:
    per-site reasoning is what let this survive in four places.
    """
    payload = {"findings": [{"rule": "SPEC001", "message": "日本語" * 5}]}
    config, target_file = make_planlint(exit_code=1, stdout=json.dumps(payload, ensure_ascii=False))

    res = run_verb("validate", target=str(target_file), config=config)

    assert res["verdict"] == FINDINGS, (
        f"expected FINDINGS from exit 1, got {res['verdict']} / "
        f"{res.get('blocked_reason')} -- a stub that dies encoding its payload "
        "exits 1 too, which is why this failure looks like a verdict bug"
    )
    assert res["exit_code"] == 1
    assert res["findings"] == payload

