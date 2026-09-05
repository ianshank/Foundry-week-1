"""Refusals are properties of the tool, so they are tested like properties."""

from __future__ import annotations

import sys

import pytest

from foundry_spike_mcp import guards

#: A stand-in target for argv-shape assertions. Never opened, never created --
#: `assert_safe_argv` inspects tokens and does not touch the filesystem. Not
#: under /tmp, so it cannot collide with a real world-writable path.
ARGV_TARGET = "/srv/specs/example"

# Allow-list construction moved to `config.py` -- see test_config.py. What
# stays here is the containment decision itself, which is the security-relevant
# half and has nothing to do with where the roots came from.


def test_an_empty_allow_list_is_a_rejection_not_a_wildcard(tmp_path):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target(str(tmp_path), ())
    assert caught.value.reason == "no_allowed_roots"


def test_target_inside_root_is_accepted(tmp_path):
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    assert guards.check_target(str(inner), [tmp_path]) == inner.resolve()


def test_traversal_out_of_root_is_rejected(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target(str(root / ".." / "elsewhere"), [root])
    assert caught.value.reason == "target_outside_allow_list"


@pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require admin privileges on Windows")
def test_symlink_escaping_root_is_rejected(tmp_path):
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(guards.GuardRejection):
        guards.check_target(str(link), [root])


def test_relative_target_is_rejected(tmp_path):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target("../specs", [tmp_path])
    assert caught.value.reason == "relative_target"


def test_missing_directory_is_not_a_guard_violation(tmp_path):
    """A nonexistent target is planlint's exit 2 to report, not the guard's to
    pre-empt -- the BLOCKED demo depends on the call actually being made."""
    assert guards.check_target(str(tmp_path / "not-there"), [tmp_path])


@pytest.mark.parametrize("verb", sorted(guards.ALLOWED_VERBS))
def test_read_only_verbs_are_allowed(verb):
    guards.assert_safe_argv(["planlint", "--target", ARGV_TARGET, verb])


@pytest.mark.parametrize("verb", ["init", "new", "witness", "make", "fix"])
def test_write_verbs_are_refused(verb):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv(["planlint", "--target", ARGV_TARGET, verb])
    assert caught.value.reason == "verb_not_allowed"


@pytest.mark.parametrize("flag", ["--force", "--fix", "--write", "--overwrite", "--force=true"])
def test_mutating_flags_are_refused(flag):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv(["planlint", "--target", ARGV_TARGET, "validate", flag])
    assert caught.value.reason == "denied_flag"


def test_option_values_are_not_mistaken_for_the_verb():
    """`--target /some/path validate` must find `validate`, not `/some/path`."""
    guards.assert_safe_argv(
        ["planlint", "--target", "/srv/specs", "validate", "--fail-on", "ERROR", "--json"]
    )


def test_fail_on_vocabulary_is_closed():
    vocabulary = ("ERROR", "WARN")
    assert guards.check_fail_on("error", vocabulary) == "ERROR"
    with pytest.raises(guards.GuardRejection):
        guards.check_fail_on("$(whoami)", vocabulary)
    with pytest.raises(guards.GuardRejection):
        guards.check_fail_on("INFO", vocabulary)  # not in *this build's* vocabulary


@pytest.mark.parametrize("verb", sorted(guards.REFUSED_VERBS))
def test_refused_verbs_are_named_not_merely_omitted(verb):
    """Listing them makes the refusal greppable and testable, rather than an
    absence someone could widen without noticing."""
    with pytest.raises(guards.GuardRejection):
        guards.check_verb(verb)


def test_every_allowed_verb_is_reachable_through_run_verb():
    """Finding #9: the list used to advertise six verbs while only `validate`
    could ever execute. Dead config reads as capability."""
    from foundry_spike_mcp import planlint

    for verb in guards.ALLOWED_VERBS:
        result = planlint.run_verb(verb, target="/nonexistent-root/x")
        # Refused for the *target*, never for the verb -- which proves the verb
        # itself got through.
        assert result["blocked_reason"] == "guard_rejected"
        assert "verb_not_allowed" not in str(result["blocked_detail"])


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_abcdefghijklmnopqrstuvwxyz012345",
        "github_pat_11ABCDEFG0abcdefghijklmnop",
        "sk-abcdefghijklmnopqrstuvwx",
        "AKIAIOSFODNN7EXAMPLE",
        "xoxb-1234567890-abcdefghijkl",
    ],
)
def test_credential_shapes_are_redacted(secret):
    assert secret not in guards.redact(f"leaked: {secret} end")


def test_redaction_leaves_evidence_intact():
    """A git SHA and a rule ID are the evidence, not a secret."""
    text = "SPEC001 failed at 4f2a9c1b8e7d6a5f4c3b2a1908f7e6d5c4b3a291"
    assert guards.redact(text) == text


def test_env_assignment_secrets_are_redacted():
    out = guards.redact("GITHUB_TOKEN=hunter2secretvalue")
    assert "hunter2secretvalue" not in out
    assert "GITHUB_TOKEN=[REDACTED]" in out


def test_tail_keeps_the_end_and_marks_the_cut():
    out = guards.tail("a" * 100 + "IMPORTANT", 20)
    assert out.endswith("IMPORTANT")
    assert "truncated" in out


def test_clean_redacts_before_truncating(monkeypatch):
    """Truncating first can bisect a token and leave half a credential in an
    evidence file, so order is part of the contract."""
    text = "ghp_abcdefghijklmnopqrstuvwxyz012345" + "z" * 100
    out = guards.clean(text, 40)
    assert "ghp_abcdefghijklmnop" not in out


def test_the_allow_list_rejection_names_the_caller_s_own_variable():
    """Copilot review, PR #1. `check_target` is shared by `lint_openspec` and
    `score_run`, which read different variables. A rejection telling an
    operator to set the wrong one is worse than a generic message -- it sends
    them to fix something that was never the problem."""
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target("/x", (), "EVAL_ALLOWED_ROOTS (or EVAL_SINK_DIR)")
    assert "EVAL_ALLOWED_ROOTS" in caught.value.detail
    assert "PLANLINT" not in caught.value.detail


def test_each_tool_passes_its_own_hint(tmp_path):
    from foundry_spike_mcp.planlint import lint_openspec
    from foundry_spike_mcp.scoring import score_run

    assert "PLANLINT_ALLOWED_ROOTS" in str(lint_openspec(target=str(tmp_path))["blocked_detail"])
    assert "EVAL_ALLOWED_ROOTS" in str(score_run("r")["blocked_detail"])
