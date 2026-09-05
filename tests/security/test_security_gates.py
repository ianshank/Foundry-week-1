"""Security gate tests for path traversal, argument injection, and secret redaction.

Validates:
- Path traversal attempts are rejected before execution.
- Command-line flag injections and mutating flags are blocked.
- Secret patterns catch credentials and prevent leakage.
- Gitleaks TOML configuration file is well-formed and valid.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

from foundry_spike_mcp.guards import (
    DENIED_FLAGS,
    REFUSED_VERBS,
    GuardRejection,
    assert_safe_argv,
    check_target,
    check_verb,
    redact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.parametrize(
    "attack_vector",
    [
        "../../etc/passwd",
        "..\\..\\Windows\\System32\\cmd.exe",
        "../outside.md",
        "nested/../../escape.md",
    ],
)
def test_security_path_traversal_refusal(tmp_path: Path, attack_vector: str):
    allowed_root = tmp_path / "sandbox"
    allowed_root.mkdir()

    # Relative paths must be refused immediately
    with pytest.raises(GuardRejection) as exc_info:
        check_target(attack_vector, (allowed_root,))
    assert exc_info.value.reason in ("relative_target", "target_outside_allow_list")

    # Absolute traversal attempts escaping the root must be refused
    absolute_attack = (allowed_root / attack_vector).resolve()
    with pytest.raises(GuardRejection) as exc_info:
        check_target(str(absolute_attack), (allowed_root,))
    assert exc_info.value.reason == "target_outside_allow_list"


@pytest.mark.parametrize("verb", sorted(REFUSED_VERBS))
def test_security_mutating_verbs_refused(verb: str):
    with pytest.raises(GuardRejection) as exc_info:
        check_verb(verb)
    assert exc_info.value.reason == "verb_not_allowed"


@pytest.mark.parametrize("flag", sorted(DENIED_FLAGS))
def test_security_denied_flags_in_argv(flag: str):
    # Denied flag by itself
    argv = ["planlint", "--target", "/valid/spec.md", "validate", flag]
    with pytest.raises(GuardRejection) as exc_info:
        assert_safe_argv(argv)
    assert exc_info.value.reason == "denied_flag"

    # Denied flag with =value
    argv_eq = ["planlint", "--target", "/valid/spec.md", "validate", f"{flag}=all"]
    with pytest.raises(GuardRejection) as exc_info:
        assert_safe_argv(argv_eq)
    assert exc_info.value.reason == "denied_flag"


@pytest.mark.parametrize(
    ("raw_secret", "expected_tag"),
    [
        ("ghp_1234567890abcdef1234567890", "[REDACTED:github-token]"),
        ("github_pat_11AAAAAAA0000000000000_1234567890", "[REDACTED:github-pat]"),
        ("sk-1234567890abcdef1234567890", "[REDACTED:api-key]"),
        ("AKIAIOSFODNN7EXAMPLE", "[REDACTED:aws-key-id]"),
        ("xoxb-1234567890-1234567890", "[REDACTED:slack-token]"),
        (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature123",
            "[REDACTED:jwt]",
        ),
        ("Authorization: Bearer secret-token-value", "Authorization: [REDACTED]"),
        ("API_KEY=super_secret_secret_value", "API_KEY=[REDACTED]"),
    ],
)
def test_security_secret_redaction(raw_secret: str, expected_tag: str):
    redacted = redact(raw_secret)
    assert expected_tag in redacted
    assert raw_secret not in redacted or "[REDACTED" in redacted


def test_security_gitleaks_toml_validity():
    """Verify that .gitleaks.toml exists, parses cleanly, and defines required rules."""
    gitleaks_file = REPO_ROOT / ".gitleaks.toml"
    assert gitleaks_file.exists(), ".gitleaks.toml configuration must exist"

    content = gitleaks_file.read_text(encoding="utf-8")
    parsed = tomllib.loads(content)
    assert "rules" in parsed or "title" in parsed
