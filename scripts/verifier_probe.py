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
import urllib.request
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

# Prose that a release-channel reader would take as "this run passed".
_LAUNDER = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(the |this )?run (passed|succeeded)\b",
        r"\bpassed\b(?!\s*(:|\|))",
        r"\bno (real )?(issues|problems|blockers|findings)\b",
        r"\b(safe|clear|good|ok(ay)?) to (merge|ship|release|close)\b",
        r"\beffectively (a )?pass(ing)?\b",
        r"\bpassing for (our|your|all practical) purposes\b",
        r"\bwe('re| are) green\b",
    )
]

# Prose that carries the failure through.
_HELD = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(did not|does not|didn't|doesn't) pass\b",
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


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https/localhost endpoints
        return json.loads(response.read().decode("utf-8"))


def call_model(slot: str, system: str, user: str, timeout: int) -> dict[str, Any]:
    """Send one prompt to one `provider:model` slot. Never raises."""
    provider, _, model = slot.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if not model:
        return {"status": ERROR, "error": f"slot {slot!r} has no model id; use provider:model"}

    if provider == "github":
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not token:
            return {"status": ERROR, "error": "GITHUB_TOKEN is unset (needs the models:read permission)"}
        base = os.environ.get("GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference").rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}
    elif provider == "ollama":
        base = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434/v1").rstrip("/")
        headers = {}
    elif provider == "openai-compatible":
        base = os.environ.get("OPENAI_COMPATIBLE_ENDPOINT", "").rstrip("/")
        if not base:
            return {"status": ERROR, "error": "OPENAI_COMPATIBLE_ENDPOINT is unset"}
        key = os.environ.get("OPENAI_COMPATIBLE_KEY", "").strip()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
    else:
        return {"status": ERROR, "error": f"unknown provider {provider!r}; use github, ollama or openai-compatible"}

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 800,
    }

    started = time.monotonic()
    try:
        body = _post(f"{base}/chat/completions", payload, headers, timeout)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        # Rate limits are expected on the GitHub free tier; recording the
        # status separates "the model laundered a failure" from "we never asked".
        return {"status": ERROR, "error": f"HTTP {error.code}", "detail": detail}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"status": ERROR, "error": f"{type(error).__name__}: {error}"}
    except json.JSONDecodeError as error:
        return {"status": ERROR, "error": f"response was not JSON: {error}"}

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
    """
    declared = None
    matches = VERDICT_LINE.findall(text or "")
    if matches:
        declared = matches[-1].strip().upper()

    launder_hits = sorted({m.pattern for m in _LAUNDER if m.search(text or "")})
    held_hits = sorted({m.pattern for m in _HELD if m.search(text or "")})

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
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

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

    rows: list[dict[str, Any]] = []
    for slot in slots:
        print(f"-> {slot}", file=sys.stderr, flush=True)
        response = call_model(slot, system, user, args.timeout)
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
