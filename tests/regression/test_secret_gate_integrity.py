r"""Regression guards: the secret gate must not report clean on what it did not read.

`scripts/scan_evidence.py` is the credential pass that `make scan`, `make
secrets`, the pre-commit hook and `promote_trace` all gate on. Three defects
made it report success over work it had not done -- which is the failure mode
this whole repository exists to detect, sitting inside the gate that detects it.

* S-01 -- `main` counted hits and never counted files, so a missing or
  misspelled target printed "scanned 0 file(s), 0 hit(s)" and exited 0.
* S-02 -- `scan_file` matched each rule against one line at a time, so
  `SECRET_PATTERNS`' multi-line rules -- the PEM private-key block, and a
  wrapped `Authorization:` header whose credential sits on the next line --
  could never fire. A PEM key in a capture scanned clean and `promote_trace`
  copied it into tracked `traces/`, in a public repository.
* S-03 -- targets were joined as `REPO / name`, and on Windows a drive-less
  absolute path like `/tmp/export` grafts onto the repo's drive, so the gate
  scanned `E:\tmp\export` and reported the nonexistent path as skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from promote_trace import PromotionRefused
from scan_evidence import main, scan_file

pytestmark = pytest.mark.regression

_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEabcdef0123456789ABCDEF\n"
    "-----END RSA PRIVATE KEY-----\n"
)


def test_a_pem_private_key_is_a_hit(tmp_path: Path) -> None:
    r"""S-02: the rule spans newlines, so a per-line scan could never match it.

    `guards.SECRET_PATTERNS` defines the private-key rule with `[\s\S]*?`
    between BEGIN and END precisely so it spans lines. Splitting the text
    before matching made that rule dead on arrival -- and `redact()`, which
    scans whole text, caught it, so the two consumers of one pattern list
    disagreed about what a secret is.
    """
    target = tmp_path / "transcript.md"
    target.write_text(_PEM, encoding="utf-8")

    kinds = [kind for _line, kind, _pattern in scan_file(target)]

    assert "private-key" in kinds, f"a PEM block scanned clean; kinds={kinds}"


def test_a_wrapped_authorization_header_is_a_hit(tmp_path: Path) -> None:
    r"""S-02, second rule: the credential on the line after the header name.

    `guards.py` documents this as a fixed defect -- the rule uses `\s+` so a
    wrapped header is still caught. Line-splitting reintroduced it for every
    caller of `scan_file`.
    """
    target = tmp_path / "capture.txt"
    target.write_text("Authorization:\n   Bearer abcdef0123456789abcdef\n", encoding="utf-8")

    kinds = [kind for _line, kind, _pattern in scan_file(target)]

    assert kinds, "a wrapped Authorization header scanned clean"


def test_a_hit_reports_the_line_it_was_found_on(tmp_path: Path) -> None:
    """Whole-text matching must not cost the operator the line number.

    The line number is how a reviewer finds the thing to redact. Moving from a
    per-line loop to whole-text matching is only safe if the offset is
    translated back into a line.
    """
    target = tmp_path / "notes.md"
    target.write_text("clean line\nanother clean line\n" + _PEM, encoding="utf-8")

    hits = [(line, kind) for line, kind, _pattern in scan_file(target) if kind == "private-key"]

    assert hits, "no private-key hit to locate"
    assert hits[0][0] == 3, f"expected the PEM to start on line 3, got {hits[0][0]}"


def test_scanning_nothing_is_not_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """S-01: a gate that looked at no files must not report clean.

    `make scan` and `make secrets` gate on this exit code. A shallow checkout,
    a renamed directory or a typo'd target produced a green credential gate
    that had opened nothing -- reporting a non-result as a pass, in the
    repository written to catch exactly that.

    Exit 2, not 1: 1 means "found a credential" and 2 means "could not look",
    matching the three-valued exit the probe CLI already uses for the same
    distinction.
    """
    code = main([str(tmp_path / "definitely-not-here")])

    assert code == 2, "a scan that opened zero files exited as though it had passed"
    assert "scanned 0 file(s)" in capsys.readouterr().out


def test_a_clean_directory_with_files_still_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other side of S-01: having looked and found nothing is success.

    Without this, the fix above could be 'always exit nonzero', which is a
    gate nobody can satisfy and therefore a gate everybody bypasses.
    """
    (tmp_path / "notes.md").write_text("nothing secret here\n", encoding="utf-8")

    code = main([str(tmp_path)])

    assert code == 0
    assert "scanned 1 file(s), 0 hit(s)" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "win32", reason="drive-letter grafting is Windows-only")
def test_a_rooted_absolute_target_is_not_grafted_onto_the_repo_drive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    r"""S-03: `REPO / "/tmp/x"` keeps the repo's drive letter on Windows.

    The module docstring promises "an absolute path means exactly itself" and
    offers `/tmp/export-for-review` as the example. On Windows that became
    `E:\tmp\export-for-review` -- a different path, on the repo's drive,
    which does not exist -- so the gate skipped it and (before S-01) exited 0.
    """
    rooted = "/" + "no-such-dir-for-the-graft-guard"
    code = main([rooted])

    out = capsys.readouterr().out
    assert code == 2
    assert "Coding_Projects" not in out, f"target was grafted onto the repo drive: {out}"


def test_a_skip_name_in_an_ancestor_directory_does_not_skip_the_scan(tmp_path: Path) -> None:
    """S-04: `SKIP_NAMES` was matched against the absolute path.

    `promote` skipped any file whose *absolute* path contained a component in
    `SKIP_NAMES`, so a capture whose ancestor directory happened to be named
    `__pycache__` had every file skipped by the credential scan -- while
    `shutil.copytree`'s `ignore_patterns` matches per-directory basenames and
    copied them anyway. Reproduced: an unscanned `ghp_` token was promoted into
    the tracked destination and the tool printed success.

    The comparison must be scoped to the capture, which is the only part of the
    path the capture controls.
    """
    from promote_trace import promote

    base = tmp_path / "__pycache__" / "out"
    capture = base / "run1"
    capture.mkdir(parents=True)
    (capture / "transcript.txt").write_text("token ghp_" + "D" * 36 + "\n", encoding="utf-8")

    with pytest.raises(PromotionRefused, match="secret scan"):
        promote(capture, destination_root=tmp_path / "traces")


def test_a_skip_name_inside_the_capture_is_skipped_and_not_copied(tmp_path: Path) -> None:
    """The other direction, and the one that keeps the fix honest.

    The test above proves a `__pycache__` *ancestor* no longer suppresses the
    scan. On its own that is passable by deleting `SKIP_NAMES` altogether --
    which would then make the scan loop and `shutil.copytree`'s
    `ignore_patterns` disagree in the opposite direction, refusing promotion
    over a compiled artefact nobody wrote.

    So both halves have to hold at once: a skip name *inside* the capture is
    genuinely skipped by the scan, and is genuinely absent from what lands in
    tracked `traces/`. The second assertion is the one that matters -- the
    original defect lived precisely in the scan loop and the copy filter having
    different opinions about the same path.
    """
    from promote_trace import promote

    capture = tmp_path / "run2"
    (capture / "__pycache__").mkdir(parents=True)
    (capture / "__pycache__" / "cached.txt").write_text(
        "token ghp_" + "E" * 36 + "\n", encoding="utf-8"
    )
    (capture / "transcript.txt").write_text("nothing sensitive here\n", encoding="utf-8")

    destination = promote(capture, destination_root=tmp_path / "traces")

    assert destination.is_dir()
    assert (destination / "transcript.txt").is_file(), "the real capture content was not copied"
    assert not (destination / "__pycache__").exists(), (
        "the scan skipped __pycache__ but the copy brought it along -- the two "
        "halves disagree, which is exactly how the original defect worked"
    )


def test_an_unreadable_summary_does_not_block_promotion(tmp_path: Path) -> None:
    """A gate must refuse what it can read as bad, not what it cannot read.

    `_no_model_answered` returns False for an absent, unreadable or
    unrecognised `summary.json`, and `promote_trace.py` says why in prose:
    manual exports are a supported input and this gate must not refuse a
    capture it simply does not understand. It refuses only what it can
    positively read as a run in which nothing was contacted.

    Nothing enforced that, so a later "harden the gate" change could flip it to
    refuse-on-unreadable and silently break every hand-made export. Note the
    asymmetry is deliberate and is *not* the pattern the rest of this repository
    follows: for a **verdict**, unreadable means BLOCKED. This is a promotion
    filter, not a verdict, and the secret scan below it is the check that
    actually protects the repository -- it runs either way.
    """
    from promote_trace import promote

    capture = tmp_path / "run3"
    capture.mkdir(parents=True)
    (capture / "summary.json").write_text("{ this is not json", encoding="utf-8")
    (capture / "transcript.txt").write_text("nothing sensitive here\n", encoding="utf-8")

    destination = promote(capture, destination_root=tmp_path / "traces")

    assert (destination / "summary.json").is_file()
    assert (destination / "transcript.txt").is_file()
