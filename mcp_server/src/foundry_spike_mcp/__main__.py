"""Entry point: `serve` for the MCP stdio server, `selfcheck` for evidence.

`selfcheck` exists because runbook step 3's "done when" asks for structured
output on a PASS case, a FINDINGS case and a deliberately BLOCKED case. Doing
that by hand in the Agent Builder UI produces a screenshot; doing it here
produces a JSON file with exit codes in it that a reviewer can re-run.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import (
    ENV_SELFCHECK_BLOCKED_TARGET,
    ENV_SELFCHECK_FINDINGS_TARGET,
    ENV_SELFCHECK_PASS_TARGET,
    ConfigError,
    load_planlint_config,
)
from .planlint import lint_openspec
from .verdicts import BLOCKED, FINDINGS, PASS


def _selfcheck(output: Path | None) -> int:
    """Exercise all three verdicts and report whether each landed correctly.

    The BLOCKED case defaults to a fresh empty directory rather than a
    hardcoded path: a directory with no `openspec/` tree is exactly the
    precondition error the runbook asks for, and creating one is more reliable
    than hoping a stale path is still empty.
    """
    blocked_target = os.environ.get(ENV_SELFCHECK_BLOCKED_TARGET, "").strip()
    scratch: tempfile.TemporaryDirectory[str] | None = None
    if not blocked_target:
        scratch = tempfile.TemporaryDirectory(prefix="foundry-spike-blocked-")
        blocked_target = scratch.name

    config_error: str | None = None
    try:
        config = load_planlint_config()
        # The scratch dir must be inside the allow list or the guard, quite
        # correctly, refuses before planlint ever runs -- which would prove
        # the guard works but not that exit 2 survives.
        config = dataclasses.replace(
            config,
            allowed_roots=config.allowed_roots + (Path(blocked_target),)
        )
    except ConfigError as error:
        # `ConfigError`, not `ValueError`. The wider catch was one refactor
        # away from swallowing an unrelated ValueError and reporting a
        # misconfigured run as a clean one -- and a self-check that hides why
        # it fell back is the failure mode this file exists to detect.
        # Recorded rather than discarded, so the report says what happened.
        config = None
        config_error = str(error)

    # The constant travels with the case so the skip message and the lookup
    # cannot drift: the message used to be rebuilt as an f-string from the
    # case name, which is a second spelling of the variable it names.
    cases = [
        ("pass", ENV_SELFCHECK_PASS_TARGET, PASS),
        ("findings", ENV_SELFCHECK_FINDINGS_TARGET, FINDINGS),
        ("blocked", ENV_SELFCHECK_BLOCKED_TARGET, BLOCKED),
    ]

    report: dict[str, Any] = {"cases": [], "all_expected": True}
    if config_error is not None:
        report["config_error"] = config_error
    for name, env_name, expected in cases:
        target = (
            blocked_target
            if env_name == ENV_SELFCHECK_BLOCKED_TARGET
            else os.environ.get(env_name, "").strip()
        )
        if not target:
            report["cases"].append(
                {
                    "case": name,
                    "skipped": True,
                    "why": f"set {env_name} to run this case",
                }
            )
            report["all_expected"] = False
            continue
        result = lint_openspec(target=target, config=config)
        matched = result["verdict"] == expected
        report["all_expected"] = report["all_expected"] and matched
        report["cases"].append(
            {
                "case": name,
                "target": target,
                "expected_verdict": expected,
                "actual_verdict": result["verdict"],
                "exit_code": result.get("exit_code"),
                "blocked_reason": result.get("blocked_reason"),
                "matched": matched,
                "result": result,
            }
        )

    text = json.dumps(report, indent=2, sort_keys=False)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)

    if scratch is not None:
        scratch.cleanup()
    return 0 if report["all_expected"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foundry-spike-mcp")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the stdio MCP server (default)")
    check = sub.add_parser("selfcheck", help="prove PASS / FINDINGS / BLOCKED all land")
    check.add_argument("--out", type=Path, default=None, help="write the JSON report here")

    args = parser.parse_args(argv)
    if args.command == "selfcheck":
        return _selfcheck(args.out)

    from .server import main as serve

    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
