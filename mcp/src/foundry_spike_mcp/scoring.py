"""`score_run` -- read-only over an eval-harness `json_file` sink artifact.

Runbook step 3.3, and runbook stop condition 3: if scoring a run requires
importing eval-harness internals rather than reading sink output, the seam is
wrong and the eval plane stays closed. This module therefore reads a file. It
imports nothing from the harness, and it is written so that discovering the
harness *does* need to be imported is a visible failure rather than a quiet
drift into `from eval_harness import ...`.

The three-valued contract, preserved end to end:

    true   the scorer ran and passed
    false  the scorer ran and failed
    null   the scorer produced no verdict (e.g. a trajectory scorer with no
           trajectory), and is excluded from `pass_rate`

Collapsing null into false fabricates failures. Collapsing it into true
fabricates passes. Both are worse than reporting null, so both are refused.

`pass_rate` follows the harness's own `EvalEngine._aggregate`: the denominator
excludes nulls. When *every* scorer is null the denominator is zero, and
`pass_rate` is null rather than 0.0 or 1.0 -- the aggregate form of the same
trap, and the one most likely to be papered over by a `or 0` somewhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import guards
from .verdicts import (
    BLOCKED,
    BLOCKED_ARTIFACT_MISSING,
    BLOCKED_ARTIFACT_SCHEMA,
    BLOCKED_ARTIFACT_UNREADABLE,
    BLOCKED_GUARD_REJECTED,
    BLOCKED_NO_SCORED_RESULTS,
    BLOCKED_NOTE,
    FINDINGS,
    PASS,
)

#: Keys that may hold a scorer's name, in preference order.
_NAME_KEYS = ("scorer", "scorer_name", "name", "scorer_id", "id")

#: Keys that may hold the three-valued verdict.
_PASSED_KEYS = ("passed", "pass", "result")

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _allowed_roots() -> list[Path]:
    """Allow list for artifact reads.

    Separate from planlint's: the eval sink and the spec repo are different
    trust surfaces and should not be widened together by accident.
    """
    raw = os.environ.get("EVAL_ALLOWED_ROOTS", "").strip()
    if not raw:
        raw = os.environ.get("EVAL_SINK_DIR", "").strip()
    if not raw:
        raise guards.GuardRejection(
            "no_allowed_roots",
            "set EVAL_ALLOWED_ROOTS or EVAL_SINK_DIR to an absolute path",
        )
    roots = []
    for entry in raw.split(os.pathsep):
        if not entry.strip():
            continue
        path = Path(entry).expanduser()
        if not path.is_absolute():
            raise guards.GuardRejection("relative_allowed_root", entry)
        roots.append(path.resolve(strict=False))
    if not roots:
        raise guards.GuardRejection("no_allowed_roots", raw)
    return roots


def _blocked(reason: str, detail: str, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "verdict": BLOCKED,
        "blocked_reason": reason,
        "blocked_detail": guards.clean(detail, 500),
        "scorers": [],
        "pass_rate": None,
        "contract": {
            "authority": "artifact",
            "tri_state": "true | false | null",
            "note": BLOCKED_NOTE,
        },
    }
    result.update(extra)
    return result


def _normalise_passed(value: Any) -> bool | None | str:
    """Return True, False, None -- or a string describing why the value is
    none of those. A value the harness meant as a verdict but that this
    wrapper cannot read is never guessed into a boolean."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "pass", "passed"}:
            return True
        if lowered in {"false", "fail", "failed"}:
            return False
        if lowered in {"null", "none", "skipped", "n/a", ""}:
            return None
    return f"unreadable:{value!r}"


def _collect_scorers(node: Any, path: str = "$", out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Walk the artifact for objects that carry a scorer verdict.

    Shape-agnostic on purpose: the exact `json_file` sink layout is pinned in
    session 3 against a real artifact, and an adapter written from a guess
    would silently mis-read a shape it half-matched. This finds any object with
    a recognised verdict key and records where it was found, so a wrong guess
    shows up as an odd `path` in the output rather than as a wrong number.
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        verdict_key = next((key for key in _PASSED_KEYS if key in node), None)
        if verdict_key is not None:
            name = next(
                (str(node[key]) for key in _NAME_KEYS if key in node and node[key] is not None),
                None,
            )
            out.append(
                {
                    "scorer": name or f"<unnamed@{path}>",
                    "passed": _normalise_passed(node[verdict_key]),
                    "source_path": path,
                    "detail": node.get("reason") or node.get("message") or node.get("detail"),
                }
            )
        for key, value in node.items():
            _collect_scorers(value, f"{path}.{key}", out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _collect_scorers(value, f"{path}[{index}]", out)
    return out


def _aggregate(scorers: list[dict[str, Any]]) -> tuple[float | None, dict[str, int]]:
    """`pass_rate` over non-null verdicts only, mirroring EvalEngine._aggregate.

    Returns ``None`` -- not 0.0 -- when nothing was scored.
    """
    counts = {"true": 0, "false": 0, "null": 0, "unreadable": 0}
    for record in scorers:
        value = record["passed"]
        if value is True:
            counts["true"] += 1
        elif value is False:
            counts["false"] += 1
        elif value is None:
            counts["null"] += 1
        else:
            counts["unreadable"] += 1
    denominator = counts["true"] + counts["false"]
    pass_rate = (counts["true"] / denominator) if denominator else None
    return pass_rate, counts


def score_run(run_id: str, artifact_path: str | None = None) -> dict[str, Any]:
    """Read one eval-harness run artifact and report per-scorer verdicts.

    Read-only. Does not execute the harness, does not import it, and does not
    write anything. Never raises.

    Args:
        run_id: The run identifier. Resolved to ``$EVAL_SINK_DIR/<run_id>.json``
            unless ``artifact_path`` is given.
        artifact_path: Absolute path to a sink artifact, which must resolve
            inside ``$EVAL_ALLOWED_ROOTS``.

    Returns:
        A dict with ``verdict``, ``scorers`` (each ``passed`` being true /
        false / null) and ``pass_rate`` (null when nothing was scored).
    """
    if not run_id or not str(run_id).strip():
        return _blocked(BLOCKED_GUARD_REJECTED, "empty run_id")
    run_id = str(run_id).strip()

    try:
        roots = _allowed_roots()
    except guards.GuardRejection as rejection:
        return _blocked(BLOCKED_GUARD_REJECTED, str(rejection), run_id=run_id)

    if artifact_path:
        candidate = artifact_path
    else:
        if any(sep in run_id for sep in ("/", "\\", "..")):
            return _blocked(BLOCKED_GUARD_REJECTED, f"run_id looks like a path: {run_id!r}", run_id=run_id)
        sink = os.environ.get("EVAL_SINK_DIR", "").strip()
        if not sink:
            return _blocked(
                BLOCKED_GUARD_REJECTED,
                "EVAL_SINK_DIR is unset and no artifact_path was given",
                run_id=run_id,
            )
        candidate = str(Path(sink).expanduser() / f"{run_id}.json")

    try:
        resolved = guards.check_target(candidate, roots)
    except guards.GuardRejection as rejection:
        return _blocked(BLOCKED_GUARD_REJECTED, str(rejection), run_id=run_id)

    if not resolved.is_file():
        return _blocked(
            BLOCKED_ARTIFACT_MISSING,
            f"no sink artifact at {resolved}",
            run_id=run_id,
            artifact=str(resolved),
        )

    try:
        size = resolved.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            return _blocked(
                BLOCKED_ARTIFACT_UNREADABLE,
                f"artifact is {size} bytes, over the {MAX_ARTIFACT_BYTES} limit",
                run_id=run_id,
                artifact=str(resolved),
            )
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return _blocked(
            BLOCKED_ARTIFACT_UNREADABLE,
            f"artifact is not JSON: {error}",
            run_id=run_id,
            artifact=str(resolved),
        )
    except OSError as error:
        return _blocked(
            BLOCKED_ARTIFACT_UNREADABLE,
            f"{type(error).__name__}: {error}",
            run_id=run_id,
            artifact=str(resolved),
        )

    scorers = _collect_scorers(document)
    if not scorers:
        return _blocked(
            BLOCKED_ARTIFACT_SCHEMA,
            "no object in the artifact carried a recognised verdict key "
            f"({', '.join(_PASSED_KEYS)}); pin the real sink schema before trusting this tool",
            run_id=run_id,
            artifact=str(resolved),
        )

    pass_rate, counts = _aggregate(scorers)

    if counts["false"] > 0:
        verdict = FINDINGS
        blocked_reason = None
    elif counts["true"] > 0:
        verdict = PASS
        blocked_reason = None
    else:
        # Every scorer was null or unreadable. The run produced no opinion,
        # which is BLOCKED -- reporting it as PASS is the exact fabrication
        # this tool exists to prevent.
        verdict = BLOCKED
        blocked_reason = BLOCKED_NO_SCORED_RESULTS

    return {
        "verdict": verdict,
        "blocked_reason": blocked_reason,
        "run_id": run_id,
        "artifact": str(resolved),
        "scorers": scorers,
        "pass_rate": pass_rate,
        "counts": counts,
        "contract": {
            "authority": "artifact",
            "tri_state": "true | false | null",
            "pass_rate_excludes_null": True,
            "note": (
                "null means the scorer produced no verdict and is excluded from "
                "pass_rate. It is not a failure and it is not a pass."
            ),
        },
    }
