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
from typing import Any

from . import guards
from .config import ConfigError, EvalConfig, load_eval_config
from .logging_setup import get_logger, log_result
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
#:
#: `result` used to be here and had to go. It is a common *summary* key, so an
#: artifact like ``{"result": "pass", "scorers": [{"name": "t", "passed": null}]}``
#: produced a phantom scorer with ``passed=True`` at the document root -- which
#: flipped a run that should have been BLOCKED / no_scored_results into PASS
#: with ``pass_rate: 1.0``. That is precisely the fabrication this module's
#: docstring forbids, arriving through the shape-tolerant walk instead of
#: through a coercion.
_PASSED_KEYS = ("passed", "pass")

BLOCKED_CONFIG_ERROR = "configuration_error"

#: Keys present on every result, so callers never have to probe for existence.
_RESULT_KEYS = (
    "verdict",
    "blocked_reason",
    "blocked_detail",
    "run_id",
    "artifact",
    "scorers",
    "ignored",
    "pass_rate",
    "counts",
    "contract",
)

_EMPTY_COUNTS = {"true": 0, "false": 0, "null": 0, "unreadable": 0}

_log = get_logger("scoring")


def _contract() -> dict[str, Any]:
    return {
        "authority": "artifact",
        "tri_state": "true | false | null",
        "pass_rate_excludes_null": True,
        "note": (
            "null means the scorer produced no verdict and is excluded from "
            "pass_rate. It is not a failure and it is not a pass."
        ),
    }


def _envelope(**overrides: Any) -> dict[str, Any]:
    """A result with every key present, then the caller's values applied.

    Same reasoning as `planlint._envelope`: a caller reading `result["counts"]`
    must not have to know whether the artifact was ever opened.
    """
    base: dict[str, Any] = dict.fromkeys(_RESULT_KEYS)
    base.update(
        verdict=BLOCKED,
        scorers=[],
        ignored=[],
        pass_rate=None,
        counts=dict(_EMPTY_COUNTS),
        contract=_contract(),
    )
    base.update(overrides)
    return base


def _blocked(reason: str, detail: str, limit: int = 500, **extra: Any) -> dict[str, Any]:
    blocked = _envelope(
        verdict=BLOCKED,
        blocked_reason=reason,
        blocked_detail=guards.clean(detail, limit),
        **extra,
    )
    blocked["contract"] = {**_contract(), "note": BLOCKED_NOTE}
    return blocked


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


def _collect_scorers(
    node: Any,
    path: str = "$",
    label: str | None = None,
    out: list[dict[str, Any]] | None = None,
    ignored: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Walk the artifact for objects that carry a scorer verdict.

    Shape-agnostic on purpose: the exact `json_file` sink layout is pinned in
    session 3 against a real artifact, and an adapter written from a guess
    would silently mis-read a shape it half-matched. This finds any object with
    a recognised verdict key and records where it was found, so a wrong guess
    shows up as an odd `source_path` in the output rather than as a wrong
    number.

    Two rules keep tolerance from becoming invention:

    * A verdict-carrying object must be *nameable* -- either an explicit name
      key, or the key it hangs off (``$.scorers.exit_fidelity`` -> the scorer
      ``exit_fidelity``). An object that is nameable by neither is a summary
      field wearing a scorer's clothes.
    * The document root is only a scorer when it names itself. Otherwise a
      top-level verdict field would be counted alongside the real scorers,
      which is how a null-only run turned into a pass.

    Returns ``(scorers, ignored)``. Refusals are returned rather than dropped:
    a scorer this wrapper declined to count is exactly the thing session 3
    needs to see while pinning the real schema.
    """
    if out is None:
        out = []
    if ignored is None:
        ignored = []
    if isinstance(node, dict):
        verdict_key = next((key for key in _PASSED_KEYS if key in node), None)
        if verdict_key is not None:
            explicit = next(
                (str(node[key]) for key in _NAME_KEYS if key in node and node[key] is not None),
                None,
            )
            name = explicit or label
            if name is None:
                ignored.append(
                    {
                        "source_path": path,
                        "verdict_key": verdict_key,
                        "why": (
                            "an unnamed verdict field at the document root is a summary, "
                            "not a scorer; counting it would fabricate a result"
                        ),
                    }
                )
            else:
                out.append(
                    {
                        "scorer": name,
                        "passed": _normalise_passed(node[verdict_key]),
                        "source_path": path,
                        "named_by": "field" if explicit else "path",
                        "detail": node.get("reason") or node.get("message") or node.get("detail"),
                    }
                )
        for key, value in node.items():
            _collect_scorers(value, f"{path}.{key}", key, out, ignored)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            # A list element is always nameable by position, so a bare array of
            # unnamed records still reports. The one thing that stays refused is
            # an unnamed verdict field on the root object -- the actual defect.
            child_label = f"{label}[{index}]" if label else f"[{index}]"
            _collect_scorers(value, f"{path}[{index}]", child_label, out, ignored)
    return out, ignored


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


def score_run(
    run_id: str,
    artifact_path: str | None = None,
    config: EvalConfig | None = None,
) -> dict[str, Any]:
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
        config = config or load_eval_config()
    except ConfigError as error:
        return _blocked(BLOCKED_CONFIG_ERROR, str(error), run_id=run_id)

    if not config.allowed_roots:
        return _blocked(
            BLOCKED_GUARD_REJECTED,
            "set EVAL_ALLOWED_ROOTS or EVAL_SINK_DIR to an absolute path",
            run_id=run_id,
        )

    if artifact_path:
        candidate = artifact_path
    else:
        if any(sep in run_id for sep in ("/", "\\", "..")):
            return _blocked(
                BLOCKED_GUARD_REJECTED, f"run_id looks like a path: {run_id!r}", run_id=run_id
            )
        if config.sink_dir is None:
            return _blocked(
                BLOCKED_GUARD_REJECTED,
                "EVAL_SINK_DIR is unset and no artifact_path was given",
                run_id=run_id,
            )
        candidate = str(config.sink_dir / f"{run_id}.json")

    try:
        resolved = guards.check_target(
            candidate, config.allowed_roots, "EVAL_ALLOWED_ROOTS (or EVAL_SINK_DIR)"
        )
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
        if size > config.max_artifact_bytes:
            return _blocked(
                BLOCKED_ARTIFACT_UNREADABLE,
                f"artifact is {size} bytes, over the {config.max_artifact_bytes} limit",
                run_id=run_id,
                artifact=str(resolved),
            )
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, RecursionError) as error:
        # RecursionError comes from `json.loads` on deeply nested input and is
        # not a JSONDecodeError. Uncaught it escaped this function entirely,
        # contradicting the "never raises" contract in the module docstring.
        return _blocked(
            BLOCKED_ARTIFACT_UNREADABLE,
            f"artifact is not usable JSON: {type(error).__name__}: {error}",
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

    try:
        scorers, ignored = _collect_scorers(document)
    except RecursionError:
        # The walk is recursive too. A document deep enough to parse but too
        # deep to walk is still "could not read it", never an empty pass.
        return _blocked(
            BLOCKED_ARTIFACT_UNREADABLE,
            "artifact nests deeper than the walk can follow",
            run_id=run_id,
            artifact=str(resolved),
        )
    if not scorers:
        detail = (
            "no object in the artifact carried a recognised verdict key "
            f"({', '.join(_PASSED_KEYS)}); pin the real sink schema before trusting this tool"
        )
        if ignored:
            detail += (
                f"; {len(ignored)} verdict field(s) were refused as unnameable: "
                + ", ".join(entry["source_path"] for entry in ignored[:5])
            )
        return _blocked(
            BLOCKED_ARTIFACT_SCHEMA,
            detail,
            run_id=run_id,
            artifact=str(resolved),
            ignored=ignored,
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

    result = _envelope(
        verdict=verdict,
        blocked_reason=blocked_reason,
        run_id=run_id,
        artifact=str(resolved),
        scorers=scorers,
        ignored=ignored,
        pass_rate=pass_rate,
        counts=counts,
    )
    if verdict == BLOCKED:
        result["contract"] = {**_contract(), "note": BLOCKED_NOTE}
    log_result(_log, "score_run", result)
    return result
