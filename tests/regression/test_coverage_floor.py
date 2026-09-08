"""Regression guard: a global coverage floor lets any one file rot to zero.

`pyproject.toml` declares `fail_under = 90` and coverage enforces it against
the TOTAL only, which leaves enough slack that several whole files could drop
to **zero** coverage with the gate still green.

No percentage is quoted here, and that is deliberate. Three files in this
repository each stated a different figure for the same measurement -- 92.90%
here, 93.65% in `ci.yml`, and 96.02% actually measured -- because a snapshot in
prose goes stale the moment anyone adds a test, and nothing checks it. The
argument does not need the number: whatever the total is, a global-only floor
cannot see any individual file, and a well-covered module silently subsidises
an abandoned one. `test_the_global_floor_leaves_room_for_a_whole_file_to_rot`
below computes the slack against the tree it is run on and fails if the premise
ever stops holding.

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


def test_the_global_floor_leaves_room_for_a_whole_file_to_rot() -> None:
    """The premise of this file, computed against the tree rather than quoted.

    A per-file floor is only worth having if the global one is loose enough to
    hide an abandoned module. That was argued in prose with a percentage that
    went stale in three separate files at once. Here it is measured: take the
    slack the global floor allows, and check it is at least as large as the
    largest single file. If it ever is not, the global gate alone would catch a
    file dropping to zero and this whole file becomes redundant -- which would
    be good news, and should be found by a failing test rather than by nobody.
    """
    if not _COVERAGE_JSON.is_file():
        pytest.skip("coverage.json not present; run `python -m coverage run -m pytest`")

    report = json.loads(_COVERAGE_JSON.read_text(encoding="utf-8"))
    _, total_units = _combined(report["totals"])
    covered_units, _ = _combined(report["totals"])

    global_floor = _declared_global_floor()
    allowed_uncovered = total_units - int(total_units * global_floor / 100)
    currently_uncovered = total_units - covered_units
    slack = allowed_uncovered - currently_uncovered

    # Not the *largest* file -- that was the first version of this assertion and
    # it was inverted. The premise is that **some** whole file fits inside the
    # slack, because that is the one the global gate would not notice being
    # abandoned. If none does, the global gate alone is sufficient.
    would_go_unnoticed = sorted(
        (name, _combined(data["summary"])[1])
        for name, data in report["files"].items()
        if _combined(data["summary"])[1] <= slack
    )

    assert would_go_unnoticed, (
        f"the global floor of {global_floor}% now leaves {slack} units of slack, "
        "and no single file is small enough to fit inside it. The global gate "
        "alone would catch any file being abandoned, so the premise this file "
        "argues from no longer holds -- check whether the per-file floor is "
        "still earning its place."
    )


def _declared_global_floor() -> float:
    """Read the global floor from `pyproject.toml` rather than restating it."""
    import re

    text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^fail_under\s*=\s*(\d+(?:\.\d+)?)\s*$", text)
    assert match, "no `fail_under` declaration found in pyproject.toml"
    return float(match.group(1))


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
