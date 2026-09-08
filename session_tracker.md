# Session Tracker

This checklist enforces the 5-session boundary for the Foundry Toolkit spike.

Status as of 2026-09-08, checked against what is actually in the tree rather
than against recollection. A session is ticked only when its runbook "done
when" is satisfied; where it is partly satisfied, that is said rather than
rounded up.

- [x] **Session 1: Baseline Execution (`make baseline`)** — ran; three of four
      done-when clauses met. The demo eval recorded exit 1, not 0, and the
      reason is external: see `evidence/00-baseline.md`.
- [ ] **Session 2: Model Pulling & Matrix Configuration** — one slot of four
      loaded (`ollama:qwen2.5:14b`). Slot D dropped on purpose, which the
      runbook permits; slots A and B never attempted, which it does not.
      `evidence/02-bakeoff.md`.
- [x] **Session 3: MCP Schema Extraction** — the CLI half is done and real.
      `make selfcheck` runs the real `planlint 0.2.0` (FINDINGS and BLOCKED
      against tracked fixtures, PASS against an out-of-tree repo)
      and `evidence/03-mcp-selfcheck.json` reads `all_expected: true`, so exit
      0, 1 and 2 all land. Two things it does *not* cover, both stated in the
      verdict: the tools were never listed in Agent Builder, and `score_run`
      has never read a real sink artifact.
- [ ] **Session 4: Bake-off Matrix Execution (Probe)** — one cell of the sixteen-cell matrix has
      evidence behind it. No agent was built, so the four agent probes were not
      run and `snippets/` holds only its README.
- [ ] **Session 5: Verdict Extraction & Review** — `evidence/05-verdict.md` is
      written and honest about what it does not rest on, but
      `decisions/0001-foundry-toolkit-week1.md` is still `OPEN` and unsigned.
      That record declares itself a human gate; nothing here can tick it.

**The five-session budget is spent.** What remains is not more sessions but
three specific things, and two of them cannot be done from a terminal:

1. A reachable Ollama endpoint would close the exit-2 cell in one command.
2. A human at VS Code Agent Builder is the only way to reach session 4's
   probes, the "both tools list" clause of session 3, and criterion 4's timings.
3. `judge_calibration.calibration_artifact_id` is blocked outside this repo.

`NEXT_STEPS.md` is explicit that stopping here is a legitimate outcome: "If C3
and C4 cannot be afforded, that is fine, and it is not a failure."
