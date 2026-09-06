"""The secret gate and the promotion step, both of which were untested.

Review finding #6. The previous revision argued that "an untested grader is
worse than no grader" while shipping an untested secret scanner -- a gate whose
only evidence of working was that it had never been seen to fail.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from promote_trace import PromotionRefused, promote
from scan_evidence import DEFAULT_TARGETS, REPO, display, main, scan_file

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
            compiled.search(p.relative_to(repo).as_posix())
            for p in repo.rglob("*")
            if p.is_file() and ".git/" not in p.as_posix()
        )
        assert matched, f"gitleaks allowlist pattern matches nothing: {pattern}"


def test_the_default_ruleset_is_extended_not_replaced():
    config = _load_gitleaks_config()
    assert config["extend"]["useDefault"] is True


def test_no_gitleaks_pattern_uses_a_construct_re2_rejects():
    """gitleaks compiles with Go's RE2, which has no lookarounds or
    backreferences -- and it does not degrade gracefully: an unsupported
    construct **panics at config load**, so the job dies before scanning
    anything and reports as a scan failure rather than a config error.

    This test exists because `(?!user\\b)` shipped in a rule and took CI down
    exactly that way. Writing a Python-flavoured regex into a Go tool's config
    is a mistake that will recur; this makes it fail locally in milliseconds
    instead of in CI after a push.
    """
    import re

    config = _load_gitleaks_config()
    patterns: list[tuple[str, str]] = []
    for rule in config.get("rules", []):
        for key in ("regex", "path"):
            if key in rule:
                patterns.append((f"rule {rule['id']}.{key}", rule[key]))
    for key in ("paths", "regexes"):
        for index, pattern in enumerate(config.get("allowlist", {}).get(key, [])):
            patterns.append((f"allowlist.{key}[{index}]", pattern))
    assert patterns, "no patterns found to check"

    # Constructs RE2 does not implement, with the reason spelled out so a
    # failure explains itself rather than just naming a symbol.
    unsupported = {
        r"(?=": "positive lookahead",
        r"(?!": "negative lookahead",
        r"(?<=": "positive lookbehind",
        r"(?<!": "negative lookbehind",
        r"(?>": "atomic group",
    }
    backreference = re.compile(r"\\[1-9]")

    offenders = []
    for where, pattern in patterns:
        for construct, name in unsupported.items():
            if construct in pattern:
                offenders.append(f"{where}: {name} `{construct}` -- RE2 has none")
        if backreference.search(pattern):
            offenders.append(f"{where}: backreference -- RE2 has none")
    assert not offenders, "\n".join(offenders)


def test_every_gitleaks_pattern_compiles():
    """A weaker but broader check than the RE2 one: catch plain syntax errors
    too. Python's engine is a superset, so passing here is necessary, not
    sufficient -- which is why the RE2 check above exists as well."""
    import re

    config = _load_gitleaks_config()
    for rule in config.get("rules", []):
        if "regex" in rule:
            re.compile(rule["regex"])
    for key in ("paths", "regexes"):
        for pattern in config.get("allowlist", {}).get(key, []):
            re.compile(pattern)


def test_the_custom_rule_actually_matches_a_developer_path():
    """A detection rule that never fires is worse than no rule: it reads as
    coverage. These are the shapes it exists to catch."""
    import re

    config = _load_gitleaks_config()
    rule = next(r for r in config["rules"] if r["id"] == "developer-home-path")
    pattern = re.compile(rule["regex"])
    for leaky in (
        'PLANLINT_TARGET="/Users/jsmith/src/Agents"',
        "AGENTS_REPO=/home/jsmith/work/Agents",
        r'SPIKE_HOME="C:\Users\jsmith\spikes"',
        "EVAL_ALLOWED_ROOTS=/Users/jsmith/.eval-runs",
    ):
        assert pattern.search(leaky), f"missed: {leaky}"
    for portable in (
        'PLANLINT_TARGET="$HOME/src/Agents"',
        'EVAL_SINK_DIR="${AGENTS_REPO}/.eval-runs"',
        "SPIKE_HOME=./spikes",
    ):
        assert not pattern.search(portable), f"false positive: {portable}"


# --------------------------------------------------------------------------
# Scanning a directory outside the repository.
#
# The script advertises positional targets, and the use that most needs a gate
# -- checking a staging directory before exporting it -- ended in a traceback
# from `Path.relative_to`, which raises for anything not under the repo root.
# --------------------------------------------------------------------------


def test_an_absolute_path_outside_the_repo_is_shown_as_itself(tmp_path):
    assert display(tmp_path) == str(tmp_path)


def test_a_path_inside_the_repo_is_still_shown_relative():
    assert display(REPO / "evidence" / "x.md") == str(Path("evidence") / "x.md")


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param(REPO / ".." / "outside", id="parent-of-repo"),
        pytest.param(REPO / "traces" / ".." / ".." / "etc", id="climbs-back-out"),
        pytest.param(REPO / "evidence" / ".." / ".." / "elsewhere" / "x.md", id="deeper-climb"),
    ],
)
def test_a_path_that_only_looks_local_is_shown_as_where_it_really_is(spelling):
    """`relative_to` compares syntax, so a target spelled with `..` printed as
    though it sat in the repo: `REPO / "../outside"` came out as `../outside`
    and `traces/../../etc` as `traces/../../etc`, both indistinguishable from a
    real repo-relative path in the scan output.

    An operator reads this output to decide whether an export is clean. A gate
    that misreports *where* it found a credential is worse than one that misses
    it, because it sends the fix to the wrong file.
    """
    shown = display(spelling)
    assert Path(shown).is_absolute(), f"{shown!r} reads as repo-relative but resolves outside it"
    assert shown == str(spelling.resolve())


def test_display_survives_a_path_that_cannot_be_resolved():
    """Resolution is what makes the check above honest, and resolution can
    raise -- a NUL byte is a `ValueError`. A gate that crashes gets skipped, so
    an unresolvable path falls back to what the caller passed rather than
    taking the whole scan down."""
    assert display(Path("nul\x00byte")) == "nul\x00byte"


def test_a_clean_directory_outside_the_repo_scans_and_passes(tmp_path, capsys):
    (tmp_path / "notes.md").write_text("a rule id, not a secret: SPEC001\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    assert "0 hit(s)" in capsys.readouterr().out


def test_a_credential_outside_the_repo_still_fails_closed(tmp_path, capsys):
    """The gate must not become permissive just because the target moved."""
    leaky = tmp_path / "export" / "transcript.md"
    leaky.parent.mkdir()
    leaky.write_text("token ghp_abcdefghijklmnopqrstuvwxyz012345\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert str(leaky) in out
    assert "github-token" in out
    # The location and the shape, never the value.
    assert "ghp_abcdefghijklmnopqrstuvwxyz012345" not in out


def test_a_missing_absolute_target_is_skipped_not_a_traceback(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 0
    assert "does not exist" in capsys.readouterr().out


def test_relative_targets_still_resolve_against_the_repo_root(capsys):
    """Backwards compatibility: the documented invocations must not change."""
    assert main(["evidence"]) == 0
    assert "0 hit(s)" in capsys.readouterr().out


# --------------------------------------------------------------------------
# The ignore rules themselves. `mcp.json` holds real paths and, per the
# runbook, possibly a GitHub token; the rule naming it was written before the
# directory was renamed and then silently protected nothing for several commits.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    ["mcp_server/mcp.json", "mcp/mcp.json", "some/deep/dir/mcp.json"],
)
def test_a_filled_mcp_config_cannot_be_committed_from_anywhere(candidate):
    result = subprocess.run(
        ["git", "check-ignore", "-q", candidate],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{candidate} is committable. The runbook tells the operator to fill it "
        "with real paths and possibly a token."
    )


def test_the_example_config_is_still_tracked():
    """The rule must catch the filled file without hiding the template that
    tells someone how to fill it."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "mcp_server/mcp.json.example"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, "the example config must stay visible"


def test_raw_capture_directories_are_still_ignored():
    """Unchanged behaviour, asserted alongside the rule that broke: an
    unscanned transcript must not be publishable by an absent-minded add."""
    for candidate in ("traces/raw/run/x.md", "evidence/raw/x.md"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", candidate],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{candidate} is not ignored"
