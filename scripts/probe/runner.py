"""Runner orchestration and summary builder for the verifier probe."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .client import call_model
from .config import REPO
from .logging_setup import get_logger
from .screen import ERROR, OK, screen

_log = get_logger("runner")


def _rel(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise -- always POSIX-separated.

    `str(Path)` is platform-native, so this used to write
    `configs\\probes\\02-verifier.md` on Windows and
    `configs/probes/02-verifier.md` on Linux for the same run. `summary.json`
    is tracked evidence; two captures of one run must not differ by separator.
    A Windows drive letter survives in the absolute branch, which is right --
    an absolute path off this machine is not portable and should not pretend.
    """
    resolved = path.resolve()
    try:
        return PurePosixPath(resolved.relative_to(REPO)).as_posix()
    except ValueError:
        return resolved.as_posix()


def row_reached_a_model(row: Mapping[str, Any]) -> bool:
    """Did this slot get an answer back from a model?

    One reader for a fact two gates were spelling differently: `cli.main`
    decides the exit code on `row["screen"]`, `promote_trace` decides
    promotion on `row["status"]`, and `ERROR` is the single value that appears
    in both vocabularies. Nothing tied the two together, so if `call_model`'s
    envelope ever stopped emitting `status`, the promotion gate would quietly
    stop refusing dead runs while the exit-code guard stayed green.

    Stated positively -- `status == OK`, not `status != ERROR` -- so a row
    whose status is missing, or is some third value this code has never seen,
    counts as *not* having reached a model. Refusing a shape it cannot read is
    the only safe direction: the negative form is vacuously true for a key
    that is never there, which would make every dead run promotable.

    `screen` is checked too, because the two keys are two spellings of one
    fact and a row that disagrees with itself is not evidence either way.
    """
    return row.get("status") == OK and row.get("screen") != ERROR


def no_model_answered(summary: Mapping[str, Any]) -> bool:
    """True when a capture's every row failed before reaching a model.

    Returns False for a summary this cannot positively read as such -- no
    `results` list, or an empty one. `promote_trace` depends on that: manual
    exports have no `summary.json` at all and are a documented input.
    """
    rows = summary.get("results") if isinstance(summary, Mapping) else None
    if not isinstance(rows, list) or not rows:
        return False
    return all(
        isinstance(row, Mapping) and not row_reached_a_model(row) for row in rows
    )


def run_probe_cells(
    slots: list[str],
    system: str,
    user: str,
    expect: str,
    out_dir: Path,
    timeout: int,
    sampling: dict[str, Any],
    call_model_fn: Any = None,
) -> list[dict[str, Any]]:
    """Execute probe against list of slots, save transcripts and return row summaries."""
    actual_call_model = call_model_fn if call_model_fn is not None else call_model
    rows: list[dict[str, Any]] = []
    for slot in slots:
        print(f"-> {slot}", file=sys.stderr, flush=True)
        response = actual_call_model(slot, system, user, timeout, sampling)
        if response["status"] == ERROR:
            row = {"slot": slot, "screen": ERROR, **response}
        else:
            row = {"slot": slot, **response, **screen(response["text"], expect)}
        rows.append(row)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", slot)
        try:
            (out_dir / f"{safe}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        except OSError as error:
            # The model has already been called and the tokens already spent,
            # so losing the run because the transcript could not be written is
            # the most expensive possible failure. The row is in memory and
            # still belongs in `summary.json`; record that its transcript is
            # missing and carry on. `cli.py` applies the same reasoning to
            # `--out` one function earlier, and it was not carried through
            # here.
            row["transcript_error"] = str(error)
            _log.warning(
                "transcript could not be written",
                extra={"slot": slot, "error": str(error)},
            )
        _log.info(
            "probe cell complete",
            extra={
                "slot": slot,
                "screen": row["screen"],
                "basis": row.get("basis"),
                "error": row.get("error"),
                "duration_ms": row.get("latency_ms"),
            },
        )
        print(f"   {row['screen']}  ({row.get('basis', row.get('error', ''))})", file=sys.stderr)
    return rows


def build_summary(
    stamp: str,
    prompt_path: Path,
    system_path: Path,
    expect: str,
    sampling: dict[str, Any],
    timeout: int,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate the structured summary.json dictionary."""
    return {
        "captured": stamp,
        "prompt": _rel(prompt_path),
        "system_prompt": _rel(system_path),
        "expected_verdict": expect,
        "sampling": sampling,
        "timeout_seconds": timeout,
        "screen_is_advisory": (
            "HELD/LAUNDERED/REVIEW is a screen, not a grade. REVIEW means read the "
            "transcript. Every cell in evidence/02-bakeoff.md still needs a human line."
        ),
        "results": [
            {key: value for key, value in row.items() if key != "text"} for row in rows
        ],
    }


def format_report_table(rows: list[dict[str, Any]], out_dir: Path) -> str:
    """Format the terminal report table."""
    lines: list[str] = [""]
    width = max((len(row["slot"]) for row in rows), default=4)
    lines.append(f"{'slot'.ljust(width)}  screen      declared   tokens  ms")
    for row in rows:
        lines.append(
            f"{row['slot'].ljust(width)}  {str(row['screen']).ljust(10)}  "
            f"{str(row.get('declared') or '-').ljust(9)}  "
            f"{str(row.get('total_tokens') or '-').rjust(6)}  {row.get('latency_ms', '-')}"
        )
    lines.append(f"\nTranscripts: {out_dir}")
    lines.append("REVIEW and ERROR rows are not results. Read them before filling the matrix.")
    return "\n".join(lines)
