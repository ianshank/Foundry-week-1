<!-- Copy to evidence/05-verdict.md. This is the week's exit artifact.
     Write it before closing the week, including when the week stopped early --
     an early stop is a result, and an unwritten verdict is the only way this
     week can actually fail. -->

# Step 5 — Week 1 verdict

**Toolkit extension version:**  <!-- ms-windows-ai-studio.windows-ai-studio@x.y.z -->
**Date:**
**Sessions used:** <!-- of 5 -->
**Azure spend:** <!-- target: $0. If nonzero, say what and why. -->

---

## 1. Bake-off winner per prompt

| Prompt | Winner | Runner-up |
|---|---|---|
| Planner | | |
| Verifier | | |
| Search rationale | | |

**Models that failed the verifier probe** (restated a nonzero exit as a pass):

<!-- Name them. This is the field the rest of the document hangs on. -->

**Models that mishandled exit 2**, and in which direction:

---

## 2. Did the MCP wrapper preserve the contract end to end?

| Contract | Preserved? | Evidence |
|---|---|---|
| planlint exit 0 → PASS | | `evidence/03-mcp-selfcheck.json` |
| planlint exit 1 → FINDINGS | | `evidence/03-mcp-selfcheck.json` |
| planlint exit 2 → BLOCKED (not a spec failure) | | `evidence/03-mcp-selfcheck.json` |
| timeout → BLOCKED, never FINDINGS | | `mcp/tests/test_planlint_contract.py` |
| scorer `true` / `false` / `null` distinct | | `mcp/tests/test_scoring.py` |
| `pass_rate` excludes null; null when nothing scored | | `mcp/tests/test_scoring.py` |
| the verdict survived the trip *into the model* | | `traces/` |

The last row is the one that is not covered by the test suite. The tests prove
the tool is correct. Only the traces show whether a model preserved it.

---

## 3. Did any probe require weakening the tool contract?

> If yes, that is a stop signal, not a tuning task.

**Answer:** yes / no

<!-- If yes: what were you tempted to change, and what made the agent behave
     once you did? Record the temptation even if you resisted it -- the fact
     that the contract had to be argued with is itself the finding. -->

| Probe | Passed? | Contract change needed | What it was |
|---|---|---|---|
| Happy path | | | |
| Override | | | |
| Omission | | | |
| Blocked | | | |

---

## 4. Stop conditions

| # | Condition | Triggered |
|---|---|---|
| 1 | No model passes the verifier probe → bake-off bench only | |
| 2 | Wrapper cannot preserve exit-2 semantics without special-casing → architectural signal, do not patch around it | |
| 3 | Scoring requires importing eval-harness internals rather than reading sink output → the seam is wrong, eval plane stays closed | |

<!-- Note on condition 2: ordinary error handling is not "special-casing".
     Catching TimeoutExpired and a missing binary so they map to BLOCKED is
     what makes exit-2 semantics *work*; it is not the wrapper fighting the
     contract. Condition 2 fires when BLOCKED can only be produced by
     inspecting stderr strings, by pattern-matching planlint's messages, or by
     anything else that would break on the next planlint release. Do not let
     this week self-terminate on a false positive. -->

---

## 5. Recommendation

**One line:** proceed to a Week 2 hosted twin / stop at local bake-off bench.

**Because:**

---

## 6. Week 2 cost and identity work, if proceeding

Estimate these before agreeing to week 2, because this is where "no Azure
required" stops being true.

| Item | Needed | Estimated cost | Owner |
|---|---|---|---|
| Azure subscription | | | |
| Foundry project | | | |
| Foundry User role (Foundry Project Manager to create connections) | | | |
| Remote MCP endpoint — a hosted agent **cannot** call the stdio server built this week | | | |
| Private MCP endpoint: virtual network with a dedicated MCP subnet (in practice Container Apps, internal ingress) | | | |
| Trace egress: shared run/trace ID contract, secret masking, field allow list | | | |

The stdio server in `mcp/` is week-1 only. Nothing about it carries to a hosted
agent except the tool contract, which is the part worth carrying.

---

## 7. Decision-log row

Copy into `decisions/0001-foundry-toolkit-week1.md` and set its status.

| Date | Decision | Status | Evidence |
|---|---|---|---|
| | Foundry Toolkit: keep as sidecar / drop | | `evidence/` |
