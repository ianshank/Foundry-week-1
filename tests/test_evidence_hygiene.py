"""The secret gate and the promotion step, both of which were untested.

Review finding #6. The previous revision argued that "an untested grader is
worse than no grader" while shipping an untested secret scanner -- a gate whose
only evidence of working was that it had never been seen to fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promote_trace import PromotionRefused, promote
from scan_evidence import DEFAULT_TARGETS, scan_file

LEAKS = [
    ("github token", "ghp_abcdefghijklmnopqrstuvwxyz012345"),
    ("github pat", "github_pat_11ABCDEFG0abcdefghijklmnop"),
    ("api key", "sk-abcdefghijklmnopqrstuvwx"),
    ("aws key id", "AKIAIOSFODNN7EXAMPLE"),
    ("slack token", "xoxb-1234567890-abcdefghijkl"),
    ("bearer header", "Authorization: Bearer abcdef123456"),
    ("assignment", "GITHUB_TOKEN=hunter2secretvalue"),
]


@pytest.mark.parametrize(("label", "secret"), LEAKS, ids=[label for label, _ in LEAKS])
def test_scanner_catches_each_credential_shape(tmp_path, label, secret):
    path = tmp_path / "capture.txt"
    path.write_text(f"line one\n{secret}\nline three\n", encoding="utf-8")
    hits = scan_file(path)
    assert hits, f"{label} was not caught"
    assert hits[0][0] == 2, "the hit should report the line it was found on"


def test_scanner_reports_location_and_shape_never_the_value(tmp_path):
    """A scanner that echoes the secret into CI logs has moved the leak."""
    secret = "ghp_abcdefghijklmnopqrstuvwxyz012345"
    path = tmp_path / "capture.txt"
    path.write_text(secret, encoding="utf-8")
    for _line, kind, pattern in scan_file(path):
        assert secret not in kind
        assert secret not in pattern


def test_scanner_leaves_evidence_alone(tmp_path):
    """Rule ids, git SHAs and exit codes are the evidence, not secrets."""
    path = tmp_path / "clean.md"
    path.write_text(
        "SPEC012 ERROR at 4f2a9c1b8e7d6a5f4c3b2a1908f7e6d5c4b3a291\nexit=1\n",
        encoding="utf-8",
    )
    assert scan_file(path) == []


def test_binary_files_are_flagged_for_review_not_silently_passed(tmp_path):
    path = tmp_path / "screenshot.bin"
    path.write_bytes(b"\x00\x01\x02\xff\xfe")
    hits = scan_file(path)
    assert hits and hits[0][1] == "binary"


def test_default_targets_cover_every_directory_that_can_hold_a_capture():
    """`snippets/` holds generated adapter code and `configs/` holds pasted
    proposals. An earlier revision documented those as caveats instead of
    scanning them -- a gate with a written-down hole is not a gate."""
    assert {"evidence", "traces", "snippets", "configs"} <= set(DEFAULT_TARGETS)


# --------------------------------------------------------------------------
# Promotion: raw captures are gitignored, tracked traces are cited by evidence.
# The scan is what stands between the two.
# --------------------------------------------------------------------------


def _capture(tmp_path: Path, body: str) -> Path:
    source = tmp_path / "raw" / "run-1"
    source.mkdir(parents=True)
    (source / "summary.json").write_text(json.dumps({"screen": "HELD"}), encoding="utf-8")
    (source / "model.json").write_text(body, encoding="utf-8")
    return source


def test_a_clean_capture_is_promoted(tmp_path):
    source = _capture(tmp_path, '{"text": "VERDICT: FINDINGS"}')
    destination = promote(source, destination_root=tmp_path / "traces")
    assert (destination / "summary.json").is_file()
    assert (destination / "model.json").is_file()


def test_a_capture_with_a_credential_is_refused(tmp_path):
    """The moment a transcript becomes tracked it is one push from public."""
    source = _capture(tmp_path, '{"error": "ghp_abcdefghijklmnopqrstuvwxyz012345"}')
    with pytest.raises(PromotionRefused) as caught:
        promote(source, destination_root=tmp_path / "traces")
    assert "secret scan" in str(caught.value)
    assert not (tmp_path / "traces" / "run-1").exists(), "nothing may be copied on refusal"


def test_promotion_will_not_overwrite_an_existing_trace(tmp_path):
    """Overwriting a promoted trace silently rewrites evidence a verdict cites."""
    source = _capture(tmp_path, "{}")
    root = tmp_path / "traces"
    promote(source, destination_root=root)
    with pytest.raises(PromotionRefused) as caught:
        promote(source, destination_root=root)
    assert "already exists" in str(caught.value)


def test_promotion_accepts_an_explicit_name(tmp_path):
    source = _capture(tmp_path, "{}")
    destination = promote(source, name="session-2-verifier", destination_root=tmp_path / "traces")
    assert destination.name == "session-2-verifier"


def test_a_missing_source_is_refused_not_a_traceback(tmp_path):
    with pytest.raises(PromotionRefused):
        promote(tmp_path / "nope", destination_root=tmp_path / "traces")


# --------------------------------------------------------------------------
# The gitleaks allowlist. It exists so the redaction patterns and their test
# vectors do not trip history scanning -- and it is exactly the kind of file
# that grows an entry during a rushed debugging session and never loses it.
# --------------------------------------------------------------------------


def _load_gitleaks_config():
    try:
        import tomllib
    except ImportError:  # Python 3.10
        tomllib = pytest.importorskip("tomli", reason="no TOML parser on this interpreter")
    return tomllib.loads((Path(__file__).resolve().parents[1] / ".gitleaks.toml").read_text())


def test_capture_directories_are_never_allowlisted():
    """`traces/`, `evidence/`, `snippets/` and `configs/` are where a real
    transcript, a generated adapter or a pasted proposal lands. If gitleaks
    fires there it is doing its job, and an allowlist entry rooted at one of
    them would switch that off wholesale."""
    config = _load_gitleaks_config()
    rooted_at_a_capture_dir = [
        pattern
        for pattern in config["allowlist"]["paths"]
        # Anchored at the start: `tests/test_evidence_hygiene.py` legitimately
        # contains the word "evidence" and is not a capture directory.
        if pattern.lstrip("^'\"").startswith(("traces/", "evidence/", "snippets/", "configs/"))
    ]
    assert not rooted_at_a_capture_dir, rooted_at_a_capture_dir


def test_every_allowlisted_path_still_exists():
    """An allowlist entry for a file that has moved silently stops protecting
    the file and silently keeps excusing whatever now matches the pattern."""
    import re

    config = _load_gitleaks_config()
    repo = Path(__file__).resolve().parents[1]
    for pattern in config["allowlist"]["paths"]:
        compiled = re.compile(pattern)
        matched = any(
            compiled.search(str(p.relative_to(repo)))
            for p in repo.rglob("*")
            if p.is_file() and ".git/" not in str(p)
        )
        assert matched, f"gitleaks allowlist pattern matches nothing: {pattern}"


def test_the_default_ruleset_is_extended_not_replaced():
    config = _load_gitleaks_config()
    assert config["extend"]["useDefault"] is True
