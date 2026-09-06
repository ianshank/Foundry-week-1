"""The contract tests. If one of these fails, stop condition 2 is in play.

Read these as the specification: `lint_openspec` maps planlint's exit code to
a three-way verdict, never raises, and never lets a payload problem change a
verdict.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from foundry_spike_mcp.config import load_planlint_config
from foundry_spike_mcp.planlint import detect_dialect, lint_openspec
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


# --------------------------------------------------------------------------
# A path the operating system cannot represent.
#
# `Path.resolve` raises rather than returning, and the argument is supplied by
# a model. Uncaught, the model gets a framework error with no verdict field --
# the one outcome this package exists to prevent.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_target",
    [
        pytest.param("{root}/spec\x00.md", id="nul-byte"),
        pytest.param("{root}/\x00", id="nul-only-segment"),
    ],
)
def test_a_path_the_os_cannot_represent_is_blocked_never_raised(
    fake_planlint, configured, bad_target
):
    root = configured(fake_planlint(exit_code=0, stdout="{}"))
    result = lint_openspec(target=bad_target.format(root=root))
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED
    assert "invalid_path" in result["blocked_detail"]
    # No process ran, so there is no exit code to report. BLOCKED with a null
    # exit code is the refusal shape, not a missing field.
    assert result["exit_code"] is None


def test_the_refusal_does_not_echo_the_malformed_path_back(fake_planlint, configured):
    """A NUL pasted into the result is a second problem on top of the first:
    the detail is serialised into JSON that a model and a trace both read."""
    root = configured(fake_planlint(exit_code=0, stdout="{}"))
    result = lint_openspec(target=f"{root}/spec\x00.md")
    assert "\x00" not in json.dumps(result)


# --------------------------------------------------------------------------
# The payload is evidence, and evidence is bounded and redacted.
#
# Both controls previously lived only in the branch that FAILED to parse, so
# the common case -- valid JSON -- routed straight past them.
# --------------------------------------------------------------------------


def test_an_oversized_payload_is_refused_without_changing_the_verdict(fake_planlint, configured):
    configured(
        fake_planlint(exit_code=1, stdout=FINDINGS_JSON),
        FOUNDRY_SPIKE_FINDINGS_MAX_BYTES="10",
    )
    result = lint_openspec()
    # The exit code is the verdict. A payload too large to hand back downgrades
    # the evidence and must not turn FINDINGS into anything else.
    assert result["verdict"] == FINDINGS
    assert result["exit_code"] == 1
    assert result["findings_truncated"] is True
    assert result["findings"] is None
    assert "over the 10 byte findings limit" in result["findings_parse_error"]
    # The evidence is downgraded, not destroyed: an excerpt still reaches the
    # caller so a human can see what was dropped.
    assert result["stdout_excerpt"]


def test_the_findings_limit_is_configuration_not_a_constant(fake_planlint, configured):
    """The same payload passes or is refused purely on the configured ceiling."""
    configured(
        fake_planlint(exit_code=1, stdout=FINDINGS_JSON),
        FOUNDRY_SPIKE_FINDINGS_MAX_BYTES=str(len(FINDINGS_JSON) + 1),
    )
    kept = lint_openspec()
    assert kept["findings_truncated"] is False
    assert kept["findings"] is not None

    configured(
        fake_planlint(exit_code=1, stdout=FINDINGS_JSON),
        FOUNDRY_SPIKE_FINDINGS_MAX_BYTES=str(len(FINDINGS_JSON) - 1),
    )
    assert lint_openspec()["findings_truncated"] is True


def test_a_credential_inside_valid_json_is_redacted(fake_planlint, configured):
    """The gap this closes: redaction ran only on unparsable stdout, so a token
    inside a payload that parsed went back to the model verbatim."""
    token = "ghp_" + "A" * 36
    configured(
        fake_planlint(
            exit_code=1,
            stdout=json.dumps({"findings": [{"rule": "R1", "message": f"leaked {token}"}]}),
        )
    )
    result = lint_openspec()
    assert result["verdict"] == FINDINGS
    serialised = json.dumps(result["findings"])
    assert token not in serialised
    assert "[REDACTED:github-token]" in serialised


def test_redaction_preserves_the_structure_it_redacts(fake_planlint, configured):
    """Redacting the raw JSON text instead would be simpler and wrong: the
    authorization pattern consumes to the next whitespace, eating the closing
    quote and leaving text that no longer parses."""
    configured(
        fake_planlint(
            exit_code=1,
            stdout=json.dumps(
                {"findings": [{"rule": "R1", "message": "authorization: Bearer abc123"}]}
            ),
        )
    )
    result = lint_openspec()
    assert isinstance(result["findings"], dict)
    finding = result["findings"]["findings"][0]
    assert finding["rule"] == "R1"
    assert "abc123" not in finding["message"]
    assert "[REDACTED]" in finding["message"]


def test_nothing_truncated_reports_false_rather_than_null(fake_planlint, configured):
    """A caller branching on this key must never have to treat null as a third
    state. On a path where no payload was read, nothing was truncated."""
    configured(fake_planlint(exit_code=0, stdout=json.dumps({"findings": []})))
    assert lint_openspec()["findings_truncated"] is False
    # Refused before any process started: still false, never null.
    assert lint_openspec(target="relative/path")["findings_truncated"] is False


def test_an_injected_config_overrides_the_environment(fake_planlint, configured):
    """`config=` exists so in-process callers can vary settings without mutating
    os.environ, which is global and has bitten this repository once already."""
    configured(fake_planlint(exit_code=1, stdout=FINDINGS_JSON))
    injected = replace(load_planlint_config(), findings_max_bytes=1)
    assert lint_openspec(config=injected)["findings_truncated"] is True
    # The environment was never touched to achieve that, so the very next call
    # with no injected config still sees the configured ceiling.
    assert lint_openspec()["findings_truncated"] is False


# --------------------------------------------------------------------------
# Copilot review, PR #1. The JSON flag is whatever spelling session 1 finds in
# `validate --help`, and `00-baseline.sh` reports `--format` as a candidate.
# Appending it whole passed a single argv token "--format json", which planlint
# rejects -- exit 2, BLOCKED, for a *configuration* reason indistinguishable
# from a real precondition error. Two of this repo's own files pointed the
# operator into that trap.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spelling", "expected_tail"),
    [
        ("--json", ["--json"]),
        ("--format json", ["--format", "json"]),
        ("--format=json", ["--format=json"]),
        ("--output json", ["--output", "json"]),
        ("  --json  ", ["--json"]),
    ],
)
def test_multi_token_json_flag_becomes_separate_argv_entries(
    fake_planlint, configured, spelling, expected_tail
):
    configured(fake_planlint(exit_code=0, stdout="{}"), PLANLINT_JSON_FLAG=spelling)
    command = lint_openspec()["command"]
    assert command[-len(expected_tail):] == expected_tail
    assert not any(" " in token for token in command[3:]), f"unsplit token in {command}"


def test_a_multi_token_flag_does_not_confuse_the_verb_check(fake_planlint, configured):
    """`--format json` puts a bare token in argv. The verb scan must still find
    `validate`, not treat `json` as the verb and refuse the call."""
    configured(fake_planlint(exit_code=1, stdout="{}"), PLANLINT_JSON_FLAG="--format json")
    result = lint_openspec()
    assert result["verdict"] == FINDINGS
    assert result["blocked_reason"] is None


# --------------------------------------------------------------------------
# Execution failures after the pre-flight check passed. These were correct and
# unpinned: the `shutil.which` probe catches an absent binary, so everything
# below is the case where a binary exists and still cannot be run.
# --------------------------------------------------------------------------


def test_a_binary_that_cannot_be_executed_is_blocked_not_crashed(
    tmp_path, configured, fake_planlint
):
    """A directory passes the pre-flight existence check and then fails at
    `execve`. That handler was reachable and untested.

    A shebang pointing at nothing does *not* get here, which is worth writing
    down: on ENOEXEC `subprocess` retries through `/bin/sh`, so a file with an
    unusable interpreter runs as a shell script and can exit 0. The pre-flight
    check plus this branch are what stand between that and a fabricated PASS.
    """
    directory = tmp_path / "not-a-binary"
    directory.mkdir()
    configured(fake_planlint(exit_code=0))
    result = lint_openspec(config=replace(load_planlint_config(), binary=str(directory)))
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] in {"process_error", BLOCKED_TOOL_NOT_FOUND}
    assert result["exit_code"] is None


def test_a_parsed_payload_never_overrides_the_exit_code(fake_planlint, configured):
    """`verdicts.py` states it and nothing tested it. planlint exiting 0 while
    printing findings is a planlint bug; reporting it as FINDINGS would make
    this wrapper's verdict depend on a payload, which is the inversion the
    whole contract forbids."""
    configured(fake_planlint(exit_code=0, stdout=FINDINGS_JSON))
    result = lint_openspec()
    assert result["verdict"] == PASS
    assert result["exit_code"] == 0
    # The payload is still handed back as evidence, unaltered.
    assert result["findings"]["findings"][0]["rule"] == "SPEC001"


def test_an_empty_findings_list_on_exit_one_is_still_findings(fake_planlint, configured):
    """The mirror image. An empty payload does not soften a nonzero exit."""
    configured(fake_planlint(exit_code=1, stdout=json.dumps({"findings": []})))
    assert lint_openspec()["verdict"] == FINDINGS


def test_detect_dialect_goes_through_the_same_guarded_path(fake_planlint, configured):
    """`detect` is in the allow list, so it must be reachable. It had no test,
    which is how a verb list comes to advertise something that cannot run."""
    configured(fake_planlint(exit_code=0, stdout=json.dumps({"dialect": "openspec"})))
    result = detect_dialect()
    assert result["verdict"] == PASS
    assert result["verb"] == "detect"
    assert result["findings"] == {"dialect": "openspec"}


def test_detect_dialect_refuses_a_target_outside_the_allow_list(fake_planlint, configured):
    configured(fake_planlint(exit_code=0, stdout="{}"))
    result = detect_dialect(target="/etc")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


def test_the_findings_ceiling_is_measured_in_bytes_not_characters(fake_planlint, configured):
    """Contract review finding. `stdout` arrives decoded, so a character count
    let a multi-byte payload through a ceiling named in bytes: 100 CJK
    characters are 300 UTF-8 bytes."""
    payload = json.dumps({"m": "漢" * 100}, ensure_ascii=False)
    assert len(payload) < 200 < len(payload.encode("utf-8"))
    configured(fake_planlint(exit_code=1, stdout=payload))
    result = lint_openspec(config=replace(load_planlint_config(), findings_max_bytes=200))
    assert result["findings_truncated"] is True
    assert result["verdict"] == FINDINGS
    # And the reported size is the byte count, matching the setting's units.
    assert f"{len(payload.encode('utf-8'))} bytes" in result["findings_parse_error"]


def test_a_multibyte_payload_under_the_ceiling_still_parses(fake_planlint, configured):
    payload = json.dumps({"m": "漢" * 10}, ensure_ascii=False)
    configured(fake_planlint(exit_code=1, stdout=payload))
    result = lint_openspec(config=replace(load_planlint_config(), findings_max_bytes=4096))
    assert result["findings_truncated"] is False
    assert result["findings"] == {"m": "漢" * 10}
