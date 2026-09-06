"""Refusals are properties of the tool, so they are tested like properties."""

from __future__ import annotations

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


# --------------------------------------------------------------------------
# A path the operating system cannot represent.
#
# `Path.resolve` raises for these rather than returning, and the argument comes
# from a model. The guard has to turn that into a refusal, because a refusal is
# a verdict and an exception is not.
# --------------------------------------------------------------------------


def test_a_nul_byte_in_the_target_is_a_refusal_not_an_exception(tmp_path):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target(f"{tmp_path}/spec\x00.md", (tmp_path,))
    assert caught.value.reason == guards.REJECT_INVALID_PATH


def test_the_refusal_detail_carries_the_cause_but_not_the_path(tmp_path):
    """The path is the malformed thing. Echoing it puts a NUL into a result
    that gets serialised to JSON and written into a trace."""
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target(f"{tmp_path}/spec\x00.md", (tmp_path,))
    assert "ValueError" in caught.value.detail
    assert "\x00" not in caught.value.detail


def test_a_long_path_is_still_ordinary(tmp_path):
    """Only paths the OS cannot represent are refused as invalid. A merely long
    one resolves and is judged on containment like any other."""
    long_target = f"{tmp_path}/" + "a" * 5000
    assert guards.check_target(long_target, (tmp_path,))


# --------------------------------------------------------------------------
# `redact_structure` -- redaction for payloads that arrive already parsed.
# --------------------------------------------------------------------------

TOKEN = "ghp_" + "B" * 36


def test_a_credential_in_a_nested_value_is_redacted():
    payload = {"findings": [{"message": f"saw {TOKEN}"}]}
    out, exceeded = guards.redact_structure(payload, max_depth=16)
    assert exceeded is False
    assert TOKEN not in str(out)
    assert "[REDACTED:github-token]" in out["findings"][0]["message"]


def test_a_credential_used_as_a_key_is_redacted():
    """A map of secrets keyed by the secret is not a hypothetical shape."""
    out, _ = guards.redact_structure({TOKEN: "value"}, max_depth=16)
    assert TOKEN not in str(list(out))


def test_scalars_and_containers_survive_unchanged():
    payload = {"n": 1, "f": 1.5, "b": True, "nil": None, "empty": [], "obj": {}}
    out, _ = guards.redact_structure(payload, max_depth=16)
    assert out == payload


def test_the_input_is_not_mutated():
    """Callers keep the original for size accounting, so redaction must copy."""
    payload = {"message": f"saw {TOKEN}"}
    guards.redact_structure(payload, max_depth=16)
    assert payload["message"] == f"saw {TOKEN}"


def test_list_order_is_preserved():
    out, _ = guards.redact_structure(["a", "b", "c", "d"], max_depth=16)
    assert out == ["a", "b", "c", "d"]


def test_a_subtree_past_the_depth_limit_is_marked_not_silently_dropped():
    deep: object = "bottom"
    for _ in range(10):
        deep = {"next": deep}
    out, exceeded = guards.redact_structure(deep, max_depth=3)
    assert exceeded is True
    assert guards.DEPTH_LIMIT_MARKER in str(out)


def test_a_document_far_deeper_than_the_recursion_limit_does_not_raise():
    """The walk is iterative for the same reason `json.loads` needed guarding:
    a RecursionError escaping here would be an exception standing in for a
    verdict, one layer further in."""
    deep: object = "bottom"
    for _ in range(50_000):
        deep = [deep]
    out, exceeded = guards.redact_structure(deep, max_depth=100)
    assert exceeded is True
    assert out is not None


# --------------------------------------------------------------------------
# Negative cases that were correct but unpinned. A review found each of these
# reachable and untested; behaviour is unchanged, the guarantee is not.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_target_is_refused(tmp_path, blank):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_target(blank, (tmp_path,))
    assert caught.value.reason == "empty_target"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_verb_is_refused(blank):
    with pytest.raises(guards.GuardRejection) as caught:
        guards.check_verb(blank)
    assert caught.value.reason == "empty_verb"


def test_an_empty_argv_is_refused():
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv([])
    assert caught.value.reason == "empty_argv"


def test_an_argv_with_no_verb_at_all_is_refused():
    """Every token is an option or an option's value, so no verb was ever
    reached. Refused rather than allowed through unchecked."""
    with pytest.raises(guards.GuardRejection) as caught:
        guards.assert_safe_argv(["planlint", "--target", "/srv/specs"])
    assert caught.value.reason == "no_verb"


def test_two_different_credentials_as_keys_both_survive_redaction():
    """Contract review finding. Both keys redact to the same marker, so the
    second silently overwrote the first -- evidence lost with no exception and
    no note, in the exact code path this function exists to defend."""
    other = "ghp_" + "E" * 36
    out, _ = guards.redact_structure({TOKEN: "first", other: "second"}, max_depth=16)
    assert sorted(out.values()) == ["first", "second"]
    assert TOKEN not in str(out)
    assert other not in str(out)


def test_a_key_collision_is_disambiguated_deterministically():
    payload = {"ghp_" + letter * 36: index for index, letter in enumerate("FGH")}
    first, _ = guards.redact_structure(payload, max_depth=16)
    second, _ = guards.redact_structure(payload, max_depth=16)
    assert len(first) == 3
    assert first == second


def test_a_key_that_needs_no_redaction_is_untouched():
    out, _ = guards.redact_structure({"rule": "SPEC001", "line": 4}, max_depth=16)
    assert out == {"rule": "SPEC001", "line": 4}


# --------------------------------------------------------------------------
# Authorization headers. A policy change, so it gets a test either way.
#
# The earlier pattern consumed one whitespace-delimited token after the
# separator, which on the standard `Authorization: Bearer <token>` redacted the
# word "Bearer" and left the credential in the evidence. It removed the label
# and kept the secret. A weakened assertion in the payload tests was hiding it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        pytest.param(
            "authorization: Bearer abc123secretvalue", "abc123secretvalue", id="header-bearer"
        ),
        pytest.param(
            "Authorization: Basic dXNlcjpwYXNzd29yZA==",
            "dXNlcjpwYXNzd29yZA",
            id="header-basic",
        ),
        pytest.param("authorization=xyz789abc", "xyz789abc", id="header-equals"),
        pytest.param(
            "Bearer abc123secretvalue", "abc123secretvalue", id="bare-scheme-no-header"
        ),
        pytest.param(
            '"Authorization": "Bearer sk_live_9999999999"',
            "sk_live_9999999999",
            id="inside-json",
        ),
    ],
)
def test_an_authorization_credential_does_not_survive_redaction(text, secret):
    redacted = guards.redact(text)
    assert secret not in redacted
    assert "REDACTED" in redacted


@pytest.mark.parametrize(
    "evidence",
    [
        # Short follow-on words. These were the only cases the first version of
        # this test used, which is why it passed while the rule was wrong.
        "bearer of bad news",
        "the basic case",
        "basic auth is described in the spec",
        # Long follow-on words -- the gap a review found. English is routinely
        # longer than the eight-character floor, so length alone proved nothing.
        "Basic implementation is required",
        "Basic authentication scheme",
        "basic validation failed",
        "bearer instrument reading",
        "Basic Authentication is a scheme",
        "a basic requirement document",
        # Unrelated evidence that must survive intact.
        "rule G009 at line 42",
        "commit 4f2a1c9b",
    ],
)
def test_ordinary_prose_is_not_redacted_as_a_credential(evidence):
    """A rule broad enough to redact evidence is its own failure, and this
    repository's evidence is prose about specifications.

    Two rules were wrong here in succession and both looked right: an
    eight-character floor that English clears easily, then a mixed-case test
    made inert by a `(?i)` flag that folded its own `[A-Z]`. Hence the long
    words below -- a guard that cannot fail is indistinguishable from one that
    works.
    """
    assert guards.redact(evidence) == evidence


@pytest.mark.parametrize(
    "credential",
    [
        "Bearer abc123secretvalue",
        "Bearer sk_live_9999999999",
        "Basic dXNlcjpwYXNz",  # base64, all-alphabetic, internal capitals
        "Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ",
        "BEARER ABC123XYZ789",
        "Bearer eyJhbGci.eyJzdWIi.SflKxw",
    ],
)
def test_a_bare_scheme_credential_is_still_caught(credential):
    """The other direction, in the same test file, because tightening a rule
    until prose survives is only half of it."""
    assert "REDACTED" in guards.redact(credential)


# --------------------------------------------------------------------------
# Non-finite floats: valid Python, not valid JSON, and fatal on the wire.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_float_is_refused_rather_than_carried(literal):
    """`json.loads` accepts these and `json.dumps` emits them back, so a
    payload carrying one parses here and then re-serialises into a frame the
    client cannot read. On a stdio server that is not a visible error; it is
    the tool disappearing."""
    with pytest.raises(ValueError):
        guards.loads_strict(f'{{"x": {literal}}}')


def test_ordinary_json_still_parses():
    assert guards.loads_strict('{"a": [1, 2.5, null, true, "x"]}') == {
        "a": [1, 2.5, None, True, "x"]
    }


def test_a_key_collision_stays_linear_on_adversarial_input():
    """Many keys redacting to the same marker is the shape this function is
    written to survive. The first implementation probed for a free ordinal and
    went quadratic: 4000 colliding keys cost most of a second in pure scanning.
    """
    token = "ghp_" + "E" * 36
    payload = {f"{token}{index}": index for index in range(4000)}
    redacted, _ = guards.redact_structure(payload, max_depth=8)
    # Every key survives as its own entry: nothing was silently overwritten.
    assert len(redacted) == 4000
    assert not any(token in key for key in redacted)


# --------------------------------------------------------------------------
# Wire safety. A verdict that cannot be encoded never reaches the model, which
# is the same outcome as not producing one.
# --------------------------------------------------------------------------


def test_a_lone_surrogate_is_made_encodable():
    """Legal in a Python str, legal as a JSON escape, impossible in UTF-8.

    `"\\ud800"` parses without complaint, so it arrives from an artifact
    looking like ordinary text and only fails at the transport.
    """
    scrubbed = guards.wire_safe("name\ud800here")
    scrubbed.encode("utf-8")  # the assertion: this must not raise
    assert "ud800" in scrubbed  # backslashreplace keeps the evidence visible


def test_redaction_also_makes_its_output_encodable():
    """Every externally-derived string already flows through `redact`, so the
    guarantee is made once there rather than remembered at each call site."""
    guards.redact("token \ud800 here").encode("utf-8")


@pytest.mark.parametrize("text", ["plain", "with spaces", "ünïcodé", "emoji 🙂", ""])
def test_wire_safe_leaves_ordinary_text_alone(text):
    assert guards.wire_safe(text) == text


# --------------------------------------------------------------------------
# Findings from a security review of this branch. Each one is a credential
# that reached the evidence, or a rule that ate evidence instead.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        pytest.param(
            "Authorization: Bearer\ndXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA", id="wrapped-header"
        ),
        pytest.param("Bearer\nAbCdEf0123456789xyz", "AbCdEf0123456789xyz", id="wrapped-bare"),
    ],
)
def test_a_wrapped_header_does_not_keep_its_credential(text, secret):
    """The scheme and the credential can land on different lines, and a
    horizontal-only separator matched the first and left the second -- the same
    label-redacted, secret-kept defect this rule was rewritten to close."""
    redacted = guards.redact(text)
    assert secret not in redacted
    assert "REDACTED" in redacted


# Credential-shaped fixtures, assembled at run time rather than written as
# literals. They have to be complete and realistic or they would not exercise
# the patterns -- but a literal here is indistinguishable from a real leak to
# a scanner, and GitHub's push protection duly blocked this file. Composing
# them keeps the test honest and keeps scanner bait out of the repository.
# `test_evidence_hygiene.py` asserts the same discipline for the fixtures it
# owns, and `.gitleaks.toml` allowlists this file for the same reason.
_AWS_SECRET = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfi" + "CYEXAMPLEKEY"
_AZURE_KEY = "Zm9vYmFyYmF6cXV4" + "MTIzNA=="
_GITLAB_PAT = "glpat" + "-" + "ABCdef123456789xyzQ"
_SLACK_HOOK = "https://hooks.slack.com/services/" + "T00000/B00000/XXXXXXXXXXXX"
_STRIPE_KEY = "sk" + "_live_" + "9999999999abcdef"
_API_KEY = "abcdef123456789"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        pytest.param(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKC\n-----END RSA PRIVATE KEY-----",
            "MIIEowIBAAKC",
            id="pem-block",
        ),
        pytest.param(
            "https://alice:hunter2SuperSecret@internal.example.com/repo.git",
            "hunter2SuperSecret",
            id="basic-auth-in-url",
        ),
        pytest.param(
            f"aws_secret_access_key = {_AWS_SECRET}", _AWS_SECRET, id="aws-secret-not-just-the-id"
        ),
        pytest.param(
            f"AccountKey={_AZURE_KEY};EndpointSuffix=core.windows.net",
            _AZURE_KEY,
            id="azure-connection-string",
        ),
        pytest.param(_GITLAB_PAT, _GITLAB_PAT.split("-", 1)[1], id="gitlab-pat"),
        pytest.param(_SLACK_HOOK, _SLACK_HOOK.rsplit("/", 1)[1], id="slack-webhook-url"),
        pytest.param(_STRIPE_KEY, _STRIPE_KEY.rsplit("_", 1)[1], id="stripe-underscore-form"),
        pytest.param(f"x-api-key: {_API_KEY}", _API_KEY, id="api-key-header"),
    ],
)
def test_credential_shapes_that_previously_had_no_rule(text, secret):
    """Every one of these passed through untouched until a review went looking.

    This list gates commits as well as tool output -- `scan_evidence.py` scans
    with it -- so each was a shape publishable from a public repository holding
    transcripts derived from private ones.
    """
    redacted = guards.redact(text)
    assert secret not in redacted
    assert "REDACTED" in redacted


@pytest.mark.parametrize("literal", ["1e999", "-1e999", "1E400"])
def test_a_number_that_overflows_to_infinity_is_refused(literal):
    """`parse_constant` fires only on the bare `Infinity` token. `1e999` is an
    ordinary JSON number that Python parses to `inf` and re-serialises as
    `Infinity` -- the same unframeable payload by a route the first version of
    this guard did not cover."""
    with pytest.raises(ValueError):
        guards.loads_strict(f'{{"score": {literal}}}')


def test_ordinary_floats_are_untouched():
    assert guards.loads_strict('{"a": 1.5, "b": -2e10, "c": 0.0}') == {
        "a": 1.5,
        "b": -2e10,
        "c": 0.0,
    }


def test_a_generated_suffix_never_overwrites_a_literal_key():
    """Two credentials collapsing to one marker are disambiguated with `#N`,
    and `#N` can be a key the document already has. That dropped an entry
    silently, in the function written to stop entries being dropped silently.
    """
    first = "ghp_" + "A" * 36
    second = "ghp_" + "B" * 36
    payload = {first: "one", second: "two", "[REDACTED:github-token]#2": "three"}
    redacted, _ = guards.redact_structure(payload, max_depth=8)
    assert len(redacted) == 3
    assert sorted(redacted.values()) == ["one", "three", "two"]


# --------------------------------------------------------------------------
# The scanner's category comes from the rule, not from its replacement text.
# --------------------------------------------------------------------------


def test_every_rule_carries_a_usable_category():
    """`scripts/scan_evidence.py` reports `kind` to say what it found.

    It used to derive that by stripping `[REDACTED:...]` out of the
    replacement, which held only while every replacement was a bare marker.
    The rules that keep context -- replacing with `\\1: [REDACTED]` so a
    redacted header still names itself -- printed as the literal
    `\\1: [REDACTED`, and this branch added several more of them.
    """
    assert guards.SECRET_PATTERNS, "expected at least one credential rule"
    for rule in guards.SECRET_PATTERNS:
        assert rule.kind, f"{rule.pattern.pattern[:40]} has no category"
        assert rule.kind == rule.kind.strip(), f"{rule.kind!r} has stray whitespace"
        # A category is a plain slug: no regex syntax, no marker punctuation.
        assert not set(rule.kind) & set("\\[]:$"), (
            f"{rule.kind!r} looks like it was scraped out of a replacement string"
        )


def test_rule_categories_are_unique():
    """Two rules reporting the same category makes a scan result ambiguous."""
    kinds = [rule.kind for rule in guards.SECRET_PATTERNS]
    assert len(kinds) == len(set(kinds)), f"duplicate categories: {sorted(kinds)}"
