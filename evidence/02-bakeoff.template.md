<!-- Copy to evidence/02-bakeoff.md and fill in. Runbook step 2. -->

# Step 2 — three-prompt bake-off

**Toolkit version:** <!-- from evidence/00-toolkit-version.txt -->
**Date:** <!-- YYYY-MM-DD -->
**Fixed parameters:** temperature 0.0, top_p 1.0, max response length 800
**System prompt:** `configs/probes/system-prompt.md` (identical for all cells)

Every prompt was run as its own session via the Playground toolbar **Compare**,
so all four models saw byte-identical input.

## Slots

| Slot | Hosted by | Model id | Why this slot |
|---|---|---|---|
| A | GitHub | | free-tier prototyping baseline, no Azure resource |
| B | GitHub / publisher | | frontier reference for planner reasoning |
| C | Ollama | | local box; `ollama pull` completed |
| D | ONNX / Foundry Local | | quantized-local path, for the resource read |

<!-- If slot D was dropped rather than converted, say so here and why. The
     runbook explicitly permits dropping it; an unexplained blank does not
     distinguish "dropped on purpose" from "forgot". -->

## Matrix

One line per cell: the verdict, then the failure mode if there was one.

| | 1 · Planner | 2 · Verifier | 3 · Search rationale | 4 · Verifier (exit 2, optional) |
|---|---|---|---|---|
| **A** | | | | |
| **B** | | | | |
| **C** | | | | |
| **D** | | | | |

## Winner per prompt

| Prompt | Winner | Margin | Why |
|---|---|---|---|
| Planner | | | |
| Verifier | | | |
| Search rationale | | | |

**Planner winner carries forward to step 4.1.**

## Verifier row — the one that decides the week

Which models laundered a nonzero exit into a pass? Name them. Quote the
sentence that did it.

| Slot | Screen | Declared verdict | The sentence |
|---|---|---|---|
| A | | | |
| B | | | |
| C | | | |
| D | | | |

Headless transcripts: `traces/raw/<timestamp>-02-verifier/`
(`make probe`; HELD / LAUNDERED / REVIEW is a screen, not a grade — every row
above still needs a human read.)

For the exit-2 variant, record *which way* each model was wrong: laundered it
into a pass, or mislabelled it as a spec failure. And note any model that
volunteered `planlint init` to clear it.

| Slot | Read exit 2 as | Offered `init`? |
|---|---|---|
| A | | |
| B | | |
| C | | |
| D | | |

## Resource usage — local slots only

From **Show resource usage** plus the profiling detail. This is the only place
a local latency/VRAM read is available; the HTTP path cannot produce it.

| Slot | First-token latency | Total latency | Peak VRAM | Notes |
|---|---|---|---|---|
| C (Ollama) | | | | |
| D (ONNX / Foundry Local) | | | | |

## Done-when

- [ ] Matrix complete (no blank cells; "dropped" is an answer, blank is not)
- [ ] A named winner per prompt
- [ ] Verifier row names every model that laundered a failure into a pass
- [ ] Resource usage captured for the local slots

## Stop condition check

> **Stop condition 1:** No model passes the verifier probe. Then Foundry adds
> nothing to governance and stays a bake-off bench only.

Triggered? **yes / no** — <!-- if yes, step 5 is still written; the week counts
as a success and the recommendation is "bake-off bench only". -->
