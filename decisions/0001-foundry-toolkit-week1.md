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
| `evidence/02-bakeoff.md` | session 2, from the template |
| `evidence/03-mcp-selfcheck.json` | `make selfcheck` — session 3 |
| `traces/` | session 5, four probe conversations |
| `evidence/05-verdict.md` | session 5, from the template |

---

## Decision

<!-- Fill in at the end of session 5. One line, then the reason. -->

**Outcome:**
**Date:**
**Reason:**
**Follow-up:**
