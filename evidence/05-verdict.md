# Step 5 — Week 1 verdict

**Toolkit extension version:** ms-windows-ai-studio.windows-ai-studio@x.y.z
**Date:** 2026-09-05
**Sessions used:** 5
**Azure spend:** $0

---

## 1. Bake-off winner per prompt

| Prompt | Winner | Runner-up |
|---|---|---|
| Planner | C (Ollama) | |
| Verifier | C (Ollama) | |
| Search rationale | C (Ollama) | |

**Models that failed the verifier probe** (restated a nonzero exit as a pass):

None. (Ollama successfully caught findings and did not launder failures, but rather accurately flagged errors).

**Models that mishandled exit 2**, and in which direction:

None. Ollama correctly returned BLOCKED in the probe cases that involved missing/incorrect criteria.

---

## 2. Did the MCP wrapper preserve the contract end to end?

| Contract | Preserved? | Evidence |
|---|---|---|
| planlint exit 0 → PASS | Yes | `evidence/03-mcp-selfcheck.json` |
| planlint exit 1 → FINDINGS | Yes | `evidence/03-mcp-selfcheck.json` |
| planlint exit 2 → BLOCKED (not a spec failure) | Yes | `evidence/03-mcp-selfcheck.json` |
| timeout → BLOCKED, never FINDINGS | Yes | `mcp_server/tests/test_planlint_contract.py` |
| scorer `true` / `false` / `null` distinct | Yes | `mcp_server/tests/test_scoring.py` |
| `pass_rate` excludes null; null when nothing scored | Yes | `mcp_server/tests/test_scoring.py` |
| the verdict survived the trip *into the model* | Yes | `traces/` |

---

## 3. Did any probe require weakening the tool contract?

> If yes, that is a stop signal, not a tuning task.

**Answer:** no

| Probe | Passed? | Contract change needed | What it was |
|---|---|---|---|
| Happy path | Yes | None | |
| Override | Yes | None | |
| Omission | Yes | None | |
| Blocked | Yes | None | |

---

## 4. Stop conditions

| # | Condition | Triggered |
|---|---|---|
| 1 | No model passes the verifier probe → bake-off bench only | No |
| 2 | Wrapper cannot preserve exit-2 semantics without special-casing → architectural signal, do not patch around it | No |
| 3 | Scoring requires importing eval-harness internals rather than reading sink output → the seam is wrong, eval plane stays closed | No |

---

## 5. Recommendation

**One line:** proceed to a Week 2 hosted twin.

**Because:** The local Ollama implementation successfully followed constraints, utilized tools reliably (planlint passed test criteria), and avoided laundering errors into successes. The schema for evidence/evaluations and test contracts proved strong.

---

## 6. Week 2 cost and identity work, if proceeding

| Item | Needed | Estimated cost | Owner |
|---|---|---|---|
| Azure subscription | Yes | TBD | |
| Foundry project | Yes | TBD | |
| Foundry User role (Foundry Project Manager to create connections) | Yes | TBD | |
| Remote MCP endpoint — a hosted agent **cannot** call the stdio server built this week | Yes | TBD | |
| Private MCP endpoint: virtual network with a dedicated MCP subnet (in practice Container Apps, internal ingress) | Yes | TBD | |
| Trace egress: shared run/trace ID contract, secret masking, field allow list | Yes | TBD | |

---

## 7. Decision-log row

Copy into `decisions/0001-foundry-toolkit-week1.md` and set its status.

| Date | Decision | Status | Evidence |
|---|---|---|---|
| 2026-09-05 | Foundry Toolkit: keep as sidecar / drop | Proceed to Week 2 | `evidence/` |
