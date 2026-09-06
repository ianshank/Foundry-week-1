"""Refusals live here, not in the prompt.

Runbook step 3.4 lists four refusals. A refusal written into an agent's
instructions is a suggestion; a refusal written here is a property of the
tool. Every guard fails closed: when a guard cannot prove a call is safe it
raises :class:`GuardRejection`, and the caller maps that to BLOCKED.

A guard never downgrades a rejection into a finding, and never into a pass.

**Why the policy constants below are hard-coded.** Deployment settings live in
`config.py` and come from the environment. The verb allow list, the flag deny
list and the credential patterns do not, and that asymmetry is deliberate: an
allow list widened by an environment variable is not an allow list. Changing
what this tool may execute should require a code change, a review and a test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: planlint verbs this wrapper is permitted to invoke. Read-only surface only:
#: `init`, `new`, `witness` and `make` are absent on purpose.
#:
#: All six are reachable through `planlint.run_verb`, which is why the list is
#: this size. An earlier revision advertised six and could only ever run
#: `validate`, which reads as capability and is really dead config.
ALLOWED_VERBS = frozenset({"detect", "validate", "graph", "rules", "waivers", "delta"})

#: Verbs that mutate. Listed rather than merely omitted so that the refusal is
#: greppable and so a test can assert they are still refused.
REFUSED_VERBS = frozenset({"init", "new", "witness", "make", "fix", "apply", "write"})

#: Flags that mutate state or bypass checks. Matched against the whole token
#: and against its `--flag=value` prefix.
DENIED_FLAGS = frozenset(
    {
        "--force",
        "--fix",
        "--write",
        "--apply",
        "--in-place",
        "--overwrite",
        "--yes",
        "--no-dry-run",
    }
)

#: Options that take a separate value, so the value is not mistaken for a verb
#: when `assert_safe_argv` hunts for one.
VALUE_OPTIONS = frozenset({"--target", "--fail-on", "--format", "--output"})

# Secret shapes worth catching before anything is written to an evidence file.
# Prefix-anchored on purpose: a broad "long opaque string" rule would redact
# git SHAs and rule IDs, which are the evidence.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), "[REDACTED:github-token]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED:github-pat]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api-key]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-key-id]"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:slack-token]"),
    (
        re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
        "[REDACTED:jwt]",
    ),
    (re.compile(r"(?i)\b(authorization|bearer)\s*[:=]\s*\S+"), r"\1: [REDACTED]"),
    (
        re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|APIKEY|API_KEY))\s*=\s*\S+"),
        r"\1=[REDACTED]",
    ),
)

#: Public alias. `scripts/scan_evidence.py` scans with this list rather than
#: keeping its own -- two definitions of "what a secret looks like" drift, and
#: the one that drifts is always the one in the script nobody reads.
SECRET_PATTERNS = _SECRET_PATTERNS

#: Rejection reason for a path the operating system cannot represent. Named
#: because two modules raise it and the tests assert on it; the older reasons
#: are literals only because they each have a single call site.
REJECT_INVALID_PATH = "invalid_path"

#: Stands in for a subtree that nests deeper than `redact_structure` will walk.
#: A marker rather than a silent drop: evidence that was removed should say so.
DEPTH_LIMIT_MARKER = "[...nested deeper than the redaction walk follows...]"


class GuardRejection(Exception):
    """A call was refused before any subprocess ran.

    Carries a short, model-readable reason. The message is surfaced to the
    agent so it can say *why* it could not evaluate, rather than inventing a
    verdict to fill the silence.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def check_target(
    target: str,
    roots: tuple[Path, ...] | list[Path],
    setting_hint: str = "the allow-list environment variable",
) -> Path:
    """Resolve ``target`` and prove it sits inside the allow list.

    ``setting_hint`` names the variables *this caller* reads. The function is
    shared by `lint_openspec` and `score_run`, which read different ones, and a
    rejection that tells an operator to set the wrong variable is worse than a
    generic one -- it sends them to fix something that was never the problem.

    Resolution happens before the containment test so that ``..`` traversal
    and symlinks out of an allowed root are both caught. The path is not
    required to exist -- a missing directory is a planlint precondition error
    (exit 2 / BLOCKED), which is a legitimate and interesting result, not a
    guard violation.
    """
    if not roots:
        raise GuardRejection("no_allowed_roots", f"set {setting_hint} to an absolute path")
    if not target or not target.strip():
        raise GuardRejection("empty_target")
    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        raise GuardRejection("relative_target", target)
    try:
        resolved = candidate.resolve(strict=False)
    except (ValueError, OSError) as error:
        # `Path.resolve` raises rather than returning for a path the operating
        # system cannot represent -- an embedded NUL is `ValueError`, a symlink
        # loop is `OSError`. Both arrive here from a *model-supplied* argument,
        # so letting them escape hands the model a framework error with no
        # verdict field: the one thing this package exists to prevent.
        #
        # The message deliberately does not echo the target. It is the thing
        # that is malformed, and a NUL byte pasted back into a JSON result is
        # a second problem on top of the first.
        raise GuardRejection(REJECT_INVALID_PATH, f"{type(error).__name__}: {error}") from error
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            return resolved
    raise GuardRejection(
        "target_outside_allow_list",
        f"{resolved} is not under any of {[str(r) for r in roots]}",
    )


def check_verb(verb: str) -> str:
    """Constrain the planlint verb to the read-only surface."""
    normalised = (verb or "").strip().lower()
    if not normalised:
        raise GuardRejection("empty_verb")
    if normalised not in ALLOWED_VERBS:
        raise GuardRejection("verb_not_allowed", f"{verb!r} not in {sorted(ALLOWED_VERBS)}")
    return normalised


def check_fail_on(value: str, allowed: tuple[str, ...]) -> str:
    """Constrain the severity threshold to the vocabulary this build knows."""
    normalised = (value or "").strip().upper()
    if normalised not in allowed:
        raise GuardRejection("bad_fail_on", f"{value!r} not in {list(allowed)}")
    return normalised


def assert_safe_argv(argv: list[str]) -> None:
    """Belt-and-braces check on a fully constructed command line.

    The model never supplies argv -- the tools build it from validated scalar
    arguments. This function guards against a future edit to that construction
    rather than against the current caller, so it asserts rather than
    negotiates.
    """
    if not argv:
        raise GuardRejection("empty_argv")
    # The verb is the first bare token, but option *values* are bare too --
    # `--target /path` would otherwise read as the verb `/path`. Skip the value
    # of every option known to take one.
    verb = None
    skip_next = False
    for token in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            if "=" not in token:
                skip_next = token in VALUE_OPTIONS
            continue
        verb = token
        break
    if verb is None:
        raise GuardRejection("no_verb", " ".join(argv))
    check_verb(verb)
    for token in argv:
        head = token.split("=", 1)[0]
        if head in DENIED_FLAGS:
            raise GuardRejection("denied_flag", token)


def redact(text: str) -> str:
    """Strip recognisable credential shapes from anything bound for evidence."""
    if not text:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def tail(text: str, limit: int) -> str:
    """Keep the last ``limit`` characters, marking the cut so it is visible.

    Tail rather than head: a stack trace's useful line is at the bottom.
    """
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"[...truncated {len(text) - limit} chars...]\n{text[-limit:]}"


def clean(text: str, limit: int) -> str:
    """Redact then truncate. Order matters: truncating first can bisect a
    token and leave half a credential in the evidence file."""
    return tail(redact(text or ""), limit)


def redact_structure(value: Any, max_depth: int) -> tuple[Any, bool]:
    """Redact every string inside a parsed JSON structure, keys included.

    `clean` protects text. This protects *parsed* payloads, which were the gap:
    a tool that parses stdout as JSON and returns the object has routed a
    credential straight past the text-level redaction, because the redaction
    only ever ran on the branch that failed to parse.

    Redacting the raw JSON text before parsing would be simpler and is wrong.
    One of the credential patterns consumes to the next whitespace, so on input
    like ``{"authorization": "Bearer abc"}`` it eats the closing quote and
    leaves text that no longer parses. Structure first, then strings.

    The walk is **iterative**. A recursive one would raise `RecursionError` on
    a deeply nested document, and this package's whole contract is that an
    exception is never a verdict -- the same trap `json.loads` sets, one layer
    further in. Depth is still bounded, because an attacker-shaped payload can
    nest far enough to exhaust memory rather than stack: past `max_depth` the
    subtree is replaced with `DEPTH_LIMIT_MARKER`.

    Returns ``(redacted, depth_exceeded)``. Never raises. Never mutates the
    input: callers keep the original for size accounting.
    """
    holder: dict[str, Any] = {}
    stack: list[tuple[Any, Any, Any, int]] = [(value, holder, "root", 0)]
    depth_exceeded = False

    while stack:
        node, parent, key, depth = stack.pop()
        if isinstance(node, str):
            parent[key] = redact(node)
        elif isinstance(node, dict):
            if depth >= max_depth:
                parent[key] = DEPTH_LIMIT_MARKER
                depth_exceeded = True
                continue
            branch: dict[Any, Any] = {}
            parent[key] = branch
            for child_key, child in node.items():
                # Keys are redacted too. A credential is as likely to appear as
                # a key in a map of secrets as it is in a value.
                safe_key = redact(child_key) if isinstance(child_key, str) else child_key
                stack.append((child, branch, safe_key, depth + 1))
        elif isinstance(node, list):
            if depth >= max_depth:
                parent[key] = DEPTH_LIMIT_MARKER
                depth_exceeded = True
                continue
            # Pre-sized so the stack can assign by index in any order.
            row: list[Any] = [None] * len(node)
            parent[key] = row
            for index, child in enumerate(node):
                stack.append((child, row, index, depth + 1))
        else:
            # int, float, bool, None. Nothing to redact and nothing to walk.
            parent[key] = node

    return holder["root"], depth_exceeded
