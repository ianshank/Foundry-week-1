"""Regression guards for what lands in tracked evidence.

Three defects share this file because they share a failure surface: a
`traces/` directory that a reviewer will open and a matrix cell will cite.

* D-05 -- `summary.json` recorded native path separators, so the same logical
  run diffed against itself across platforms.
* D-04 -- a run in which no model answered could be promoted into `traces/`.
* D-07 -- a UTF-8 BOM reached a tracked source file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probe.runner import _rel

pytestmark = pytest.mark.regression


def test_rel_uses_posix_separators_for_a_repo_relative_path() -> None:
    """D-05: evidence paths are POSIX on every platform.

    `str(Path)` is native, so a Windows capture wrote
    `configs\\probes\\02-verifier.md` where Linux wrote
    `configs/probes/02-verifier.md`. Tracked artifacts have to be
    byte-identical for the same run or the diff is noise.
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = _rel(repo_root / "configs" / "probes" / "02-verifier.md")

    assert result == "configs/probes/02-verifier.md"
    assert "\\" not in result


def test_rel_uses_posix_separators_for_a_path_outside_the_repo(tmp_path: Path) -> None:
    """The absolute fallback is normalised too, or the guard has a hole.

    A Windows absolute path keeps its drive letter -- that is unavoidable and
    correct -- but the separators between segments are still ours to fix.
    """
    outside = tmp_path / "somewhere" / "else.md"
    result = _rel(outside)

    assert "\\" not in result
    assert result.endswith("somewhere/else.md")
