"""Regression guards for what lands in tracked evidence.

Three defects share this file because they share a failure surface: a
`traces/` directory that a reviewer will open and a matrix cell will cite.

* D-05 -- `summary.json` recorded native path separators, so the same logical
  run diffed against itself across platforms.
* D-04 -- a run in which no model answered could be promoted into `traces/`.
* D-07 -- a UTF-8 BOM reached a tracked source file.
"""

from __future__ import annotations

import codecs
import json
import subprocess
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


#: Every byte-order mark a text editor can leave at byte 0, longest first.
#:
#: This guard compared `BOM_UTF8` alone for two merges, which meant the one
#: tracked file in this repository that actually carried a BOM --
#: `requirements.txt`, a Windows `pip freeze` written in UTF-16LE -- walked
#: straight past a check whose entire purpose was to catch it. A guard that
#: enumerates one member of a family and calls itself repo-wide is the same
#: shape of defect as the extension whitelist this test's docstring already
#: warns about, one level further in.
#:
#: Longest-first matters for the *message*, not the match: `BOM_UTF32_LE`
#: begins with `BOM_UTF16_LE`, so a shortest-first scan would report every
#: UTF-32LE file as UTF-16LE and send the reader to the wrong encoding.
_BOMS: tuple[tuple[str, bytes], ...] = (
    ("UTF-32LE", codecs.BOM_UTF32_LE),
    ("UTF-32BE", codecs.BOM_UTF32_BE),
    ("UTF-8", codecs.BOM_UTF8),
    ("UTF-16LE", codecs.BOM_UTF16_LE),
    ("UTF-16BE", codecs.BOM_UTF16_BE),
)


def test_no_tracked_text_file_starts_with_any_byte_order_mark() -> None:
    """D-07: a BOM at byte 0 breaks tools that read bytes.

    `tests/integration/test_mcp_integration.py` carried one and it was removed
    in a4d3f22. Nothing stopped the next editor putting one back, in that file
    or any other -- Windows editors add them silently.

    Discovered via `git ls-files` with **no pathspec** -- not filtered to
    `*.py`/`*.md`/etc. -- because an extension whitelist is exactly the kind
    of hand-maintained list this guard exists to avoid, and this repository
    already tracks extensionless files an extension filter would silently
    skip: `Makefile` and `.github/CODEOWNERS` both matched no pattern in an
    earlier draft of this test, which would have made a BOM in either of them
    invisible to a guard whose whole stated purpose is repo-wide coverage.

    It checks every BOM rather than UTF-8's alone for the same reason, and
    that widening is what first caught `requirements.txt`.
    """
    repo_root = Path(__file__).resolve().parents[2]
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root, capture_output=True, check=True,
    )
    paths = [p for p in listed.stdout.decode("utf-8").split("\0") if p]
    assert paths, "git ls-files matched nothing -- discovery is broken, not the repo clean"

    offenders = []
    for rel in paths:
        full = repo_root / rel
        if not full.is_file():
            continue
        try:
            head = full.read_bytes()[:4]
        except OSError:
            continue
        for label, bom in _BOMS:
            if head.startswith(bom):
                offenders.append(f"{rel} ({label})")
                break

    assert not offenders, (
        "These tracked files start with a byte-order mark: " + ", ".join(sorted(offenders)) +
        ". Re-save them as UTF-8 without a signature."
    )
