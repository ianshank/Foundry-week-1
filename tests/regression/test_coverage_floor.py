"""Regression guard: a global coverage floor lets any one file rot to zero.

`pyproject.toml` declares `fail_under = 90` and coverage enforces it against
the TOTAL only. Measured on this tree: 92.90% combined, which leaves 48
uncovered units of headroom -- enough that several whole files could drop to
**zero** coverage with the gate still green. Computed, not guessed:

    mcp_server/src/foundry_spike_mcp/server.py   40 units
    scripts/probe/config.py                      37 units
    scripts/verifier_probe.py                    36 units
    mcp_server/src/foundry_spike_mcp/verdicts.py 29 units

`server.py` is the file whose "a server that could not import, under a green
tick" failure `ci.yml` explicitly says the transport job exists to catch. The
comment there is right about the SDK install and wrong about the arithmetic: a
gate that cannot see the thing it guards is decoration, and a global-only
floor cannot see any individual file.

This is the standard remedy -- a per-file threshold alongside the aggregate,
so a well-covered module cannot subsidise an abandoned one. It reads
`coverage.json`, which only exists after a coverage run, and skips when it is
absent rather than failing: CI's `contract` job installs pytest and nothing
else, and a guard that turns an unrelated job red teaches people to delete it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

_REPO = Path(__file__).resolve().parents[2]
_COVERAGE_JSON = _REPO / "coverage.json"

#: Per-file floor. Deliberately below the global 90 rather than equal to it:
#: the aggregate is the target, and this exists to catch a file being
#: *abandoned*, not to force every module to the same number. Raising it to 90
#: would make the two gates redundant and would fail on files that are
#: legitimately hard to reach from a unit test.
MINIMUM_PER_FILE = 80.0

#: Files allowed below the floor, each with the reason it cannot reach it.
#: A dict rather than a set so the exemption has to be justified in the diff.
#: Empty is the goal; an entry here is a debt, not a decision.
ALLOWED_BELOW: dict[str, str] = {}


def _combined(summary: dict[str, int]) -> tuple[int, int]:
    """Statements and branches together, matching how the floor is measured."""
    covered = summary["covered_lines"] + summary.get("covered_branches", 0)
    total = summary["num_statements"] + summary.get("num_branches", 0)
    return covered, total


def test_no_measured_file_falls_below_the_per_file_floor() -> None:
    """Every file the coverage run measured clears `MINIMUM_PER_FILE`."""
    if not _COVERAGE_JSON.is_file():
        pytest.skip(
            "coverage.json not present; run `python -m coverage run -m pytest && "
            "python -m coverage json` (or `make coverage`) to enforce the per-file floor"
        )

    report = json.loads(_COVERAGE_JSON.read_text(encoding="utf-8"))

    offenders = []
    for path, measured in sorted(report["files"].items()):
        covered, total = _combined(measured["summary"])
        if total == 0:
            continue
        percent = 100.0 * covered / total
        normalised = path.replace("\\", "/")
        if percent < MINIMUM_PER_FILE and normalised not in ALLOWED_BELOW:
            offenders.append(f"{normalised} at {percent:.1f}% ({covered}/{total})")

    assert not offenders, (
        f"these files are below the {MINIMUM_PER_FILE:.0f}% per-file floor, which a "
        "global floor cannot see because better-covered files subsidise them:\n  "
        + "\n  ".join(offenders)
    )


def test_every_exemption_names_a_file_that_still_exists_and_still_needs_it() -> None:
    """An exemption for a deleted or since-fixed file is a hole nobody closed."""
    if not _COVERAGE_JSON.is_file():
        pytest.skip("coverage.json not present")

    report = json.loads(_COVERAGE_JSON.read_text(encoding="utf-8"))
    measured = {p.replace("\\", "/"): m for p, m in report["files"].items()}

    for path, reason in ALLOWED_BELOW.items():
        assert reason.strip(), f"{path} is exempted with no reason"
        assert path in measured, f"{path} is exempted but no longer measured"
        covered, total = _combined(measured[path]["summary"])
        percent = 100.0 * covered / total if total else 100.0
        assert percent < MINIMUM_PER_FILE, (
            f"{path} is exempted but now reaches {percent:.1f}% -- remove the exemption"
        )
