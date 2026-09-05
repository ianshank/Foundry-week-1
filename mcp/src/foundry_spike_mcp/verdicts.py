"""The three-valued verdict vocabulary, and nothing else.

This module exists so that every other module imports the *same* strings.
A fourth verdict is a governance hole: the agent instructions in Step 4.2 of
the runbook define behaviour for exactly PASS, FINDINGS and BLOCKED. Anything
outside that set is a state the agent has no rule for, and an agent without a
rule improvises.

Authority rule, stated once and relied on everywhere:

    The process exit code is the verdict. The stdout payload is evidence.

An unparsable payload never changes a verdict. A parsed payload never
overrides one.
"""

from __future__ import annotations

PASS = "PASS"
FINDINGS = "FINDINGS"
BLOCKED = "BLOCKED"

VERDICTS = (PASS, FINDINGS, BLOCKED)

#: Documented planlint exit codes. Anything else is deliberately absent --
#: see :func:`verdict_for_exit_code` for why unmapped codes become BLOCKED.
EXIT_VERDICT = {
    0: PASS,
    1: FINDINGS,
    2: BLOCKED,
}

# Why a run could not form an opinion. Always paired with BLOCKED.
BLOCKED_PRECONDITION = "precondition_error"
BLOCKED_TIMEOUT = "timeout"
BLOCKED_TOOL_NOT_FOUND = "tool_not_found"
BLOCKED_UNEXPECTED_EXIT = "unexpected_exit_code"
BLOCKED_GUARD_REJECTED = "guard_rejected"
BLOCKED_ARTIFACT_MISSING = "artifact_missing"
BLOCKED_ARTIFACT_UNREADABLE = "artifact_unreadable"
BLOCKED_ARTIFACT_SCHEMA = "unrecognized_artifact_schema"
BLOCKED_NO_SCORED_RESULTS = "no_scored_results"

BLOCKED_NOTE = (
    "BLOCKED means the run could not form an opinion. It is not a spec failure "
    "and must never be reported as a pass."
)

FINDINGS_NOTE = (
    "FINDINGS means the run completed and found problems at or above the "
    "threshold. The exit code is the verdict; the findings payload is evidence."
)


def verdict_for_exit_code(code: int) -> tuple[str, str | None]:
    """Map a process exit code to ``(verdict, blocked_reason)``.

    Unmapped codes collapse to BLOCKED rather than to a fourth "UNKNOWN"
    verdict, and never to PASS. A segfault or an unrecognised failure mode is
    precisely "could not form an opinion"; the raw code is still returned to
    the caller alongside, so no information is destroyed by the collapse.
    """
    verdict = EXIT_VERDICT.get(code)
    if verdict is None:
        return BLOCKED, BLOCKED_UNEXPECTED_EXIT
    if verdict == BLOCKED:
        return BLOCKED, BLOCKED_PRECONDITION
    return verdict, None
