"""Runner orchestration and summary builder for the verifier probe."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .client import call_model
from .config import REPO
from .screen import ERROR, screen


def _rel(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise."""
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path.resolve())


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
        (out_dir / f"{safe}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
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
