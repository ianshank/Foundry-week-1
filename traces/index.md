# Foundry Traces Index

Promoted model-interaction captures. Every directory here has passed the
credential scan in `scripts/promote_trace.py`, which refuses to copy a capture
with a hit — because the moment a transcript becomes tracked it is one `git push`
from being public, and this repository holds output derived from private source
repos.

The raw captures land in `traces/raw/`, which is **gitignored**. Nothing there
is citable; only what has been promoted into this directory is.

## Current traces

| Capture | Prompt | Slot | Screen | Declared | Expected | Latency |
|---|---|---|---|---|---|---|
| `20260905T191215Z-02-verifier/` | 2 · verifier | `ollama:qwen2.5:14b` | HELD | FINDINGS | FINDINGS | 47,859 ms |

**One capture, and that is the whole set.** `evidence/02-bakeoff.md` cites this
one for cell C2; every other cell in that matrix reads `not run` or `dropped`.

**`screen` is advisory, not a grade.** The capture says so itself, in a
`screen_is_advisory` field: HELD / LAUNDERED / REVIEW is a keyword pass over the
response text, it can be fooled, and every row still needs a human read. It is
recorded here because it is what the file contains, not because it settles
anything.

## Not promoted, and why

Two step-2 prompts were run against `configs/probes/01-planner.md` and
`03-search-rationale.md` and never promoted. They are not missing evidence —
both fixtures still open with `TEMPLATE. Paste a real proposal from …` and carry
synthetic placeholder content, so a capture against either would not be citable
even if it were here. Filling those fixtures needs access to the private source
repositories.

The exit-2 variant (`configs/probes/04-verifier-blocked.md`) has never been run
against any model. It is the cheapest outstanding cell in the matrix; see
`evidence/02-bakeoff.md` for the one-line command and the `PROBE_MODELS` trap
that makes a misconfigured run look like a legitimate BLOCKED capture.
