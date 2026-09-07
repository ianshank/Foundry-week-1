"""The contract tests. If one of these fails, stop condition 2 is in play.

Read these as the specification: `lint_openspec` maps planlint's exit code to
a three-way verdict, never raises, and never lets a payload problem change a
verdict.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
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


@pytest.mark.parametrize("code", [3, 42, 126, 127, 255])
def test_no_unmapped_exit_code_reaches_pass(fake_planlint, configured, code):
    configured(fake_planlint(exit_code=code, stdout=""))
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_UNEXPECTED_EXIT
    assert result["exit_code"] == code


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "POSIX signals (SIGKILL, SIGSEGV) are not applicable on Windows. "
        "The negative-returncode contract is POSIX-only; on Windows a killed "
        "process returns a non-zero positive code, which maps to "
        "BLOCKED_UNEXPECTED_EXIT by the same code path -- but we cannot "
        "use os.kill(pid, SIGKILL) to produce that here."
    ),
)
@pytest.mark.parametrize("signal_name", ["SIGKILL", "SIGSEGV"])
def test_a_process_killed_by_a_signal_is_blocked_never_pass(
    tmp_path, configured, fake_planlint, signal_name
):
    """A signal death reports a *negative* return code, and only 139 was ever
    tested -- which is the shell's encoding, not Python's. `subprocess` gives
    -11 for SIGSEGV, so the mapping was right by omission rather than intent.

    Killed for real rather than simulated with `sys.exit(-11)`: those are
    different things, and only the first produces a negative returncode.

    Skipped on Windows: POSIX process-group signals have no equivalent;
    `os.kill(pid, signal.SIGKILL)` itself raises `OSError` on Windows.
    The negative-returncode branch is exercised by the parametrized
    `test_the_exit_code_mapping_never_returns_pass_for_an_unknown_code`
    which covers code -11 in-process without spawning a POSIX signal.
    """
    # A distinct filename on purpose: `fake_planlint` writes to
    # `bin/planlint`, so naming this the same silently overwrote it and the
    # test measured the fixture instead of the signal. It passed for the wrong
    # reason first time round.
    script_dir = tmp_path / "bin"
    script_dir.mkdir(parents=True, exist_ok=True)
    py_name = f"planlint-{signal_name.lower()}.py"
    py_script = script_dir / py_name
    py_script.write_text(
        "import os, signal\n"
        f"os.kill(os.getpid(), signal.{signal_name})\n",
        encoding="utf-8",
    )
    sh = script_dir / f"planlint-{signal_name.lower()}"
    sh.write_text(
        f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    sh.chmod(0o755)
    configured(fake_planlint(exit_code=0))
    result = lint_openspec(config=replace(load_planlint_config(), binary=str(sh)))
    assert result["exit_code"] is not None and result["exit_code"] < 0
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_UNEXPECTED_EXIT


@pytest.mark.parametrize("code", [-11, -9, -15, 3, 42, 126, 127, 255, 1000])
def test_the_exit_code_mapping_never_returns_pass_for_an_unknown_code(code):
    from foundry_spike_mcp.verdicts import verdict_for_exit_code

    verdict, reason = verdict_for_exit_code(code)
    assert verdict == BLOCKED
    assert reason == BLOCKED_UNEXPECTED_EXIT


def test_an_unparseable_json_flag_is_blocked_not_raised(fake_planlint, configured):
    """`shlex.split` raises on an unbalanced quote, and the value comes from the
    environment. `PLANLINT_JSON_FLAG='\"'` sent a bare ValueError out of
    `run_verb` -- a framework error with no verdict field, reached through the
    one setting the module spends nine lines explaining how to get right."""
    configured(fake_planlint(exit_code=0, stdout="{}"), PLANLINT_JSON_FLAG='"')
    result = lint_openspec()
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == "configuration_error"
    assert "PLANLINT_JSON_FLAG" in result["blocked_detail"]


def test_a_timeout_reaps_the_whole_process_tree(tmp_path, configured, fake_planlint):
    """`subprocess.run(timeout=)` kills the direct child only, so a wrapper
    that starts a worker leaked that worker on every timeout -- holding the
    stdout pipe and accumulating for the life of the server.

    The grandchild is given a distinctive name so the assertion cannot match
    this test's own process or the harness's.

    Two things made an earlier version of this test pass without testing
    anything, and both are guarded against below.

    It named the grandchild with `sh -c 'exec -a MARKER sleep 45'`. `exec -a`
    is a bashism; `/bin/sh` here and on the CI runner is dash, whose `exec`
    rejects it -- so the grandchild exited 127 immediately and was never
    created. The closing "nothing leaked" assertion was then trivially true,
    and the process-group reaping it claims to verify never ran at all.

    It also counted `ps -eo comm`, which reports the executable name rather
    than argv[0], so even where `exec -a` works the marker would not appear
    there. The grandchild is now a file *named* for the marker, which both
    `comm` and `args` show honestly, and the count reads `args` because Linux
    truncates `comm` to 15 characters.

    The structural fix is the `peak` assertion: the test now proves the
    grandchild existed before it proves it was reaped. A fixture that fails to
    start one fails the test instead of passing it.
    """
    if not hasattr(os, "killpg"):  # pragma: no cover - Windows
        pytest.skip("process groups are POSIX-only")

    marker = "ZZ_FOUNDRY_GRANDCHILD_ZZ"
    # Named, not renamed: no `exec -a`, and the shell stays alive as the
    # process holding the marker (an `exec sleep` here would replace it and
    # take the name back out of the listing).
    grandchild = tmp_path / "bin" / marker
    grandchild.parent.mkdir(parents=True, exist_ok=True)
    grandchild.write_text("#!/bin/sh\nsleep 45\n", encoding="utf-8")
    grandchild.chmod(0o755)

    script = tmp_path / "bin" / "planlint-tree"
    script.write_text(f"#!/bin/sh\n{grandchild} &\nsleep 45\n", encoding="utf-8")
    script.chmod(0o755)

    def _alive() -> int:
        # `-ww`, because `ps` truncates the command column to the terminal
        # width (80 when there is no tty) and the marker is the *last* path
        # component. Under pytest's real tmp path that cut lands mid-marker, so
        # a running grandchild counted as zero -- the same silent false-negative
        # this test was rewritten to eliminate, arriving by a different route.
        listing = subprocess.run(
            ["ps", "-eww", "-o", "args"], capture_output=True, text=True, check=False
        )
        return sum(1 for line in listing.stdout.splitlines() if marker in line)

    assert _alive() == 0, "a previous run leaked; the assertion below would be meaningless"

    # Watch across the call: after it returns the grandchild should be gone,
    # so "was there ever one?" cannot be answered from the outside afterwards.
    peak = 0
    watching = True

    def _watch() -> None:
        nonlocal peak
        while watching:
            peak = max(peak, _alive())
            time.sleep(0.05)

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        configured(fake_planlint(exit_code=0), PLANLINT_TIMEOUT="1")
        result = lint_openspec(config=replace(load_planlint_config(), binary=str(script)))
    finally:
        watching = False
        watcher.join(timeout=5)

    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_TIMEOUT
    assert peak >= 1, (
        "no grandchild was ever running, so the reaping assertion below proves "
        "nothing -- the fixture failed to start one"
    )

    deadline = time.monotonic() + 10
    while _alive() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _alive() == 0, "the grandchild outlived the timeout that killed its parent"


def test_undecodable_bytes_on_stdout_are_a_verdict_not_an_exception(tmp_path, configured, fake_planlint):
    """`text=True` alone decodes with the locale encoding and strict errors, so
    a subprocess emitting a byte the locale cannot decode raised
    `UnicodeDecodeError` out of `communicate` -- a `ValueError`, so the
    `except OSError` did not catch it and it escaped `lint_openspec`.

    The module already had `_decode`, which decodes with replacement for
    exactly this reason; `text=True` made it dead code for the two streams that
    matter, because the decode happened inside `subprocess` first.
    """
    script_dir = tmp_path / "bin"
    script_dir.mkdir(parents=True, exist_ok=True)
    py_script = script_dir / "planlint-raw-bytes.py"
    # Write raw bytes that are invalid in any common encoding. Use the binary
    # buffer directly so neither the fake script nor the subprocess encoding
    # layer corrupts or rejects the data before planlint.py sees it.
    py_script.write_text(
        "import sys\n"
        'sys.stdout.buffer.write(b"\\xff\\xfe\\xff")\n'
        "sys.stdout.buffer.flush()\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        bat = script_dir / "planlint-raw-bytes.bat"
        bat.write_text(f'@"{sys.executable}" "{py_script}" %*')
        binary = str(bat)
    else:
        sh = script_dir / "planlint-raw-bytes"
        sh.write_text(
            f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        sh.chmod(sh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        binary = str(sh)
    configured(fake_planlint(exit_code=0))
    result = lint_openspec(config=replace(load_planlint_config(), binary=binary))
    # The exit code is the verdict; undecodable bytes only downgrade evidence.
    assert result["verdict"] == FINDINGS
    assert result["exit_code"] == 1
    assert result["findings"] is None
    assert result["findings_parse_error"]
