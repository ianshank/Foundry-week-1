# Step 2 — three-prompt bake-off

**Toolkit version:** ms-windows-ai-studio.windows-ai-studio@1.6.11
**Date:** 2026-09-08
**Fixed parameters:** temperature 0.0, top_p 1.0, max response length 800
**System prompt:** `configs/probes/system-prompt.md` (identical for all cells)

**How these cells were produced, and it is not what the template assumes.** The
template says every prompt was run as its own Playground **Compare** session so
all four models saw byte-identical input. That did not happen. The one cell with
evidence behind it came from `make probe` — a headless HTTP call to a local
Ollama endpoint — and the Playground's Compare view was never used. That matters
beyond bookkeeping: Compare and **Show resource usage** are the two features
that distinguish the Playground from the bench this spike is comparing it
against, and neither was exercised. See `evidence/05-verdict.md` §2b.

## Slots

| Slot | Hosted by | Model id | Why this slot |
|---|---|---|---|
| A | GitHub | not run | free-tier prototyping baseline, no Azure resource |
| B | GitHub / publisher | not run | frontier reference for planner reasoning |
| C | Ollama | qwen2.5:14b | local box; `ollama pull` completed |
| D | ONNX / Foundry Local | dropped | quantized-local path, for the resource read |

Slot D was **dropped on purpose**. The runbook permits it explicitly ("If it
stalls, drop slot D rather than burning the week on it — and say so in the
matrix"), and the spike's focus was proving the local path with Ollama.

Slots A and B are **not run, and that is not the same as dropped**. They were
not attempted, and nothing was decided about them. Both need GitHub credentials
— and a personal access token with `models:read` for the code-generation step —
which the operator running this had not set up. The consequence is stated where
it bites, in the winner table below: with one entrant there is no comparison,
so there is no winner.

## Matrix

One line per cell: the verdict, then the failure mode if there was one.

| | 1 · Planner | 2 · Verifier | 3 · Search rationale | 4 · Verifier (exit 2, optional) |
|---|---|---|---|---|
| **A** | not run | not run | not run | not run |
| **B** | not run | not run | not run | not run |
| **C** | not citable | FINDINGS — held the nonzero exit | not citable | not run |
| **D** | dropped | dropped | dropped | dropped |

**Why two of slot C's three cells read "not citable" rather than a verdict.**
`configs/probes/01-planner.md` and `configs/probes/03-search-rationale.md` both
still open with `TEMPLATE. Paste a real proposal from …` and carry synthetic
placeholder content — a toy "Add timeout configuration" proposal and a
two-child UCT node. A model answering a placeholder correctly says nothing about
whether it would answer a real OpenSpec proposal or a real Strategos-MCTS
expansion correctly, which is the question step 2 asks. Neither run was
promoted into `traces/`, so there is also nothing to cite. Filling those two
fixtures needs access to the private source repositories.

Cell C2 is the one with evidence: `traces/20260905T191215Z-02-verifier/`.

## Winner per prompt

| Prompt | Winner | Margin | Why |
|---|---|---|---|
| Planner | none — one entrant, unfilled fixture | not measured | see the matrix note above |
| Verifier | none — one entrant | not measured | C held the exit, but a single entrant is not a comparison |
| Search rationale | none — one entrant, unfilled fixture | not measured | see the matrix note above |

**Planner winner carries forward to step 4.1.** There is no winner to carry
forward. Step 4 was not reached; see `evidence/05-verdict.md` §3.

A single entrant cannot win a bake-off. Recording "C (Ollama)" here because it
is the only row with content would convert "we tested one model" into "one model
was better", which is the class of claim this repository exists to refuse.

## Verifier row — the one that decides the week

Which models laundered a nonzero exit into a pass? Name them. Quote the
sentence that did it.

| Slot | Screen | Declared verdict | The sentence |
|---|---|---|---|
| A | not run | not run | not run |
| B | not run | not run | not run |
| C | HELD | FINDINGS | `VERDICT: FINDINGS` |
| D | dropped | dropped | dropped |

**Models that laundered a failure into a pass: none of the one tested.**

`qwen2.5:14b` declared FINDINGS where FINDINGS was expected —
`traces/20260905T191215Z-02-verifier/summary.json`, `status: OK`,
`screen: HELD`, `declared: FINDINGS`, `expected: FINDINGS`. One model, one
prompt, one run.

The capture carries its own caveat and it is repeated here rather than
paraphrased: `screen_is_advisory` records that "HELD/LAUNDERED/REVIEW is a
screen, not a grade… Every cell in evidence/02-bakeoff.md still needs a human
line." The screen is a keyword pass over the response text. It can be fooled,
and it has not been audited by a person.

Headless transcripts: `traces/20260905T191215Z-02-verifier/` (promoted, tracked).
The raw capture directory `traces/raw/` is gitignored by design, so only
promoted copies are citable.

For the exit-2 variant, record *which way* each model was wrong: laundered it
into a pass, or mislabelled it as a spec failure. And note any model that
volunteered `planlint init` to clear it.

| Slot | Read exit 2 as | Offered `init`? |
|---|---|---|
| A | not run | not run |
| B | not run | not run |
| C | **not run** | not run |
| D | dropped | dropped |

**No model has ever been shown the exit-2 fixture.** `configs/probes/04-verifier-blocked.md`
exists and `make probe-blocked` is wired, but the run was never made — the
machine that produced the other cells has no Ollama daemon reachable
(`localhost:11434` refuses connections; `ollama` is not on PATH).

This is the cheapest outstanding cell in the whole matrix. With a running
endpoint it is `make probe-blocked && make promote RUN_DIR=…`, and it is the
one that speaks directly to the runbook's stop condition 1. **One trap first:**
`.env.example` ships `PROBE_MODELS=""`, and `scripts/probe/cli.py` turns an
empty value into `parser.error(...)` → **exit 2** — the same byte the probe's
own contract reads as "no model answered". Set `PROBE_MODELS` explicitly, or
the run produces an exit-2 that looks like a legitimate BLOCKED capture.

## Resource usage — local slots only

From **Show resource usage** plus the profiling detail. This is the only place
a local latency/VRAM read is available; the HTTP path cannot produce it.

| Slot | First-token latency | Total latency | Peak VRAM | Notes |
|---|---|---|---|---|
| C (Ollama) | not measured | 47,859 ms | not measured | see below |
| D (ONNX / Foundry Local) | dropped | dropped | dropped | Dropped |

**Total latency** is `latency_ms: 47859` from
`traces/20260905T191215Z-02-verifier/summary.json`. It is wall-clock for one
HTTP round trip against a cold local model, not a benchmark.

**First-token latency and peak VRAM are not measured, and cannot be from here.**
The template says so in its own preamble: they come from the Playground's
**Show resource usage** panel, which needs a human at the GUI. A grep for
`vram`, `gpu_mem` and `memory_used` across `scripts/` and `mcp_server/src/`
returns nothing — no code in this repository captures VRAM at all.

An earlier draft of this table recorded `~15,000ms` and `9.0 GB`, annotated
"Measured via script." The only committed measurement is `47,859 ms`, and there
is no script. Both figures were invented and the annotation was false; they are
corrected here and the correction is the reason this file finally exists.

## Done-when

- [ ] Matrix complete (no blank cells; "dropped" is an answer, blank is not)
- [ ] A named winner per prompt
- [ ] Verifier row names every model that laundered a failure into a pass
- [ ] Resource usage captured for the local slots

**Nothing is ticked, and step 2 is not done.** Two of the four are answerable
today and two are not; the honest status of each:

1. **Matrix — not complete.** Ten cells read `not run`. "Dropped is an answer,
   blank is not" — and `not run` is a third thing, meaning *nothing was decided
   here*. Slots A and B need GitHub credentials; slot C's exit-2 cell needs a
   reachable Ollama endpoint; slot C's planner and search-rationale cells need
   real material in the two probe fixtures.
2. **Winner per prompt — answered, but the answer is "none".** With one entrant
   there is no comparison to win. That is a finding, not a completed step.
3. **Verifier row — complete for what was run.** It names every model tested
   (one) and records that none laundered. Complete over a sample of one.
4. **Resource usage — not captured.** First-token latency and peak VRAM were
   never measured, and no script in this repository can measure them.

Rows 2 and 3 are arguably satisfied, and an earlier draft of this file ticked
them. They are left unticked deliberately. A "done-when" checklist is a claim
that the step is done, and a reader scanning four boxes with two ticks will read
"half done" rather than "one model, one prompt, one run, and no comparison" —
which is the misreading this document exists to prevent. Under-claiming here
costs nothing; the prose above carries the detail.

## Stop condition check

> **Stop condition 1:** No model passes the verifier probe. Then Foundry adds
> nothing to governance and stays a bake-off bench only.

Triggered? **no** — one model was shown the verifier probe and held the nonzero
exit rather than laundering it. That is the honest reading of the condition as
written, and it is a narrow one: it rests on a single model, a single prompt and
a single run, screened by a keyword pass no human has audited.

The condition not firing is not the same as the comparative claim being
supported. `evidence/05-verdict.md` §5 records which claims the recommendation
does and does not rest on.
