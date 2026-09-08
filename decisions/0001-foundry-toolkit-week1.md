# 0001 — Foundry Toolkit: keep as sidecar, or drop

**Status:** OPEN — closed by `evidence/05-verdict.md` at the end of session 5
**Opened:** 2026-09-05
**Owner:** ianshank
**Decision type:** human gate. This row is not closed by a passing test suite.

---

## Question

Does the Foundry Toolkit earn a standing place beside the existing harness as a
model bake-off bench and a demo-grade hosted twin — or does it add nothing that
justifies the second plane?

## What would make the answer "keep as sidecar"

1. At least one model holds the verifier probe: reports a nonzero exit as a
   nonzero exit under pressure to do otherwise.
2. The MCP wrapper preserves 0/1/2 and `true`/`false`/`null` end to end,
   without special-casing planlint's message strings.
3. No probe requires weakening the tool contract to make the agent behave.
4. The Playground's Compare and resource-usage views give a faster read on a
   candidate model than the existing bench does. This one is a judgement call,
   and it is the one most likely to be answered generously — write down what
   you actually did faster, not what it looked like it could do.

## What would make the answer "drop", or "bench only"

Any of the three stop conditions in `RUNBOOK.md` step 5. Each of them ends the
week as a success, not a failure:

| # | Condition | Verdict it implies |
|---|---|---|
| 1 | No model passes the verifier probe | Bake-off bench only; Foundry adds nothing to governance |
| 2 | Wrapper cannot preserve exit-2 without special-casing | Architectural signal; do not patch around it |
| 3 | Scoring needs eval-harness internals, not sink output | The seam is wrong; the eval plane stays closed |

## Constraints on the decision

- **The harness keeps the governance kernel.** Foundry does not become the eval
  source of truth. Its built-in evaluators are reference-similarity metrics,
  and an in-vendor judge conflicts with the verifier-outside-the-model-under-test
  rule.
- **The `command_actions.py` allow list stays authoritative.** MCP tool
  descriptions and results are untrusted input; anything Foundry contributes
  there is defence in depth, not a replacement.
- **A "yes" costs money and identity work.** Week 2 needs a subscription, a
  Foundry project, the Foundry User role (Foundry Project Manager to create
  connections), and a reachable *remote* MCP endpoint — the stdio server built
  this week cannot be called by a hosted agent. Estimate that before agreeing.
- **`Agents` has an open-issue backlog.** Standing up a second eval/trace plane
  competes with triaging the canonical one. A "keep" that does not account for
  that is a "keep" that will not happen.

## Evidence this row will cite

| File | Produced by |
|---|---|
| `evidence/00-toolkit-version.txt` | `make baseline` — session 1 |
| `evidence/00-dialect-card.json` | `make baseline` — session 1 |
| `evidence/02-bakeoff.md` | session 2, from the template — **exists as of 2026-09-08**; ten of twelve matrix cells read `not run` |
| `evidence/03-mcp-selfcheck.json` | `make selfcheck` — session 3; `all_expected: true` against the real binary |
| `traces/` | session 5, four probe conversations — **one capture, and it is a headless step-2 probe, not an agent conversation** |
| `evidence/05-verdict.md` | session 5, from the template |
| `decisions/0002-pinned-sink-schema.md` | 2026-09-08; the pin `score_run` shipped without a record |

---

## Decision

<!-- Fill in at the end of session 5. One line, then the reason. -->

**Outcome:**
**Date:**

<!-- Outcome and Date are deliberately blank. This row is a human gate and
     signing it is not something the test suite, or anything that runs in CI,
     can do. Everything below is drafted so that closing it is a matter of
     choosing a line and dating it. -->

### Scorecard against the four criteria above

| # | Criterion | Answer | Resting on |
|---|---|---|---|
| 1 | At least one model holds the verifier probe | **met, narrowly** | one model, one prompt, one run; screen is advisory and unaudited — `traces/20260905T191215Z-02-verifier/` |
| 2 | Wrapper preserves 0/1/2 and `true`/`false`/`null` end to end | **half** | 0/1/2 live-proven against `planlint 0.2.0`; the scorer half is unit-proven only and no sink artifact has ever been read |
| 3 | No probe requires weakening the tool contract | **not established** | the four agent probes were never run; no agent was built |
| 4 | The Playground gives a faster read than the existing bench | **not measured** | Compare and Show resource usage were never used at all |

### The three lines this row may take

Spelled as `evidence/05-verdict.template.md` §5 spells them, so the two
documents cannot offer different vocabularies:

* **keep as sidecar** — proceed to a week-2 hosted twin; §6 of the verdict then
  becomes a budget request rather than a note. **This is what
  `evidence/05-verdict.md` §5 proposes.**
* **bench only** — the Playground earns a place as a local bake-off bench and
  Foundry adds nothing to governance. The template routes here on stop
  condition 1 or an *unmet* criterion 4; neither applies, since condition 1 did
  not fire and criterion 4 is *not measured*, which is a distinct third answer.
  It remains a defensible choice on a different argument: one slot ran, so the
  comparative claim is unsupported — the wording `NEXT_STEPS.md` sanctions.
* **drop** — it adds nothing the existing bench does not. Note this also needs
  criterion 4 measured: concluding "adds nothing" from "never measured" is the
  same fabrication pointed the other way.

Two of the three end the week early and the week still counts as a success.
Only an unwritten verdict is a failure.

**Reason:**

<!-- Cite the verdict's sections by number. `evidence/05-verdict.md` §5 carries
     the proposed reasoning and, more usefully, the list of claims the
     recommendation does NOT rest on. -->

**Follow-up:**

<!-- The three things that would change this answer, none of which can be done
     from a terminal on the machine that produced this tree:

     1. A reachable Ollama endpoint closes the exit-2 cell in one command and
        speaks directly to stop condition 1. Cheapest by a wide margin.
     2. A human at VS Code Agent Builder is the only route to criterion 3 (the
        four probes), criterion 4 (the two timings), and session 3's "both
        tools list in Agent Builder" clause.
     3. `judge_calibration.calibration_artifact_id` is blocked outside this
        repository and gates criterion 2's scorer half. If it turns out to
        need harness changes rather than a config field, that is runbook stop
        condition 3 and should be recorded as one, not worked around. -->
