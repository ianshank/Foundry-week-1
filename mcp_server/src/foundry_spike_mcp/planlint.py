"""`lint_openspec` -- a read-only subprocess wrapper over `planlint`.

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
failure mode below is caught and mapped to BLOCKED with a reason.

Two structural properties worth stating, because both were review findings:

* **The result shape is stable.** Every return carries the same keys, whether
  the run reached planlint or was refused before it started. A contract whose
  whole premise is a predictable envelope cannot hand callers a different key
  set per code path.
* **`run_verb` is the single execution point.** Every read-only verb goes
  through it, so the allow list in `guards.py` describes something real rather
  than advertising five verbs the code could never reach.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import guards
from .config import ConfigError, PlanlintConfig, load_planlint_config
from .logging_setup import get_logger, log_result
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

BLOCKED_CONFIG_ERROR = "configuration_error"
BLOCKED_PROCESS_ERROR = "process_error"

#: Keys present on every result, so callers never have to probe for existence.
#: Order is the order a human reads them in a trace: verdict first.
_RESULT_KEYS = (
    "verdict",
    "exit_code",
    "blocked_reason",
    "blocked_detail",
    "verb",
    "target",
    "command",
    "duration_ms",
    "findings",
    "findings_parse_error",
    "findings_truncated",
    "stdout_excerpt",
    "stderr",
    "contract",
)

_log = get_logger("planlint")


def _decode(stream: Any) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return str(stream)


def _contract(verdict: str) -> dict[str, Any]:
    """The in-band statement of the authority boundary.

    Kept short on purpose: every field in a tool result is prompt surface that
    the model pays attention budget for. This says the one thing the model
    must not get wrong.
    """
    contract: dict[str, Any] = {
        "authority": "exit_code",
        "verdict_derived_from": "exit_code",
        "payload_role": "evidence_only",
    }
    if verdict == BLOCKED:
        contract["note"] = BLOCKED_NOTE
    elif verdict == FINDINGS:
        contract["note"] = FINDINGS_NOTE
    return contract


def _envelope(**overrides: Any) -> dict[str, Any]:
    """A result with every key present, then the caller's values applied.

    The stable shape is the point: a caller that reads `result["duration_ms"]`
    must not have to know whether the run got as far as starting a process.
    """
    base: dict[str, Any] = dict.fromkeys(_RESULT_KEYS)
    base["verdict"] = BLOCKED
    base["contract"] = _contract(BLOCKED)
    # False rather than None: on a path where no payload was ever read, nothing
    # was truncated, and that is a fact rather than an absence. A caller that
    # branches on this key should never have to treat null as a third state.
    base["findings_truncated"] = False
    base.update(overrides)
    if "verdict" in overrides and "contract" not in overrides:
        base["contract"] = _contract(overrides["verdict"])
    return base


def _blocked(reason: str, detail: str, limit: int, **extra: Any) -> dict[str, Any]:
    """Build a BLOCKED result. The only way this module reports 'I could not
    look' -- there is deliberately no other constructor for it."""
    return _envelope(
        verdict=BLOCKED,
        blocked_reason=reason,
        blocked_detail=guards.clean(detail, limit),
        **extra,
    )


def _read_findings(
    stdout: str, config: PlanlintConfig
) -> tuple[Any, str | None, str | None, bool]:
    """Turn planlint's stdout into evidence: parsed, bounded and redacted.

    Returns ``(findings, parse_error, stdout_excerpt, truncated)``.

    **None of this may change the verdict.** The verdict comes from the exit
    code and is already decided by the time this runs. Everything here can only
    downgrade the *evidence*, which is what the contract permits: exit 1 with
    garbage on stdout is still FINDINGS, and so is exit 1 with a payload too
    large to hand back.

    Three guarantees, each of which was previously missing on the branch that
    parses successfully -- the common one:

    * **Bounded.** The size test runs on the raw text, before `json.loads`, so
      an oversized payload is never materialised as a Python object at all. A
      valid 30 MB document used to be returned whole.
    * **Redacted.** A credential inside *valid* JSON went straight back to the
      model, because redaction only ran in the parse-failure branch. It now
      runs on the parsed structure, where it cannot corrupt the JSON.
    * **Never raises.** `json.loads` raises `RecursionError`, which is not a
      `JSONDecodeError`, on deeply nested input; the redaction walk is
      iterative for the same reason.
    """
    if not stdout.strip():
        return None, None, None, False

    # Measured on the raw stream. Parsing first to find out whether the result
    # is too big to keep is exactly the memory exhaustion this prevents.
    if len(stdout) > config.findings_max_bytes:
        _log.warning(
            "planlint stdout over the findings limit; evidence truncated, verdict unaffected",
            extra={"tool": "planlint"},
        )
        return (
            None,
            (
                f"stdout is {len(stdout)} bytes, over the "
                f"{config.findings_max_bytes} byte findings limit"
            ),
            guards.clean(stdout, config.stdout_limit),
            True,
        )

    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, RecursionError) as error:
        # Unparsable stdout downgrades the *evidence*, never the verdict. On
        # exit 2 this is the normal case: the payload is a usage message, and
        # BLOCKED is already correct without it. RecursionError is here because
        # deeply nested JSON raises it from inside `json.loads`, and it is not
        # a JSONDecodeError.
        return (
            None,
            f"stdout is not usable JSON: {type(error).__name__}: {error}",
            guards.clean(stdout, config.stdout_limit),
            False,
        )

    findings, depth_exceeded = guards.redact_structure(parsed, config.findings_max_depth)
    if depth_exceeded:
        _log.debug(
            "findings payload nested past the redaction depth limit; deep subtrees elided",
            extra={"tool": "planlint"},
        )
    return findings, None, None, False


def run_verb(
    verb: str,
    target: str | None = None,
    extra_args: tuple[str, ...] = (),
    config: PlanlintConfig | None = None,
) -> dict[str, Any]:
    """Execute one read-only planlint verb and map its exit code to a verdict.

    The single execution point for every verb in `guards.ALLOWED_VERBS`. Tools
    exposed over MCP are thin wrappers around this; the surface a model can
    reach stays deliberately narrower than the surface this function permits.

    Never raises. Every failure -- bad configuration, refused verb, target
    outside the allow list, missing binary, timeout, unparsable output -- comes
    back as a BLOCKED envelope with a `blocked_reason`.
    """
    started = time.monotonic()

    try:
        config = config or load_planlint_config()
    except ConfigError as error:
        # A misconfigured run could not form an opinion. Substituting defaults
        # here would hide an operator mistake behind a plausible-looking result.
        return _blocked(BLOCKED_CONFIG_ERROR, str(error), 500)

    limit = config.stderr_limit

    try:
        safe_verb = guards.check_verb(verb)
    except guards.GuardRejection as rejection:
        return _blocked(BLOCKED_GUARD_REJECTED, str(rejection), limit, verb=verb)

    raw_target = target if target is not None else config.target
    if not raw_target:
        return _blocked(
            BLOCKED_GUARD_REJECTED,
            "no target given and PLANLINT_TARGET is unset",
            limit,
            verb=safe_verb,
        )

    try:
        resolved = guards.check_target(
            raw_target, config.allowed_roots, "PLANLINT_ALLOWED_ROOTS (or PLANLINT_TARGET)"
        )
    except guards.GuardRejection as rejection:
        return _blocked(
            BLOCKED_GUARD_REJECTED, str(rejection), limit, verb=safe_verb, target=raw_target
        )

    argv = [config.binary, "--target", str(resolved), safe_verb, *extra_args]
    if config.json_flag:
        # `shlex.split`, not `append`. The flag is whatever spelling session 1
        # found in `validate --help`, and `--format json` is two argv tokens.
        # Appending it whole passed the single token "--format json", which
        # planlint rejects -- exit 2, BLOCKED, for a configuration reason that
        # looks exactly like a precondition error. `00-baseline.sh` reports
        # `--format` as a candidate, so this repo was routing operators into
        # that trap by its own instructions.
        argv.extend(shlex.split(config.json_flag))

    try:
        guards.assert_safe_argv(argv)
    except guards.GuardRejection as rejection:
        return _blocked(
            BLOCKED_GUARD_REJECTED, str(rejection), limit, verb=safe_verb, target=str(resolved)
        )

    redacted_argv = [guards.redact(token) for token in argv]
    common = {"verb": safe_verb, "target": str(resolved), "command": redacted_argv}

    if shutil.which(config.binary) is None and not Path(config.binary).exists():
        return _blocked(
            BLOCKED_TOOL_NOT_FOUND, f"{config.binary!r} is not on PATH", limit, **common
        )

    _log.debug("running planlint", extra={"tool": "planlint", "command": redacted_argv})
    try:
        proc = subprocess.run(  # noqa: S603 - argv is constructed, never model-supplied
            argv,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        # The refusal the runbook asked for and its sample code could not
        # deliver: a timeout is "could not look", never "found nothing".
        return _blocked(
            BLOCKED_TIMEOUT,
            f"planlint exceeded {config.timeout_seconds}s",
            limit,
            stderr=guards.clean(_decode(expired.stderr), limit),
            duration_ms=int((time.monotonic() - started) * 1000),
            **common,
        )
    except FileNotFoundError:
        return _blocked(
            BLOCKED_TOOL_NOT_FOUND, f"{config.binary!r} could not be executed", limit, **common
        )
    except OSError as error:  # permission denied, ENOEXEC, fork failure
        return _blocked(
            BLOCKED_PROCESS_ERROR, f"{type(error).__name__}: {error}", limit, **common
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    verdict, blocked_reason = verdict_for_exit_code(proc.returncode)
    stdout = _decode(proc.stdout)

    findings, parse_error, stdout_excerpt, truncated = _read_findings(stdout, config)

    result = _envelope(
        verdict=verdict,
        exit_code=proc.returncode,
        blocked_reason=blocked_reason,
        findings=findings,
        findings_parse_error=parse_error,
        findings_truncated=truncated,
        stdout_excerpt=stdout_excerpt,
        stderr=guards.clean(_decode(proc.stderr), limit),
        duration_ms=duration_ms,
        **common,
    )
    log_result(_log, "planlint", result)
    return result


def lint_openspec(
    target: str | None = None,
    fail_on: str = "ERROR",
    config: PlanlintConfig | None = None,
) -> dict[str, Any]:
    """Run `planlint validate` read-only and report its exit code as a verdict.

    Never calls `init`, `new`, `witness`, or `make`. Never passes `--force`.
    Never writes. The `target` argument is checked against an absolute-path
    allow list from the environment before any process starts.

    Args:
        target: Absolute path to the repository to lint. Defaults to
            ``$PLANLINT_TARGET``. Must resolve inside ``$PLANLINT_ALLOWED_ROOTS``.
        fail_on: Severity threshold, e.g. ``ERROR``.
        config: Pre-built settings. Optional, and not part of the MCP tool
            surface -- a model never supplies it. It exists so that in-process
            callers (`__main__`'s self-check, tests) can vary configuration
            without mutating `os.environ`, which is global, order-dependent and
            has bitten this repository once already.

    Returns:
        A dict that always contains ``verdict`` (PASS / FINDINGS / BLOCKED),
        ``exit_code`` (int, or null when no process ran) and ``findings``.
        BLOCKED results also carry ``blocked_reason``. Never raises.
    """
    try:
        config = config or load_planlint_config()
    except ConfigError as error:
        return _blocked(BLOCKED_CONFIG_ERROR, str(error), 500, verb="validate")

    try:
        threshold = guards.check_fail_on(fail_on, config.fail_on_values)
    except guards.GuardRejection as rejection:
        return _blocked(
            BLOCKED_GUARD_REJECTED, str(rejection), config.stderr_limit, verb="validate"
        )

    return run_verb("validate", target=target, extra_args=("--fail-on", threshold), config=config)


def detect_dialect(target: str | None = None) -> dict[str, Any]:
    """Run `planlint detect` read-only -- the dialect card from runbook step 0.5.

    Not exposed as an MCP tool: step 4.1 gives the agent exactly two tools. It
    exists so `make baseline` and future callers share one guarded execution
    path instead of shelling out separately, and so `detect` in the verb allow
    list refers to something reachable.
    """
    return run_verb("detect", target=target, extra_args=("--format", "json"))


__all__ = ["lint_openspec", "detect_dialect", "run_verb"]
