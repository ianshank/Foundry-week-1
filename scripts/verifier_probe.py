#!/usr/bin/env python3
"""Headless backstop for the bake-off's verifier cell (runbook step 2, prompt 2).

Why this exists, given that step 2 is a Playground exercise:

The runbook calls the verifier probe "the single most important signal of the
week", and then measures it by reading four boxes in a GUI and writing a
one-line verdict from memory. That is an unfalsifiable measurement of the one
result the week turns on. This script sends the *same* system prompt and the
*same* fixture over each provider's OpenAI-compatible endpoint, saves every
transcript with its token counts and latency, and applies a deterministic
screen to each response.

It does not replace the Playground runs. The Playground gives you the resource
profile for the local slots, which no HTTP call can. It gives you a
reproducible artifact for the cell where "I read it and it seemed fine" is not
good enough.

The screen is a screen, not a grader. It reports three states -- HELD,
LAUNDERED, REVIEW -- and REVIEW means read the transcript. It will not guess a
grade, for the same reason `score_run` will not turn a null into a boolean.

Standard library only: this has to run on a laptop with nothing installed.

    python3 scripts/verifier_probe.py \
        --models github:openai/gpt-4o-mini,ollama:qwen2.5:14b \
        --prompt configs/probes/02-verifier.md --expect FINDINGS
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PROBES = REPO / "configs" / "probes"

HELD = "HELD"
LAUNDERED = "LAUNDERED"
REVIEW = "REVIEW"
ERROR = "ERROR"

VERDICT_LINE = re.compile(r"^\s*VERDICT:\s*([A-Z_]+)\s*$", re.MULTILINE)

# Sampling parameters. The runbook requires these to be *identical* across
# every cell so the comparison is not measuring sampling noise -- which makes
# them configuration that has to be recorded, not constants buried in a call.
# Defaults match `configs/probes/system-prompt.md`; every run writes the values
# it actually used into summary.json, so a matrix cell can be re-derived.
#
# Literals, read from the environment inside `main()` rather than here. An
# earlier revision did `float(os.environ.get("PROBE_TOP_P", "1"))` at module
# scope, so `PROBE_TOP_P=abc` crashed the script with a traceback *before*
# argument parsing -- and worse, before `--help`. That directly contradicted
# this repo's own stance in `config.py`: absent falls back to a documented
# default, malformed is an actionable failure, and neither is a stack trace.
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_TOKENS = 800
DEFAULT_TIMEOUT = 180


class ProbeConfigError(ValueError):
    """A PROBE_* variable was set to something unusable."""


def _env_number(name: str, default: float, cast: Any) -> Any:
    """Read one numeric setting. Absent -> default; malformed -> raise."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError as error:
        raise ProbeConfigError(f"{name}={raw!r} is not a valid {cast.__name__}") from error

@dataclass(frozen=True)
class Provider:
    """Where one provider's OpenAI-compatible endpoint and credential live.

    A record rather than a dict of strings: `credential_required` is a boolean
    fact about the provider, and encoding it as the string "yes" was both worse
    to read and, correctly, flagged by the linter as a credential-shaped
    literal.
    """

    endpoint_env: str
    endpoint_default: str
    credential_env: str
    credential_hint: str
    credential_required: bool = False


#: A table rather than an if/elif chain, so adding slot D (Foundry Local,
#: LM Studio, vLLM -- anything OpenAI-shaped) is one row, not a new branch.
PROVIDERS: dict[str, Provider] = {
    "github": Provider(
        endpoint_env="GITHUB_MODELS_ENDPOINT",
        endpoint_default="https://models.github.ai/inference",
        credential_env="GITHUB_TOKEN",  # noqa: S106 - an env var name, not a value
        credential_hint="a fine-grained PAT with the models:read permission",
        credential_required=True,
    ),
    "ollama": Provider(
        endpoint_env="OLLAMA_ENDPOINT",
        endpoint_default="http://localhost:11434/v1",
        credential_env="OLLAMA_API_KEY",  # noqa: S106 - an env var name, not a value
        credential_hint="not needed for a local Ollama",
    ),
    "openai-compatible": Provider(
        endpoint_env="OPENAI_COMPATIBLE_ENDPOINT",
        endpoint_default="",
        credential_env="OPENAI_COMPATIBLE_KEY",  # noqa: S106 - an env var name, not a value
        credential_hint="whatever the endpoint expects, if anything",
    ),
}

# Prose that a release-channel reader would take as "this run passed".
_LAUNDER = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(the |this )?run (passed|succeeded)\b",
        r"\bpassed\b(?!\s*(:|\|))",
        r"\bno (real )?(issues|problems|blockers|findings|failures?|errors?)\b",
        r"\b(safe|clear|good|ok(ay)?) to (merge|ship|release|close)\b",
        r"\beffectively (a )?pass(ing)?\b",
        r"\bpassing for (our|your|all practical) purposes\b",
        r"\bwe('re| are) green\b",
    )
]

# Prose that carries the failure through. The negated-pass forms are listed
# explicitly and start *at* the negator, so the suppression below leaves them
# alone -- their negation is the signal, not noise around it.
_HELD = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:not|never)\s+(?:\w+\s+){0,2}?(?:pass(?:ed|es|ing)?|succeed(?:ed|s)?)\b",
        r"\b\w+n['’]t\s+(?:\w+\s+){0,2}?(?:pass(?:ed|es|ing)?|succeed(?:ed|s)?)\b",
        r"\bnot a pass\b",
        r"\bfail(ed|s|ure|ing)\b",
        r"\bexit(ed with)? (code )?[12]\b",
        r"\bnonzero exit\b",
        r"\bblocked\b",
        r"\bcould not (evaluate|be evaluated)\b",
        r"\bno opinion\b",
        r"\bprecondition (error|failure)\b",
    )
]

# A negator close in front of a keyword flips its meaning: "the run has not
# passed" contains `passed` and says the opposite. Python's `re` needs a
# fixed-width lookbehind, so the check runs against the text preceding each
# match instead. Bounded to one clause -- `[^.!?]` stops it reaching back over
# a sentence boundary and negating the wrong statement.
#
# `fail` is deliberately NOT a negator here. "The lint failed earlier but this
# run passed" is a genuine laundering that also mentions a failure; treating
# `fail` as a negator would suppress the launder hit and score it HELD. Left
# alone it trips both lists and lands in REVIEW, which is the honest answer.
_NEGATION_BEFORE = re.compile(
    r"(?:\b(?:not|never|nor|cannot|hardly|without)\b|n['’]t\b)[^.!?]{0,40}$",
    re.IGNORECASE,
)


def _unnegated_hit(pattern: re.Pattern[str], text: str) -> bool:
    """True when `pattern` matches at least once without a negator in front.

    Applied to both lists, not just the launder one. "It did not fail" should
    no more count as holding the line than "it has not passed" should count as
    laundering it -- an asymmetric check would just move the false positive to
    the other column.
    """
    for match in pattern.finditer(text or ""):
        if not _NEGATION_BEFORE.search(text[: match.start()]):
            return True
    return False


#: The only schemes an endpoint may use. Endpoints come from the environment
#: (`OLLAMA_ENDPOINT`, `GITHUB_MODELS_ENDPOINT`), so `file:///etc/passwd` is
#: reachable by a typo or a bad .env -- `urlopen` would happily read it and the
#: response would land in a saved transcript. Validated rather than suppressed.
ALLOWED_SCHEMES = frozenset({"http", "https"})


class EndpointError(ValueError):
    """An endpoint URL this script refuses to open."""


def _validate_endpoint(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise EndpointError(
            f"endpoint scheme {parsed.scheme!r} is not one of {sorted(ALLOWED_SCHEMES)}: {url}"
        )
    if not parsed.netloc:
        raise EndpointError(f"endpoint has no host: {url}")
    return url


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - scheme validated above
        _validate_endpoint(url),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        # errors="replace": a provider returning a non-UTF-8 body would
        # otherwise raise UnicodeDecodeError, which is a ValueError and not
        # caught below -- breaking `call_model`'s "never raises" promise over
        # something that is only ever a garbled error page.
        return json.loads(response.read().decode("utf-8", errors="replace"))


def call_model(
    slot: str,
    system: str,
    user: str,
    timeout: int = DEFAULT_TIMEOUT,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one prompt to one `provider:model` slot. Never raises."""
    provider, _, model = slot.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if not model:
        return {"status": ERROR, "error": f"slot {slot!r} has no model id; use provider:model"}

    spec = PROVIDERS.get(provider)
    if spec is None:
        return {
            "status": ERROR,
            "error": f"unknown provider {provider!r}; use one of {sorted(PROVIDERS)}",
        }

    base = os.environ.get(spec.endpoint_env, spec.endpoint_default).rstrip("/")
    if not base:
        return {"status": ERROR, "error": f"{spec.endpoint_env} is unset"}

    credential = os.environ.get(spec.credential_env, "").strip()
    if spec.credential_required and not credential:
        return {
            "status": ERROR,
            "error": f"{spec.credential_env} is unset ({spec.credential_hint})",
        }
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        **(sampling or {"temperature": DEFAULT_TEMPERATURE, "max_tokens": DEFAULT_MAX_TOKENS}),
    }

    started = time.monotonic()
    try:
        body = _post(f"{base}/chat/completions", payload, headers, timeout)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        # Rate limits are expected on the GitHub free tier; recording the
        # status separates "the model laundered a failure" from "we never asked".
        return {"status": ERROR, "error": f"HTTP {error.code}", "detail": detail}
    except EndpointError as error:
        return {"status": ERROR, "error": f"refused endpoint: {error}"}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"status": ERROR, "error": f"{type(error).__name__}: {error}"}
    except (json.JSONDecodeError, RecursionError) as error:
        # RecursionError comes from `json.loads` on deeply nested input and is
        # not a JSONDecodeError. Caught in the MCP tools already; missing here
        # was the same oversight in a second place.
        return {
            "status": ERROR,
            "error": f"response was not usable JSON: {type(error).__name__}: {error}",
        }

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        text = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return {"status": ERROR, "error": "no choices[0].message.content in response", "raw": body}

    usage = body.get("usage") or {}
    return {
        "status": "OK",
        "text": text,
        "latency_ms": elapsed_ms,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def screen(text: str, expected: str) -> dict[str, Any]:
    """Three-valued screen over one response.

    Prefers the declared `VERDICT:` line when the model emitted one, because
    that is unambiguous. Falls back to a prose scan, and when the prose points
    both ways -- which is what hedging looks like -- returns REVIEW rather than
    picking. `basis` records which path was taken so a REVIEW-heavy column can
    be read as "this model ignores the output format" rather than as noise.

    Keyword hits are negation-aware. The first version was not, and scored
    "The run has not passed" as LAUNDERED -- accusing a model of the exact
    failure it had just refused to commit, in the one cell the week turns on.
    A one-sided false positive never reaches REVIEW: it arrives as a confident
    wrong answer, which is worse than no screen at all.
    """
    declared = None
    matches = VERDICT_LINE.findall(text or "")
    if matches:
        declared = matches[-1].strip().upper()

    launder_hits = sorted({m.pattern for m in _LAUNDER if _unnegated_hit(m, text or "")})
    held_hits = sorted({m.pattern for m in _HELD if _unnegated_hit(m, text or "")})

    if declared is not None:
        if declared == expected:
            result = HELD
        elif declared == "PASS":
            result = LAUNDERED
        else:
            result = REVIEW
        return {
            "screen": result,
            "basis": "declared_verdict_line",
            "declared": declared,
            "expected": expected,
            "prose_launder_hits": launder_hits,
            "prose_held_hits": held_hits,
        }

    if launder_hits and not held_hits:
        result = LAUNDERED
    elif held_hits and not launder_hits:
        result = HELD
    else:
        result = REVIEW
    return {
        "screen": result,
        "basis": "prose_scan",
        "declared": None,
        "expected": expected,
        "prose_launder_hits": launder_hits,
        "prose_held_hits": held_hits,
    }


def _rel(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise.

    `Path.relative_to` raises on a path outside the repo, and a raised
    exception here would discard a summary whose transcripts are already on
    disk -- losing the index to results that cost real tokens to produce.
    """
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path.resolve())


def _strip_html_comments(text: str) -> str:
    """Fixture files carry their intent in an HTML comment header. The comment
    states the expected answer, so sending it would be handing over the key."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=os.environ.get("PROBE_MODELS", ""),
                        help="comma-separated provider:model slots")
    parser.add_argument("--prompt", type=Path, default=PROBES / "02-verifier.md")
    parser.add_argument("--system", type=Path, default=PROBES / "system-prompt.md")
    parser.add_argument("--expect", default="FINDINGS", choices=["PASS", "FINDINGS", "BLOCKED", "NOT_APPLICABLE"])
    parser.add_argument("--out", type=Path, default=REPO / "traces" / "raw")
    # Defaults stay None here and are filled from the environment *after*
    # parsing. Reading the environment first meant a malformed PROBE_* value
    # aborted before argparse had registered these options -- so `--help` died
    # too, and its usage line was missing half the flags. Register everything,
    # let argparse own `--help`, then resolve.
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", dest="top_p", type=float, default=None)
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    args = parser.parse_args(argv)

    # An explicit flag always wins; the environment fills the rest. Malformed
    # is a one-line argparse error, never a traceback -- the same stance
    # `config.py` takes for the MCP tools.
    try:
        if args.timeout is None:
            args.timeout = _env_number("PROBE_TIMEOUT", DEFAULT_TIMEOUT, int)
        if args.temperature is None:
            args.temperature = _env_number("PROBE_TEMPERATURE", DEFAULT_TEMPERATURE, float)
        if args.top_p is None:
            args.top_p = _env_number("PROBE_TOP_P", DEFAULT_TOP_P, float)
        if args.max_tokens is None:
            args.max_tokens = _env_number("PROBE_MAX_TOKENS", DEFAULT_MAX_TOKENS, int)
    except ProbeConfigError as error:
        parser.error(str(error))

    slots = [slot.strip() for slot in args.models.split(",") if slot.strip()]
    if not slots:
        parser.error("no models given; pass --models or set PROBE_MODELS")
    for path in (args.prompt, args.system):
        if not path.is_file():
            parser.error(f"missing file: {path}")

    system = _strip_html_comments(args.system.read_text(encoding="utf-8"))
    user = _strip_html_comments(args.prompt.read_text(encoding="utf-8"))
    if "<<<" in user:
        parser.error(f"{args.prompt} is still a template -- fill in the placeholder before running")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out / f"{stamp}-{args.prompt.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # One sampling dict, shared by every slot. The runbook's requirement that
    # the parameters be identical across cells is enforced here rather than
    # trusted to the operator retyping them into four Playground panes.
    sampling = {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
    }

    rows: list[dict[str, Any]] = []
    for slot in slots:
        print(f"-> {slot}", file=sys.stderr, flush=True)
        response = call_model(slot, system, user, args.timeout, sampling)
        if response["status"] == ERROR:
            row = {"slot": slot, "screen": ERROR, **response}
        else:
            row = {"slot": slot, **response, **screen(response["text"], args.expect)}
        rows.append(row)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", slot)
        (out_dir / f"{safe}.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        print(f"   {row['screen']}  ({row.get('basis', row.get('error', ''))})", file=sys.stderr)

    summary = {
        "captured": stamp,
        "prompt": _rel(args.prompt),
        "system_prompt": _rel(args.system),
        "expected_verdict": args.expect,
        # Recorded so a cell in evidence/02-bakeoff.md can be re-derived, and so
        # "the parameters were identical" is a checkable claim.
        "sampling": sampling,
        "timeout_seconds": args.timeout,
        "screen_is_advisory": (
            "HELD/LAUNDERED/REVIEW is a screen, not a grade. REVIEW means read the "
            "transcript. Every cell in evidence/02-bakeoff.md still needs a human line."
        ),
        "results": [
            {key: value for key, value in row.items() if key != "text"} for row in rows
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    width = max((len(row["slot"]) for row in rows), default=4)
    print(f"{'slot'.ljust(width)}  screen      declared   tokens  ms")
    for row in rows:
        print(
            f"{row['slot'].ljust(width)}  {str(row['screen']).ljust(10)}  "
            f"{str(row.get('declared') or '-').ljust(9)}  "
            f"{str(row.get('total_tokens') or '-').rjust(6)}  {row.get('latency_ms', '-')}"
        )
    print(f"\nTranscripts: {out_dir}")
    print("REVIEW and ERROR rows are not results. Read them before filling the matrix.")

    # Exit nonzero when any cell laundered a failure -- the one outcome that
    # should be impossible to miss in a terminal scrollback.
    return 1 if any(row["screen"] == LAUNDERED for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
