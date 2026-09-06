#!/usr/bin/env python3
"""Refuse to publish evidence that still contains a credential.

Runbook step 3.4: "run the repo's secret-scanning pass over anything you plan
to export." This is that pass, and it deliberately reuses
`guards.SECRET_PATTERNS` rather than keeping a second list -- two definitions
of "what a secret looks like" drift, and the one that drifts is always the one
in the script nobody reads.

Scans `evidence/` and `traces/` by default. Exits nonzero on any hit, so it
can sit in a pre-commit hook or in CI without further wiring.

Positional targets are resolved against the repository root, so a relative
name means "in this repo" and an absolute path means exactly itself -- you can
point the gate at a staging directory outside the tree before exporting it.

    python3 scripts/scan_evidence.py
    python3 scripts/scan_evidence.py evidence traces/raw
    python3 scripts/scan_evidence.py /tmp/export-for-review
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mcp_server" / "src"))

from foundry_spike_mcp.guards import SECRET_PATTERNS  # noqa: E402

#: Scanned by default. `snippets/` is where step 4.5 parks a generated adapter
#: (View Snippet output can embed a token), and `configs/` is where a real
#: OpenSpec proposal gets pasted into a fixture. An earlier revision documented
#: those as caveats in a README instead of scanning them -- a gate with a
#: written-down hole is not a gate.
DEFAULT_TARGETS = ("evidence", "traces", "snippets", "configs", "decisions")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".webp"}
MAX_BYTES = 16 * 1024 * 1024


def display(path: Path) -> str:
    """Render a path for the operator: relative inside the repo, absolute outside.

    `Path.relative_to` raises for a path that is not under `REPO`, and this
    script advertises positional targets. Pointing the gate at a staging
    directory before exporting it -- the one use that most needs a gate -- ended
    in a traceback rather than a scan.
    """
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    try:
        if path.stat().st_size > MAX_BYTES:
            return [(0, "oversize", f"{path.stat().st_size} bytes -- not scanned, review by hand")]
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [(0, "binary", "not scanned as text -- review by hand before exporting")]
    except OSError as error:
        return [(0, "unreadable", str(error))]

    hits: list[tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule in SECRET_PATTERNS:
            if rule.pattern.search(line):
                # Report the shape and the location, never the value.
                #
                # `rule.kind`, not a string scraped out of the replacement. The
                # category used to be derived by stripping `[REDACTED:...]` off
                # the replacement text, which held only while every replacement
                # was a bare marker. The rules that keep context -- the ones
                # replacing with `\1: [REDACTED]` so a redacted header still
                # names its header -- printed as the literal `\1: [REDACTED`.
                hits.append((number, rule.kind, rule.pattern.pattern[:48]))
    return hits


def main(argv: list[str]) -> int:
    targets = [REPO / name for name in (argv or DEFAULT_TARGETS)]
    findings = 0
    scanned = 0

    for target in targets:
        if not target.exists():
            print(f"skip  {display(target)} (does not exist)")
            continue
        paths = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
        for path in paths:
            if path.suffix.lower() in SKIP_SUFFIXES or ".git" in path.parts:
                continue
            scanned += 1
            for number, kind, pattern in scan_file(path):
                findings += 1
                where = f"{display(path)}:{number}" if number else display(path)
                print(f"HIT   {where}  [{kind}]  /{pattern}/")

    print(f"\nscanned {scanned} file(s), {findings} hit(s)")
    if findings:
        print("Redact these before committing. Nothing here should reach a PR.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
