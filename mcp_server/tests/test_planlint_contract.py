"""The contract tests. If one of these fails, stop condition 2 is in play.

Read these as the specification: `lint_openspec` maps planlint's exit code to
a three-way verdict, never raises, and never lets a payload problem change a
verdict.
"""

from __future__ import annotations

import json

import pytest

from foundry_spike_mcp.planlint import lint_openspec
from foundry_spike_mcp.verdicts import (
    BLOCKED,
    BLOCKED_GUARD_REJECTED,
    BLOCKED_PRECONDITION,
    BLOCKED_TIMEOUT,
    BLOCKED_TOOL_NOT_FOUND,
    BLOCKED_UNEXPECTED_EXIT,
    FINDINGS,
    PASS,
    VERDICTS,
)

FINDINGS_JSON = json.dumps(
    {"findings": [{"rule": "SPEC001", "severity": "ERROR", "message": "missing acceptance criteria"}]}
)

# What planlint prints when it cannot find a spec tree. Not JSON -- which is
# the whole point: the runbook's sample code calls json.loads on this.
USAGE_TEXT = "error: no openspec/ directory under target; nothing to validate\n"


def test_exit_zero_is_pass(fake_planlint, configured):
    configured(fake_planlint(exit_code=0, stdout=json.dumps({"findings": []})))
    result = lint_openspec()
    assert result["verdict"] == PASS
    assert result["exit_code"] == 0
    assert result["blocked_reason"] is None
    assert result["findings"] == {"findings": []}


def test_exit_one_is_findings(fake_planlint, configured):
    configured(fake_planlint(exit_code=1, stdout=FINDINGS_JSON))
    result = lint_openspec()
    assert result["verdict"] == FINDINGS
    assert result["exit_code"] == 1
    assert result["findings"]["findings"][0]["rule"] == "SPEC001"


def test_exit_two_is_blocked_not_pass_and_does_not_raise(fake_planlint, configured):
    """The deliberate-BLOCKED case from the runbook's step 3 'done when'.

    stdout is a usage message, so the sample code's unguarded `json.loads`
    would raise here and the model would never see a verdict at all.
    """
    configured(fake_planlint(exit_code=2, stdout=USAGE_TEXT))
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["exit_code"] == 2
    assert result["blocked_reason"] == BLOCKED_PRECONDITION
    assert result["findings"] is None
    assert "findings_parse_error" in result
    assert "no openspec/" in result["stdout_excerpt"]


def test_exit_two_with_empty_stdout_is_still_blocked(fake_planlint, configured):
    configured(fake_planlint(exit_code=2, stdout="", stderr=USAGE_TEXT))
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["exit_code"] == 2
    assert result["blocked_reason"] == BLOCKED_PRECONDITION


def test_unmapped_exit_code_collapses_to_blocked_never_pass(fake_planlint, configured):
    """A crash is 'could not form an opinion', and the raw code survives."""
    configured(fake_planlint(exit_code=139, stdout=""))
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_UNEXPECTED_EXIT
    assert result["exit_code"] == 139


def test_timeout_is_blocked_never_findings(fake_planlint, configured):
    """The refusal the runbook asked for; `subprocess.run(timeout=)` raises."""
    configured(fake_planlint(exit_code=1, stdout=FINDINGS_JSON, sleep=3.0), PLANLINT_TIMEOUT="1")
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_TIMEOUT
    assert result["verdict"] != FINDINGS
    assert result["exit_code"] is None


def test_missing_binary_is_blocked(configured, spec_repo, monkeypatch):
    monkeypatch.setenv("PLANLINT_BIN", "/nonexistent/planlint-does-not-exist")
    monkeypatch.setenv("PLANLINT_TARGET", str(spec_repo))
    monkeypatch.setenv("PLANLINT_ALLOWED_ROOTS", str(spec_repo))
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_TOOL_NOT_FOUND


def test_unset_target_is_blocked_not_a_keyerror():
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [(0, PASS), (1, FINDINGS)],
)
def test_unparsable_payload_never_changes_the_verdict(fake_planlint, configured, exit_code, expected):
    """The exit code is the verdict; the payload is evidence."""
    configured(fake_planlint(exit_code=exit_code, stdout="<<< not json at all >>>"))
    result = lint_openspec()
    assert result["verdict"] == expected
    assert result["exit_code"] == exit_code
    assert result["findings"] is None
    assert "findings_parse_error" in result


def test_verdict_is_always_one_of_three(fake_planlint, configured):
    """No fourth state reaches the model -- the agent has no rule for one."""
    for code in (0, 1, 2, 3, 42, 127, 255):
        configured(fake_planlint(exit_code=code, stdout=""))
        assert lint_openspec()["verdict"] in VERDICTS


def test_secrets_are_redacted_from_stderr(fake_planlint, configured):
    leak = "fatal: auth failed for token ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"
    configured(fake_planlint(exit_code=2, stderr=leak))
    result = lint_openspec()
    assert "ghp_abcdefghijklmnopqrstuvwxyz" not in result["stderr"]
    assert "[REDACTED:github-token]" in result["stderr"]


def test_stderr_is_truncated(fake_planlint, configured):
    configured(fake_planlint(exit_code=2, stderr="x" * 50_000))
    result = lint_openspec()
    assert len(result["stderr"]) < 3000
    assert "truncated" in result["stderr"]


def test_explicit_target_outside_allow_list_is_blocked(fake_planlint, configured, tmp_path):
    configured(fake_planlint(exit_code=0, stdout="{}"))
    result = lint_openspec(target=str(tmp_path / "somewhere-else"))
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


def test_command_is_recorded_for_the_trace(fake_planlint, configured):
    """Step 2's verifier prompt pastes 'one finding plus the invocation', so
    the invocation has to be in the result."""
    configured(fake_planlint(exit_code=1, stdout=FINDINGS_JSON))
    result = lint_openspec()
    assert "validate" in result["command"]
    assert "--fail-on" in result["command"]
    assert "--force" not in result["command"]


def test_bad_fail_on_is_rejected_before_the_process_runs(fake_planlint, configured):
    configured(fake_planlint(exit_code=0, stdout="{}"))
    result = lint_openspec(fail_on="; rm -rf /")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


def test_json_flag_can_be_disabled_without_breaking_the_verdict(fake_planlint, configured):
    """planlint's exact JSON spelling is confirmed in session 1. Until then,
    running without the flag must still produce a correct verdict."""
    configured(fake_planlint(exit_code=1, stdout="2 findings\n"), PLANLINT_JSON_FLAG="")
    result = lint_openspec()
    assert result["verdict"] == FINDINGS
    assert "--json" not in result["command"]


# --------------------------------------------------------------------------
# Regression: finding #5. A contract whose premise is a predictable envelope
# cannot hand callers a different key set per code path.
# --------------------------------------------------------------------------


def test_result_shape_is_identical_across_every_path(fake_planlint, configured, monkeypatch):
    shapes = []
    shapes.append(set(lint_openspec().keys()))  # unconfigured: no target
    configured(fake_planlint(exit_code=0, stdout="{}"))
    shapes.append(set(lint_openspec().keys()))  # success
    configured(fake_planlint(exit_code=2, stdout="usage: ..."))
    shapes.append(set(lint_openspec().keys()))  # blocked by exit code
    monkeypatch.setenv("PLANLINT_BIN", "/nonexistent/planlint")
    shapes.append(set(lint_openspec().keys()))  # blocked before exec
    assert len(set(map(frozenset, shapes))) == 1, shapes


def test_malformed_timeout_is_blocked_not_silently_defaulted(fake_planlint, configured):
    """A misconfigured run could not form an opinion. Substituting the default
    would hide an operator mistake behind a plausible-looking result."""
    configured(fake_planlint(exit_code=0, stdout="{}"), PLANLINT_TIMEOUT="not-a-number")
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == "configuration_error"


def test_deeply_nested_stdout_does_not_raise(fake_planlint, configured):
    """RecursionError from json.loads is not a JSONDecodeError, and the verdict
    must survive an unparsable payload regardless."""
    configured(fake_planlint(exit_code=1, stdout="[" * 20_000 + "]" * 20_000))
    result = lint_openspec()
    assert result["verdict"] == FINDINGS
    assert result["findings"] is None
    assert "RecursionError" in result["findings_parse_error"]
