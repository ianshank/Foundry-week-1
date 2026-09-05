"""`lint_openspec` -- a read-only subprocess wrapper over `planlint validate`.

planlint's README states its surface as "CLI with an exit code; no UI, no MCP
server". This wrapper honours that: it shells out and reads an exit code. It
imports nothing from `openspec_graph`, and it lives in the spike repo rather
than in planlint's.

The one job of this module is that planlint's three-way exit code survives the
trip into a language model intact:

    0 -> PASS      no findings at or above the threshold
    1 -> FINDINGS  the run completed and found problems
    2 -> BLOCKED   precondition or usage error; the run could not look

It follows that **no code path in this module may raise**. An exception is not
a verdict. If `lint_openspec` throws, what reaches the model is a framework
error string with no verdict field in it, and a model asked to summarise that
will guess -- which is the exact failure this spike exists to measure. Every
failure mode below is therefore caught and mapped to BLOCKED with a reason.

Deviations from the runbook's sample code, and why:

* `subprocess.run(..., timeout=N)` *raises* `TimeoutExpired`; it does not
  return a completed process. The sample's stated refusal ("timeout maps to
  BLOCKED, never to FINDINGS") was therefore unimplemented. Caught here.
* `json.loads(proc.stdout)` on the exit-2 path parses a usage message as JSON
  and raises. That is the deliberate-BLOCKED demo the runbook's own "done
  when" requires, so it has to be the best-tested path, not the crashing one.
* `os.environ["PLANLINT_TARGET"]` raises `KeyError` when unset. Missing
  configuration is BLOCKED, not a crash.
* A missing `planlint` binary raises `FileNotFoundError`. Also BLOCKED.
* The runbook maps unrecognised exit codes to a fourth verdict, "UNKNOWN".
  See `verdicts.verdict_for_exit_code` for why they collapse to BLOCKED here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import guards
from .verdicts import (
    BLOCKED,
    BLOCKED_GUARD_REJECTED,
    BLOCKED_NOTE,
    BLOCKED_TIMEOUT,
    BLOCKED_TOOL_NOT_FOUND,
    FINDINGS,
    FINDINGS_NOTE,
    verdict_for_exit_code,
)

DEFAULT_TIMEOUT_SECONDS = 120


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _timeout_seconds() -> int:
    raw = _env("PLANLINT_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _decode(stream: Any) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return str(stream)


def _blocked(reason: str, detail: str, **extra: Any) -> dict[str, Any]:
    """Build a BLOCKED result. The only way this module reports 'I could not
    look' -- there is deliberately no other constructor for it."""
    result: dict[str, Any] = {
        "verdict": BLOCKED,
        "exit_code": None,
        "blocked_reason": reason,
        "blocked_detail": guards.clean(detail, 500),
        "findings": None,
        "contract": _contract(BLOCKED),
    }
    result.update(extra)
    return result


def _contract(verdict: str) -> dict[str, Any]:
    """The in-band statement of the authority boundary.

    Kept short on purpose: every field in a tool result is prompt surface that
    the model pays attention budget for. This says the one thing the model
    must not get wrong.
    """
    contract = {
        "authority": "exit_code",
        "verdict_derived_from": "exit_code",
        "payload_role": "evidence_only",
    }
    if verdict == BLOCKED:
        contract["note"] = BLOCKED_NOTE
    elif verdict == FINDINGS:
        contract["note"] = FINDINGS_NOTE
    return contract


def lint_openspec(target: str | None = None, fail_on: str = "ERROR") -> dict[str, Any]:
    """Run `planlint validate` read-only and report its exit code as a verdict.

    Never calls `init`, `new`, `witness`, or `make`. Never passes `--force`.
    Never writes. The `target` argument is checked against an absolute-path
    allow list from the environment before any process starts.

    Args:
        target: Absolute path to the repository to lint. Defaults to
            ``$PLANLINT_TARGET``. Must resolve inside ``$PLANLINT_ALLOWED_ROOTS``.
        fail_on: Severity threshold, e.g. ``ERROR``.

    Returns:
        A dict that always contains ``verdict`` (PASS / FINDINGS / BLOCKED),
        ``exit_code`` (int, or null when no process ran) and ``findings``.
        BLOCKED results also carry ``blocked_reason``. Never raises.
    """
    started = time.monotonic()

    try:
        roots = guards.allowed_roots()
    except guards.GuardRejection as rejection:
        return _blocked(BLOCKED_GUARD_REJECTED, str(rejection))

    raw_target = target if target is not None else _env("PLANLINT_TARGET")
    if not raw_target:
        return _blocked(
            BLOCKED_GUARD_REJECTED,
            "no target given and PLANLINT_TARGET is unset",
        )

    try:
        resolved = guards.check_target(raw_target, roots)
        threshold = guards.check_fail_on(fail_on)
    except guards.GuardRejection as rejection:
        return _blocked(BLOCKED_GUARD_REJECTED, str(rejection), target=raw_target)

    binary = _env("PLANLINT_BIN", "planlint")
    argv = [binary, "--target", str(resolved), "validate", "--fail-on", threshold]

    # The JSON flag is configurable because planlint's exact spelling is
    # confirmed in session 1 against the installed build, not guessed here.
    # Setting PLANLINT_JSON_FLAG="" disables it; parsing then falls back to
    # the raw-text path, which is a degraded result but never a wrong verdict.
    json_flag = os.environ.get("PLANLINT_JSON_FLAG", "--json").strip()
    if json_flag:
        argv.append(json_flag)

    try:
        guards.assert_safe_argv(argv)
    except guards.GuardRejection as rejection:
        return _blocked(BLOCKED_GUARD_REJECTED, str(rejection), target=str(resolved))

    if shutil.which(binary) is None and not Path(binary).exists():
        return _blocked(
            BLOCKED_TOOL_NOT_FOUND,
            f"{binary!r} is not on PATH",
            target=str(resolved),
            command=argv,
        )

    timeout = _timeout_seconds()
    try:
        proc = subprocess.run(  # noqa: S603 - argv is constructed, never model-supplied
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        # The refusal the runbook asked for and the sample code could not
        # deliver: a timeout is "could not look", never "found nothing".
        return _blocked(
            BLOCKED_TIMEOUT,
            f"planlint exceeded {timeout}s",
            target=str(resolved),
            command=argv,
            stderr=guards.clean(_decode(expired.stderr), guards.DEFAULT_STDERR_LIMIT),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except FileNotFoundError:
        return _blocked(
            BLOCKED_TOOL_NOT_FOUND,
            f"{binary!r} could not be executed",
            target=str(resolved),
            command=argv,
        )
    except OSError as error:  # permission denied, ENOEXEC, fork failure
        return _blocked(
            "process_error",
            f"{type(error).__name__}: {error}",
            target=str(resolved),
            command=argv,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    verdict, blocked_reason = verdict_for_exit_code(proc.returncode)
    stdout = _decode(proc.stdout)

    findings: Any = None
    parse_error: str | None = None
    if stdout.strip():
        try:
            findings = json.loads(stdout)
        except json.JSONDecodeError as error:
            # Unparsable stdout downgrades the *evidence*, never the verdict.
            # On exit 2 this is the normal case: the payload is a usage
            # message, and BLOCKED is already correct without it.
            parse_error = f"stdout is not JSON: {error}"

    result: dict[str, Any] = {
        "verdict": verdict,
        "exit_code": proc.returncode,
        "blocked_reason": blocked_reason,
        "findings": findings,
        "contract": _contract(verdict),
        "target": str(resolved),
        "command": [guards.redact(token) for token in argv],
        "duration_ms": duration_ms,
        "stderr": guards.clean(_decode(proc.stderr), guards.DEFAULT_STDERR_LIMIT),
    }
    if parse_error is not None:
        result["findings_parse_error"] = parse_error
        result["stdout_excerpt"] = guards.clean(stdout, guards.DEFAULT_STDOUT_LIMIT)
    return result
