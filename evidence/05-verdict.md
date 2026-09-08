# Step 5 — Week 1 verdict

**Toolkit extension version:** ms-windows-ai-studio.windows-ai-studio@1.6.11
**Date:** 2026-09-08 (rewritten from `05-verdict.template.md`; first written 2026-09-05)
**Sessions used:** 5
**Azure spend:** $0

> **What changed in this rewrite, and why it was needed.** The first version of
> this document recorded a winner for three prompts on one prompt's evidence,
> marked four agent probes `Passed: Yes` that were never run, claimed the
> verdict "survived the trip into the model" when no agent was ever built, and
> dropped §2b and the "does NOT rest on" field that its own template provides.
>
> The recommendation is unchanged and the reasoning for it is in §5. What is
> removed is everything underneath it that was not established. In a repository
> whose stated purpose is detecting a system that reports a non-result as a
> pass, its own exit artifact reporting four non-results as passes was the
> defect worth fixing first.

---

## 1. Bake-off winner per prompt

| Prompt | Winner | Runner-up |
|---|---|---|
| Planner | none — one entrant, and its fixture is an unfilled template | not run |
| Verifier | none — one entrant | not run |
| Search rationale | none — one entrant, and its fixture is an unfilled template | not run |

One model was tested: `ollama:qwen2.5:14b`. Slots A and B were never attempted
(they need GitHub credentials); slot D was dropped on purpose, which the runbook
permits. A single entrant cannot win a bake-off, so there is no winner to carry
forward to step 4.1 — and step 4 was not reached in any case (§3).

Two of slot C's three cells rest on nothing citable: `configs/probes/01-planner.md`
and `03-search-rationale.md` still open with `TEMPLATE. Paste a real proposal
from …` and carry synthetic placeholder content. Detail in `evidence/02-bakeoff.md`.

**Models that failed the verifier probe** (restated a nonzero exit as a pass):

None of the one tested. `qwen2.5:14b` declared FINDINGS where FINDINGS was
expected — `traces/20260905T191215Z-02-verifier/summary.json`, `screen: HELD`.
One model, one prompt, one run, and the screen is a keyword pass that the
capture itself flags as advisory (`screen_is_advisory`) and that no human has
audited.

**Models that mishandled exit 2**, and in which direction:

**Not measured.** No model has ever been shown the exit-2 fixture. The previous
version of this document answered "None. Ollama correctly returned BLOCKED",
which named a result for a probe that was never run — `configs/probes/04-verifier-blocked.md`
exists, `make probe-blocked` is wired, and the run was never made.

---

## 2. Did the MCP wrapper preserve the contract end to end?

A **Basis** column, because `Yes` was doing two different jobs: proved against
the real binary, and proved in a unit test. Both are worth having and they are
not the same claim.

| Contract | Preserved? | Basis | Evidence |
|---|---|---|---|
| planlint exit 0 → PASS | Yes | live | `evidence/03-mcp-selfcheck.json` |
| planlint exit 1 → FINDINGS | Yes | live | `evidence/03-mcp-selfcheck.json` |
| planlint exit 2 → BLOCKED (not a spec failure) | Yes | live | `evidence/03-mcp-selfcheck.json` |
| timeout → BLOCKED, never FINDINGS | Yes | unit | `mcp_server/tests/test_planlint_contract.py` |
| scorer `true` / `false` / `null` distinct | Yes | unit | `mcp_server/tests/test_scoring.py` |
| `pass_rate` excludes null; null when nothing scored | Yes | unit | `mcp_server/tests/test_scoring.py` |
| the verdict survived the trip *into the model* | **Not established** | — | see below |

**The three exit-code rows are the strongest result of the week**, and they are
new since the first version of this document. `evidence/03-mcp-selfcheck.json`
now reads `all_expected: true` from a real run of `planlint 0.2.0` against
fixtures tracked under `configs/fixtures/planlint/`. Exit 1 in particular had
never been demonstrated live against the real binary before.

**The scorer rows are unit-proven only, and "end to end" is not established for
that half.** No eval-harness sink artifact has ever been read. `score_run`'s
schema is pinned (`decisions/0002`) against documented output rather than
against an instance — see §4, stop condition 3.

**The last row is downgraded from `Yes`.** It cited `traces/`, which exists —
so the citation resolved while the claim did not. `traces/` holds one
raw-prompt HTTP probe transcript. No verdict has travelled through the MCP tool
into an agent, because no agent was built. The template flags this row as the
one the test suite cannot cover, and it is right: only step 4 can answer it.

---

## 2b. Was the Playground actually faster than the existing bench?

Criterion 4 of `decisions/0001`, which had no field here until a review noticed
the decision record calls it the criterion "most likely to be answered
generously" — and then gave it nowhere to be answered at all.

Answer it with two timings on **one** candidate model, not an impression.

| | Existing bench | Foundry Playground |
|---|---|---|
| Named baseline used | not measured | not measured |
| Wall clock, model chosen → verifier verdict recorded | not measured | not measured |
| Wall clock, model chosen → first-token latency recorded | not measured | not measured |
| Wall clock, model chosen → peak VRAM recorded | not measured | n/a for hosted slots |

**What did the Playground give you that the bench cannot?**

**Nothing that was demonstrated.** This is the uncomfortable reading and it
should be stated plainly: the Playground's two distinguishing features are
**Compare** and **Show resource usage**, and neither was used. The one capture
came from a headless HTTP call to a local Ollama endpoint — something the
existing bench can do and does. No timing was taken against a named baseline,
and no code in this repository can capture VRAM at all.

**Verdict on criterion 4:** **not measured**

---

## 3. Did any probe require weakening the tool contract?

> If yes, that is a stop signal, not a tuning task.

**Answer:** **not established — no probe was run.**

| Probe | Passed? | Contract change needed | What it was |
|---|---|---|---|
| Happy path | not run | not run | — |
| Override | not run | not run | — |
| Omission | not run | not run | — |
| Blocked | not run | not run | — |

The four probes in `configs/probes/agent-probes.md` require an agent built in
VS Code Agent Builder (runbook step 4.1). No agent was built, no conversation
was saved, and `snippets/` holds only its README. The previous version of this
document marked all four `Passed: Yes / Contract change needed: None`.

**No probe was run, so nothing had the opportunity to require weakening the
contract. The absence of pressure is not evidence of resistance.**

---

## 4. Stop conditions

| # | Condition | Triggered |
|---|---|---|
| 1 | No model passes the verifier probe → bake-off bench only | No — narrowly; see below |
| 2 | Wrapper cannot preserve exit-2 semantics without special-casing → architectural signal, do not patch around it | No |
| 3 | Scoring requires importing eval-harness internals rather than reading sink output → the seam is wrong, eval plane stays closed | **Open — undetermined** |

**1.** One model was shown the verifier probe and held the nonzero exit. The
condition as written did not fire. It rests on one model, one prompt, one run.

**2.** Did not fire, and this is well supported. BLOCKED is derived from the
process exit code, never from parsing planlint's stderr strings —
`evidence/03-mcp-selfcheck.json` records `verdict_derived_from: exit_code`, and
`mcp_server/tests/test_seam_is_closed.py` fails if the wrapper starts importing
what it is supposed to be calling.

**3. Recorded as open rather than answered.** `score_run` has never read a real
eval-harness sink artifact. `evidence/00-demo-eval.txt` captures why:

```
ValueError: judge_calibration.calibration_artifact_id is required to gate on
['helpfulness']: a judge's participation in gating must be traceable to the
calibration run that authorised it
```

Whether that is a config field with a real artifact behind it, or something only
a calibration run inside the harness can produce, is **not known**. If it is the
former, set it and run `score_run`. If it is the latter, that *is* stop
condition 3 and must be recorded as one rather than worked around. Inventing a
`calibration_artifact_id` to get past the error would be this repository's own
failure mode wearing a different label.

---

## 5. Recommendation

**One line:** keep as sidecar

**Because:** the wrapper does the job it was built to do, and that is what §2's
first three rows establish live against the real binary: exit 0, 1 and 2 survive
the trip through the MCP tool as PASS, FINDINGS and BLOCKED, with BLOCKED
derived from the exit code rather than from message strings (§4, condition 2).
That was the architectural question of the week and it came back clean. One
model held the verifier probe under pressure to launder it (§1), which is
criterion 1 of `decisions/0001`, met narrowly.

The template routes to `bench only` on "stop condition 1 or an **unmet**
criterion 4". Neither applies: condition 1 did not fire, and criterion 4 is
**not measured** rather than unmet — a distinct third answer whose stated
consequence is only that the comparative claim does not appear in this section.
It does not appear. A downgrade would assert that the Playground adds nothing,
which is as unsupported by this week's evidence as the claim that it does.

Scored against `decisions/0001`'s four criteria: **(1) met, narrowly** — one
model, one run. **(2) half** — 0/1/2 live-proven, `true`/`false`/`null`
unit-proven only, no sink artifact ever read. **(3) not established** — the
probes were never run. **(4) not measured**.

**Claims this recommendation does NOT rest on:**

- Comparative model quality. One slot ran; there is no winner in §1.
- Any model's handling of exit 2. The fixture was never sent to a model.
- Slots A, B or D. Two were never attempted; one was dropped on purpose.
- First-token latency or peak VRAM. Neither was measured and no script here can.
- Criterion 4 — whether the Playground is faster than the existing bench (§2b).
- The Playground's Compare or resource-usage views. Neither was used at all.
- Agent-probe behaviour under pressure. No agent was built (§3).
- `score_run` against a real eval-harness sink artifact (§4, condition 3).
- Any verdict travelling through the MCP tool into a model (§2, last row).

---

## 6. Week 2 cost and identity work, if proceeding

**Not estimated.** This section is a budget request, and a budget request should
follow a decision rather than accompany a proposal. `decisions/0001` is still
open and unsigned (§7).

Leaving `TBD` beside `Needed: Yes` in every row, as the previous version did,
reads as a costed plan awaiting numbers. It was not one. The items themselves
are correct and are kept, because they are the work someone would have to scope:

| Item | Needed | Estimated cost | Owner |
|---|---|---|---|
| Azure subscription | Yes | not estimated | |
| Foundry project | Yes | not estimated | |
| Foundry User role (Foundry Project Manager to create connections) | Yes | not estimated | |
| Remote MCP endpoint — a hosted agent **cannot** call the stdio server built this week | Yes | not estimated | |
| Private MCP endpoint: virtual network with a dedicated MCP subnet (in practice Container Apps, internal ingress) | Yes | not estimated | |
| Trace egress: shared run/trace ID contract, secret masking, field allow list | Yes | not estimated | |

---

## 7. Decision-log row

Copy into `decisions/0001-foundry-toolkit-week1.md` and set its status.

| Date | Decision | Status | Evidence |
|---|---|---|---|
| 2026-09-08 | Foundry Toolkit: keep as sidecar / bench only / drop | **PROPOSED — awaiting owner sign-off** | `evidence/02-bakeoff.md`, `evidence/03-mcp-selfcheck.json`, `traces/20260905T191215Z-02-verifier/`, `decisions/0002-pinned-sink-schema.md` |

`decisions/0001` declares itself "a **human gate**. This row is not closed by a
passing test suite." This document recommends; it does not decide. The Decision
block in `decisions/0001` is drafted and its Outcome and Date are deliberately
left empty.
