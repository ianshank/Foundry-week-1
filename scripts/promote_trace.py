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
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

try:
    from scripts.scan_evidence import scan_file
except ImportError:
    from scan_evidence import scan_file  # type: ignore[import-not-found,no-redef]

TRACES = REPO / "traces"
SKIP_NAMES = {"__pycache__", ".DS_Store"}


class PromotionRefused(RuntimeError):
    """The capture was not promoted, and the message says why."""


def promote(source: Path, name: str | None = None, destination_root: Path | None = None) -> Path:
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

    findings: list[str] = []
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        if any(part in SKIP_NAMES for part in path.parts):
            continue
        for line_number, kind, _pattern in scan_file(path):
            where = f"{path.relative_to(source)}:{line_number}" if line_number else str(path)
            findings.append(f"{where} [{kind}]")
    if findings:
        raise PromotionRefused(
            "secret scan found "
            f"{len(findings)} hit(s); not promoting:\n  " + "\n  ".join(findings[:10])
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
    args = parser.parse_args(argv)

    try:
        destination = promote(args.source, args.name, destination_root=args.dest_root)
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
