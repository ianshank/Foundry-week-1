"""Regression guards for what lands in tracked evidence.

Three defects share this file because they share a failure surface: a
`traces/` directory that a reviewer will open and a matrix cell will cite.

* D-05 -- `summary.json` recorded native path separators, so the same logical
  run diffed against itself across platforms.
* D-04 -- a run in which no model answered could be promoted into `traces/`.
* D-07 -- a UTF-8 BOM reached a tracked source file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from probe.runner import _rel
from promote_trace import PromotionRefused, promote

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


def _capture(root: Path, name: str, statuses: list[str]) -> Path:
    """A minimal capture directory shaped like one verifier_probe.py writes."""
    capture = root / name
    capture.mkdir(parents=True)
    (capture / "summary.json").write_text(
        json.dumps(
            {
                "captured": "20260907T000000Z",
                "results": [
                    {"slot": f"ollama:m{i}", "status": status, "screen": status}
                    for i, status in enumerate(statuses)
                ],
            }
        ),
        encoding="utf-8",
    )
    return capture


def test_promotion_refuses_a_run_where_no_model_answered(tmp_path: Path) -> None:
    """D-04: the secret scan is a confidentiality gate, not an evidence gate.

    Promotion used to check exactly one thing -- that no credential was in the
    transcript -- which is load-bearing and stays. But it meant `traces/` could
    hold, and `evidence/02-bakeoff.md` could cite, a run in which every slot
    errored before a request was sent.
    """
    capture = _capture(tmp_path / "raw", "20260907T000000Z-02-verifier", ["ERROR", "ERROR"])

    with pytest.raises(PromotionRefused, match="no model answered"):
        promote(capture, destination_root=tmp_path / "traces")


def test_promotion_allows_a_partial_run(tmp_path: Path) -> None:
    """One answering slot makes the capture evidence, whatever else failed."""
    capture = _capture(tmp_path / "raw", "20260907T000001Z-02-verifier", ["OK", "ERROR"])

    promoted = promote(capture, destination_root=tmp_path / "traces")

    assert promoted.is_dir()
    assert (promoted / "summary.json").is_file()


def test_promotion_allows_an_error_run_when_asked_explicitly(tmp_path: Path) -> None:
    """Sometimes the error transcript is the evidence. That has to be sayable."""
    capture = _capture(tmp_path / "raw", "20260907T000002Z-02-verifier", ["ERROR"])

    promoted = promote(capture, destination_root=tmp_path / "traces", allow_error_run=True)

    assert promoted.is_dir()


def test_promotion_still_accepts_a_capture_with_no_summary(tmp_path: Path) -> None:
    """Manual exports have no summary.json and are a supported input.

    `promote_trace.py`'s own docstring names them, so a content gate that
    assumed the file exists would refuse the case the tool was written for.
    """
    capture = tmp_path / "raw" / "manual-export"
    capture.mkdir(parents=True)
    (capture / "transcript.md").write_text("pasted by hand", encoding="utf-8")

    promoted = promote(capture, destination_root=tmp_path / "traces")

    assert (promoted / "transcript.md").is_file()


def test_unwritable_out_directory_is_an_argparse_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-06: every other bad argument in `main` reports through parser.error.

    A file where a directory belongs makes `mkdir` raise on every platform,
    which is the portable way to provoke this without needing permissions.
    """
    from probe.cli import main as probe_main

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        probe_main(["--models", "ollama:m", "--out", str(blocker)])

    assert excinfo.value.code == 2  # argparse's usage-error code
