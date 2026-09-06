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

import json
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
    # Authorization headers. The value is optionally prefixed by a scheme, and
    # the earlier form of this pattern consumed exactly one whitespace-delimited
    # token after the separator -- which on the standard
    # `Authorization: Bearer <token>` ate the word "Bearer" and left the
    # credential itself in the evidence. It redacted the label and kept the
    # secret. `(?:\S+[ \t]+)?` takes the scheme when one is present.
    # `\s+` after the scheme, not `[ \t]+`. With a horizontal-only separator a
    # wrapped header -- `Authorization: Bearer\n<token>` -- matched the scheme
    # on the first line and left the credential on the second: the exact defect
    # this rule was rewritten to close, back again for text that happens to be
    # line-wrapped. Transcripts are full of wrapped headers.
    (re.compile(r"(?i)\b(authorization)\s*[:=]\s*(?:\S+\s+)?\S+"), r"\1: [REDACTED]"),
    # The same credential without a header around it. `verifier_probe` builds
    # exactly this string for its outbound header, so a transcript could carry
    # it with no `authorization:` prefix to match on.
    #
    # The length floor alone was not enough, and a review caught it: "Basic
    # implementation is required" and "bearer instrument reading" both matched,
    # because English words are routinely longer than eight characters. A rule
    # broad enough to redact evidence is its own failure, and this repository's
    # evidence is prose about specifications.
    #
    # Two lookaheads separate a credential from a word. The token qualifies if
    # it carries a digit or base64 punctuation, OR an uppercase letter anywhere
    # after the first character. Between them they cover what real credentials
    # look like while leaving prose alone:
    #
    #   dXNlcjpwYXNz     internal capitals      -> redacted (base64 of user:pass)
    #   sk_live_9999     digits and underscores -> redacted
    #   implementation   neither                -> left as evidence
    #   Authentication   capital only at [0]    -> left as evidence
    #
    # The digit test alone was not enough: base64 is frequently all-alphabetic.
    # The case test alone was not enough either: plenty of tokens are lowercase
    # and numeric. A lowercase, all-alphabetic secret would still slip both,
    # and that is the accepted cost -- under an `Authorization:` label the
    # pattern above catches it regardless of shape.
    (
        # The case-insensitive flag is scoped to the scheme word alone. Applied
        # to the whole pattern -- as it first was -- `(?i)` also folds the
        # `[A-Z]` in the lookahead, so the mixed-case test silently matched any
        # two letters and the over-redaction it was added to fix came straight
        # back. An inert guard reads exactly like a working one.
        re.compile(
            r"\b((?i:bearer|basic))\s+"
            r"(?=[A-Za-z0-9._\-+/=]*[0-9._\-+/=]|[A-Za-z][A-Za-z0-9._\-+/=]*[A-Z])"
            r"([A-Za-z0-9._\-+/=]{8,})"
        ),
        r"\1 [REDACTED]",
    ),
    (
        re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|APIKEY|API_KEY))\s*=\s*\S+"),
        r"\1=[REDACTED]",
    ),
    # Shapes with no rule at all until a security review went looking for them.
    # This list gates commits as well as tool output -- `scan_evidence.py`
    # scans with it and `promote_trace.py` refuses on a hit -- so a shape
    # missing here is a shape that can be published from a public repository
    # holding transcripts derived from private ones.
    #
    # Every one is prefix- or label-anchored, for the reason this block opens
    # with: a general "long opaque string" rule would redact the git SHAs and
    # rule identifiers that are the evidence.
    (
        re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"),
        "[REDACTED:private-key]",
    ),
    # Credentials embedded in a URL. Anchored on the scheme separator so it
    # cannot match a bare `host:port` or an ordinary `key: value` line.
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://[REDACTED]@"),
    (re.compile(r"(?i)\b(aws_secret_access_key)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\bAccountKey=[A-Za-z0-9+/=]{16,}"), "AccountKey=[REDACTED]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"), "[REDACTED:gitlab-token]"),
    (re.compile(r"https://hooks\.slack\.com/services/\S+"), "[REDACTED:slack-webhook]"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{30,}"), "[REDACTED:google-api-key]"),
    # The `sk-` rule above is hyphen-anchored and misses the underscore forms.
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"), "[REDACTED:stripe-key]"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{20,}"), "[REDACTED:npm-token]"),
    (re.compile(r"\bhf_[A-Za-z0-9]{20,}"), "[REDACTED:huggingface-token]"),
    (re.compile(r"\bpypi-[A-Za-z0-9_\-]{20,}"), "[REDACTED:pypi-token]"),
    (
        re.compile(r"(?i)\b(x-api-key|api-key|cookie|proxy-authorization)\s*[:=]\s*\S+"),
        r"\1: [REDACTED]",
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


def wire_safe(text: str) -> str:
    """Make a string encodable, so a good verdict is not lost to its own payload.

    A lone surrogate is legal in a Python `str` and legal as a JSON escape --
    `"\\ud800"` parses without complaint -- but it cannot be encoded to UTF-8.
    The tool therefore produces a perfectly correct verdict that the transport
    then fails to serialise, and what reaches the model is the SDK's
    "Error executing tool" with no verdict field in it.

    That is the failure this package exists to prevent, arriving one layer
    further out than the rule is usually applied: it is not enough that
    `score_run` does not raise, the thing it returns has to be deliverable.
    Found by driving the real server over stdio; no in-process test can see it,
    because in-process nothing ever encodes the result.

    `backslashreplace` rather than `replace`: the reader gets `\\ud800` and can
    see what was there, instead of a `?` that destroys the evidence silently.
    """
    if not text:
        return text
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def redact(text: str) -> str:
    """Strip recognisable credential shapes from anything bound for evidence.

    Also makes the result encodable. Every externally-derived string in a
    result already flows through here, so this is the one place that guarantee
    can be made once rather than remembered at each call site.
    """
    if not text:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return wire_safe(text)


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


def _reject_non_finite(token: str) -> Any:
    """`json.loads` hook for the three constants JSON does not actually have."""
    raise ValueError(
        f"{token} is a Python extension, not JSON; it cannot be framed as JSON-RPC"
    )


def _checked_float(token: str) -> float:
    """Reject a number that *overflows* to infinity rather than naming it.

    `parse_constant` fires only on the literal tokens `NaN`, `Infinity` and
    `-Infinity`. `1e999` is an ordinary JSON number that Python parses to `inf`
    without going near that hook, and it re-serialises as `Infinity` -- the
    same unframeable payload, by a route the first version of this guard did
    not cover. Found by a security review, not by the tests written for it.
    """
    value = float(token)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(
            f"{token} overflows to a non-finite float; it cannot be framed as JSON-RPC"
        )
    return value


def loads_strict(text: str) -> Any:
    """`json.loads`, minus the non-standard floats Python accepts by default.

    Python's decoder accepts bare ``NaN``, ``Infinity`` and ``-Infinity``, and
    its encoder emits them back. JSON has no such literals, so a payload
    carrying one parses here and then re-serialises into a frame the client
    cannot read -- and on a stdio MCP server an unreadable frame is not a
    visible error, it is the tool disappearing.

    Refusing is the contract-correct answer rather than substituting `null`:
    the value is evidence this wrapper cannot faithfully carry, and guessing
    what the producer meant is the failure this package exists to prevent. The
    caller downgrades the evidence and keeps the verdict, which comes from the
    exit code and is unaffected.

    Raises `ValueError` for both a malformed document and a non-finite float,
    so callers need one handler rather than a list of `json` subclasses that
    has already been wrong three times.
    """
    return json.loads(text, parse_constant=_reject_non_finite, parse_float=_checked_float)


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
            # Keys are redacted too: a credential is as likely to appear as a
            # key in a map of secrets as it is in a value. That introduces a
            # collision this loop has to handle -- two *different* credentials
            # redact to the same marker, and the second would otherwise
            # overwrite the first, dropping evidence silently in the exact code
            # path this function exists to defend. Allocation happens here,
            # eagerly, because assignment into `branch` is deferred until the
            # child is popped and a check at that point would race.
            # A next-ordinal counter rather than a probing loop. The obvious
            # `while candidate in taken: ordinal += 1` is quadratic when many
            # keys collapse to the same marker, which is precisely the input
            # this function is written to survive: 4000 credential-shaped keys
            # inside the size budget took 905ms of pure probing. Remembering
            # the next free ordinal per base makes it linear.
            # Redact every key first, then allocate. Two passes, because a
            # single pass got each half wrong in turn:
            #
            # * Probing with `while candidate in taken` is quadratic on the
            #   input this function exists to survive -- 4000 keys collapsing
            #   to one marker spent 905ms scanning. A per-base counter fixes
            #   that.
            # * But a counter alone can hand back a name that a *literal* key
            #   already holds. `{"ghp_A...": 1, "ghp_B...": 2,
            #   "[REDACTED:github-token]#2": 3}` produced two entries out of
            #   three, dropping the third silently -- in the function written
            #   to stop evidence disappearing silently. Knowing every redacted
            #   key up front is what makes a genuinely free name findable.
            redacted_keys = [
                redact(child_key) if isinstance(child_key, str) else child_key
                for child_key in node
            ]
            occupied = set(redacted_keys)
            next_ordinal: dict[Any, int] = {}
            for (_, child), base_key in zip(node.items(), redacted_keys, strict=True):
                safe_key = base_key
                if base_key in next_ordinal:
                    ordinal = next_ordinal[base_key]
                    safe_key = f"{base_key}#{ordinal}"
                    while safe_key in occupied:
                        ordinal += 1
                        safe_key = f"{base_key}#{ordinal}"
                    occupied.add(safe_key)
                    next_ordinal[base_key] = ordinal + 1
                else:
                    next_ordinal[base_key] = 2
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
