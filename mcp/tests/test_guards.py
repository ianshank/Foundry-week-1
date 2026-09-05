"""Refusals are properties of the tool, so they are tested like properties."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from foundry_spike_mcp import guards


def test_allowed_roots_falls_back_to_target_not_to_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("PLANLINT_TARGET", str(tmp_path))
    assert guards.allowed_roots() == [tmp_path.resolve()]


def test_no_allow_list_is_a_rejection_not_a_wildcard(monkeypatch):
    monkeypatch.delenv("PLANLINT_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("PLANLINT_TARGET", raising=False)
    with pytest.raises(guards.GuardRejection):
        guards.allowed_roots()


def test_relative_allowed_root_is_rejected(monkeypatch):
    monkeypatch.setenv("PLANLINT_ALLOWED_ROOTS", "./specs")
    with pytest.raises(guards.GuardRejection):
        guards.allowed_roots()


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
    guards.assert_safe_argv(["planlint", "--target", "/tmp/x", verb])


@pytest.mark.parametrize("verb", ["init", "new", "witness", "make", "fix"])
def test_write_verbs_are_refused(verb):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv(["planlint", "--target", "/tmp/x", verb])
    assert caught.value.reason == "verb_not_allowed"


@pytest.mark.parametrize("flag", ["--force", "--fix", "--write", "--overwrite", "--force=true"])
def test_mutating_flags_are_refused(flag):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv(["planlint", "--target", "/tmp/x", "validate", flag])
    assert caught.value.reason == "denied_flag"


def test_option_values_are_not_mistaken_for_the_verb():
    """`--target /some/path validate` must find `validate`, not `/some/path`."""
    guards.assert_safe_argv(
        ["planlint", "--target", "/srv/specs", "validate", "--fail-on", "ERROR", "--json"]
    )


def test_fail_on_vocabulary_is_closed():
    assert guards.check_fail_on("error") == "ERROR"
    with pytest.raises(guards.GuardRejection):
        guards.check_fail_on("$(whoami)")


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
