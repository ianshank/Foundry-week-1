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

#: How much of a matching rule's regex is echoed beside a hit. Named rather
#: than left as a bare slice, following `config.CONFIG_ERROR_DETAIL_LIMIT`'s
#: precedent: deliberately not configurable -- it is display width, and an
#: operator who wants the whole pattern can read `guards.SECRET_PATTERNS`.
PATTERN_PREVIEW_CHARS = 48

#: `main` returns this when it could not look, as distinct from 1, which means
#: it looked and found a credential. Same three-valued shape as the probe CLI
#: and as planlint itself: 0 clean, 1 findings, 2 could not look. A gate that
#: spells "found nothing" and "opened nothing" with the same byte is the
#: failure this repository exists to detect.
EXIT_COULD_NOT_LOOK = 2


def display(path: Path) -> str:
    """Render a path for the operator: relative inside the repo, absolute outside.

    `Path.relative_to` raises for a path that is not under `REPO`, and this
    script advertises positional targets. Pointing the gate at a staging
    directory before exporting it -- the one use that most needs a gate -- ended
    in a traceback rather than a scan.

    Resolved first, because `relative_to` compares *syntax*. Without this,
    `REPO / "../outside"` printed as `../outside` and `traces/../../etc` printed
    as though it sat under the repo -- so "inside or outside" depended on how
    the target was spelled rather than on where it actually is. An operator
    reading this output is deciding whether an export is clean; the one thing
    it must not do is misreport where a hit was found.

    Resolution itself can fail -- a NUL byte in an argument raises `ValueError`,
    a symlink loop `OSError` -- and a gate that crashes is a gate that gets
    skipped, so an unresolvable path falls back to what the caller passed.
    """
    try:
        resolved = path.resolve()
    except (ValueError, OSError):
        return str(path)
    try:
        return str(resolved.relative_to(REPO))
    except ValueError:
        return str(resolved)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    try:
        if path.stat().st_size > MAX_BYTES:
            return [(0, "oversize", f"{path.stat().st_size} bytes -- not scanned, review by hand")]
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [(0, "binary", "not scanned as text -- review by hand before exporting")]
    except OSError as error:
        return [(0, "unreadable", str(error))]

    # Matched against the whole text, not line by line.
    #
    # `SECRET_PATTERNS` contains rules that span newlines by construction: the
    # PEM block is `-----BEGIN...-----[\s\S]*?-----END...-----`, and the
    # authorization rule uses `\s+` specifically so a header whose credential
    # wrapped onto the next line is still caught -- `guards.py` records that
    # second one as a fixed defect. Splitting the text before matching made
    # every such rule dead on arrival here, so `redact()` (which scans whole
    # text) and `scan_file()` disagreed about what a secret is. A PEM private
    # key in a capture scanned clean and `promote_trace` copied it into
    # tracked `traces/`, in a public repository.
    #
    # The line number is recovered from the match offset rather than from a
    # loop counter, because it is how a reviewer finds the thing to redact.
    hits: list[tuple[int, str, str]] = []
    for rule in SECRET_PATTERNS:
        for match in rule.pattern.finditer(text):
            # Report the shape and the location, never the value.
            #
            # `rule.kind`, not a string scraped out of the replacement. The
            # category used to be derived by stripping `[REDACTED:...]` off
            # the replacement text, which held only while every replacement
            # was a bare marker. The rules that keep context -- the ones
            # replacing with `\1: [REDACTED]` so a redacted header still
            # names its header -- printed as the literal `\1: [REDACTED`.
            number = text.count("\n", 0, match.start()) + 1
            hits.append((number, rule.kind, rule.pattern.pattern[:PATTERN_PREVIEW_CHARS]))
    return sorted(hits)


def _resolve_target(name: str) -> Path:
    """A relative name means "in this repo"; an absolute path means itself.

    `REPO / name` alone does not deliver the second half of that promise on
    Windows: a drive-less rooted path like `/tmp/export-for-review` -- the
    example this module's own docstring gives -- keeps the repository's drive
    letter and becomes `E:\\tmp\\export-for-review`. The gate then scanned a
    path the operator never named, found it absent, and (before the exit-code
    fix below) reported success.
    """
    candidate = Path(name)
    return candidate if candidate.is_absolute() else REPO / name


def main(argv: list[str]) -> int:
    targets = [_resolve_target(name) for name in (argv or DEFAULT_TARGETS)]
    findings = 0
    scanned = 0
    missing = 0

    for target in targets:
        if not target.exists():
            print(f"skip  {display(target)} (does not exist)")
            missing += 1
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
    if scanned == 0 and missing:
        # Looked at nothing, and was asked to look somewhere that is not there.
        #
        # `make scan`, `make secrets`, the pre-commit hook and `promote_trace`
        # all gate on this exit code. A shallow checkout, a renamed directory
        # or a typo'd target used to print "scanned 0 file(s), 0 hit(s)" and
        # exit 0 -- a green credential gate that had opened nothing.
        #
        # Guarded on `missing` as well as `scanned` so that a genuinely empty
        # but present directory still passes: having looked and found nothing
        # is success, and a gate nobody can satisfy is a gate everybody
        # bypasses.
        print(
            f"{missing} requested target(s) did not exist and nothing was scanned. "
            "This is not a pass -- fix the path or the checkout."
        )
        return EXIT_COULD_NOT_LOOK
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
