#!/usr/bin/env python3
"""Move a raw capture into tracked evidence, but only if it scans clean.

Closes the gap between `traces/raw/` (gitignored, where `verifier_probe.py`
and manual exports land) and `traces/` (tracked, what `evidence/02-bakeoff.md`
cites). Without it the evidence chain dead-ends: a matrix cell points at a run
directory that is not in the repository, so a reviewer cannot follow it.

The refusal is the point. Promotion runs the secret pass first and **will not
copy** a directory with a hit, because the moment a transcript becomes tracked
it is one `git push` from being public -- and this repository holds output
derived from private source repos.

    python3 scripts/promote_trace.py traces/raw/20260905T144347Z-02-verifier
    python3 scripts/promote_trace.py <dir> --as session-2-verifier
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Load-bearing, and the reason the fallback arms below it are gone.
#
# `make promote` and `make probe` invoke these scripts by bare path
# (`$(PY) scripts/promote_trace.py ...`), and for a script run `sys.path[0]` is
# the *script's* directory -- `scripts/` -- not the repository root. This insert
# is what makes the `scripts.`-prefixed imports resolve there, which is what
# makes the `except ImportError` arms unreachable.
#
# The two are mutually redundant: delete either and the other carries it, delete
# both and `make promote` breaks. Verified from a foreign cwd with a clean
# PYTHONPATH -- without this insert the primary arm raises
# `No module named 'scripts.scan_evidence'`.
#
# The `scripts.` spelling is the one mypy resolves, because `mypy_path` has the
# repo root and not `scripts/` (adding the latter would make every script a
# duplicate module). So the prefixed arm is the one that has to survive.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# `no_model_answered` is the single reader of "did a model answer", shared with
# `probe.cli`'s exit code so the two gates cannot drift apart. Imported rather
# than reimplemented, for the same reason `scan_file` is: two definitions of one
# fact drift, and the one that drifts is the one nobody reads.
#
# E402 is unavoidable and deliberate -- these cannot precede the `sys.path`
# insert above that makes them resolvable. Same as `scan_evidence.py`.
from scripts.probe.runner import no_model_answered  # noqa: E402
from scripts.scan_evidence import scan_file  # noqa: E402

TRACES = REPO / "traces"
SKIP_NAMES = {"__pycache__", ".DS_Store"}

#: How many scan hits the refusal message lists before truncating. Named
#: rather than left as a bare slice, matching `scan_evidence.PATTERN_PREVIEW_CHARS`.
#: Deliberately not configurable: it is display width, and the message now
#: states how many were suppressed, so nothing is hidden by the truncation.
MAX_REPORTED_FINDINGS = 10


class PromotionRefused(RuntimeError):
    """The capture was not promoted, and the message says why."""


def _no_model_answered(source: Path) -> bool:
    """True when `summary.json` exists and says every slot errored.

    Absent, unreadable or unrecognised `summary.json` returns False: manual
    exports are a supported input and this gate must not refuse a capture it
    simply does not understand. It refuses only what it can positively read as
    a run in which nothing was contacted.
    """
    summary_path = source / "summary.json"
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return False
    # Delegated so there is one reader of "did a model answer". This gate and
    # `probe.cli`'s exit code were deciding the same fact from different keys
    # -- `status` here, `screen` there -- with nothing tying them together.
    return no_model_answered(summary)


def promote(
    source: Path,
    name: str | None = None,
    destination_root: Path | None = None,
    allow_error_run: bool = False,
) -> Path:
    """Copy `source` into the tracked traces directory after a clean scan.

    Returns the destination path. Raises `PromotionRefused` rather than
    exiting, so this is usable as a library call from a test.
    """
    source = source.resolve()
    if not source.is_dir():
        raise PromotionRefused(f"{source} is not a directory")

    root = (destination_root or TRACES).resolve()
    destination = root / (name or source.name)
    if destination.exists():
        raise PromotionRefused(
            f"{destination} already exists; pass --as <name> or remove it first. "
            "Overwriting a promoted trace would silently rewrite evidence."
        )

    if not allow_error_run and _no_model_answered(source):
        raise PromotionRefused(
            f"{source} records a run in which no model answered -- every result has "
            "status ERROR. Promoting it would put a capture into tracked traces/ that "
            "evidence/02-bakeoff.md could cite as a result. Fix the endpoint and "
            "re-run, or pass --allow-error-run if the error transcript is the evidence."
        )

    findings: list[str] = []
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        # Scoped to the capture. Matched against `path.parts` -- the *absolute*
        # path -- this skipped every file under a capture whose ancestor
        # directory happened to be named `__pycache__`, while
        # `shutil.copytree`'s `ignore_patterns` below matches per-directory
        # basenames and copied them anyway. The result was an unscanned
        # credential promoted into tracked `traces/` under a printed success,
        # which is the exact outcome this function exists to prevent.
        relative = path.relative_to(source)
        if any(part in SKIP_NAMES for part in relative.parts):
            continue
        for line_number, kind, _pattern in scan_file(path):
            # Relative on both branches. The `line_number == 0` case printed
            # the absolute path, leaking the operator's home directory into a
            # refusal message.
            where = f"{relative}:{line_number}" if line_number else str(relative)
            findings.append(f"{where} [{kind}]")
    if findings:
        shown = findings[:MAX_REPORTED_FINDINGS]
        more = len(findings) - len(shown)
        raise PromotionRefused(
            "secret scan found "
            f"{len(findings)} hit(s); not promoting:\n  " + "\n  ".join(shown)
            + (f"\n  ... and {more} more" if more else "")
        )

    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*SKIP_NAMES))
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a run directory under traces/raw/")
    parser.add_argument("--as", dest="name", default=None, help="name it differently in traces/")
    parser.add_argument(
        "--dest-root",
        dest="dest_root",
        type=Path,
        default=None,
        help="override destination root directory (defaults to traces/)",
    )
    parser.add_argument(
        "--allow-error-run",
        action="store_true",
        help="promote even when every result errored (the error is the evidence)",
    )
    args = parser.parse_args(argv)

    try:
        destination = promote(
            args.source,
            args.name,
            destination_root=args.dest_root,
            allow_error_run=args.allow_error_run,
        )
    except PromotionRefused as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return 1

    try:
        display_path = str(destination.relative_to(REPO))
    except ValueError:
        display_path = str(destination)
    print(f"promoted -> {display_path}")
    print("Cite this path from evidence/02-bakeoff.md; it is tracked, traces/raw/ is not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
