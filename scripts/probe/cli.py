"""CLI entry point for the headless bake-off verifier probe."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    DEFAULT_TOP_P,
    ENV_PROBE_MAX_TOKENS,
    ENV_PROBE_MODELS,
    ENV_PROBE_TEMPERATURE,
    ENV_PROBE_TIMEOUT,
    ENV_PROBE_TOP_P,
    PROBES,
    REPO,
    ProbeConfigError,
    _env_number,
)
from .runner import build_summary, format_report_table, run_probe_cells
from .screen import ERROR, LAUNDERED, _strip_html_comments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Headless backstop for the bake-off verifier probe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--models",
        default=os.environ.get(ENV_PROBE_MODELS, ""),
        help="comma-separated provider:model slots",
    )
    parser.add_argument("--prompt", type=Path, default=PROBES / "02-verifier.md")
    parser.add_argument("--system", type=Path, default=PROBES / "system-prompt.md")
    parser.add_argument(
        "--expect",
        default="FINDINGS",
        choices=["PASS", "FINDINGS", "BLOCKED", "NOT_APPLICABLE"],
    )
    parser.add_argument("--out", type=Path, default=REPO / "traces" / "raw")
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", dest="top_p", type=float, default=None)
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    return parser


def main(argv: list[str] | None = None, call_model_fn: Any = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.timeout is None:
            args.timeout = _env_number(ENV_PROBE_TIMEOUT, DEFAULT_TIMEOUT, int)
        if args.temperature is None:
            args.temperature = _env_number(ENV_PROBE_TEMPERATURE, DEFAULT_TEMPERATURE, float)
        if args.top_p is None:
            args.top_p = _env_number(ENV_PROBE_TOP_P, DEFAULT_TOP_P, float)
        if args.max_tokens is None:
            args.max_tokens = _env_number(ENV_PROBE_MAX_TOKENS, DEFAULT_MAX_TOKENS, int)
    except ProbeConfigError as error:
        parser.error(str(error))

    slots = [slot.strip() for slot in args.models.split(",") if slot.strip()]
    if not slots:
        parser.error("no models given; pass --models or set PROBE_MODELS")
    for path in (args.prompt, args.system):
        if not path.is_file():
            parser.error(f"missing file: {path}")

    system = _strip_html_comments(args.system.read_text(encoding="utf-8"))
    user = _strip_html_comments(args.prompt.read_text(encoding="utf-8"))
    if "<<<" in user:
        parser.error(f"{args.prompt} is still a template -- fill in the placeholder before running")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out / f"{stamp}-{args.prompt.stem}"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        # Every other bad argument in this function reports through
        # parser.error. An unwritable --out reported through a traceback, so
        # one input was validated differently from the rest for no reason.
        parser.error(f"cannot create output directory {out_dir}: {error}")

    sampling = {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
    }

    rows = run_probe_cells(
        slots=slots,
        system=system,
        user=user,
        expect=args.expect,
        out_dir=out_dir,
        timeout=args.timeout,
        sampling=sampling,
        call_model_fn=call_model_fn,
    )

    summary = build_summary(
        stamp=stamp,
        prompt_path=args.prompt,
        system_path=args.system,
        expect=args.expect,
        sampling=sampling,
        timeout=args.timeout,
        rows=rows,
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(format_report_table(rows, out_dir))
    # Three states, because callers read three facts off this byte and there
    # used to be only two available. `make probe` was green for a bake-off in
    # which no endpoint answered, because "nothing laundered" and "nothing ran"
    # were the same exit code.
    #
    # Laundering outranks an unusable run: if any model that *did* answer
    # laundered a failing verdict, that is the finding, and a second dead slot
    # in the same run must not downgrade it to a plumbing complaint.
    if any(row["screen"] == LAUNDERED for row in rows):
        return 1
    if all(row["screen"] == ERROR for row in rows):
        return 2
    return 0
