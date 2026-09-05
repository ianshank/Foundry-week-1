# Next steps

Ordered by what unblocks the most. The repository is scaffolding — none of the
week's actual findings exist yet, and no amount of further engineering here
substitutes for running the five sessions.

**The blunt version:** this repo is now over-engineered relative to its purpose.
It is a five-session throwaway spike carrying CI, containers, type checking and
a hook harness. That was asked for and it is defensible — the tool contract is
the artifact that survives into week 2, so testing it properly is not waste —
but do not let the scaffolding become the work. The deliverable is
`evidence/05-verdict.md`, and it is still empty.

---

## Before session 1

| # | Action | Why now |
|---|---|---|
| 1 | **Decide whether this repo stays public.** | It is public today and will accumulate planlint findings with real spec paths, pasted OpenSpec proposals, MCTS node dumps and model transcripts — from source repos that are private. One click; do it before the first capture, not after. |
| 2 | `cp .env.example .env` and fill it in | Nothing runs without `PLANLINT_TARGET` and an allow list. Both fail closed. |
| 3 | `make setup && make test` | Confirms the floor works on your machine before a session is on the clock. |
| 4 | `make hooks` | Installs the pre-commit secret gate. |
| 5 | Decide the default branch | `main` exists now but the repository default is still the working branch. Change it in repo settings so pull requests target something stable. |

---

## Open review findings

From the peer review of `2ac6e39`. Findings 1–3 are fixed; 4–11 were carried,
and this branch closes most of them. What is left:

| # | Finding | State |
|---|---|---|
| 4 | `RecursionError` escaped `score_run` | **fixed** |
| 5 | Unstable result shape | **fixed** — envelope tested across every path |
| 6 | Zero coverage on scanner, server, hooks | **fixed** — `test_evidence_hygiene.py`, `test_server_smoke.py`, `test_claude_assets.py` |
| 7 | `noqa` codes with no linter | **fixed** — ruff and mypy in CI; the one remaining `S310` sits above real scheme validation |
| 8 | Baseline flag probe compared inconsistent substrings | **fixed** |
| 9 | Five unreachable verbs in the allow list | **fixed** — `run_verb` reaches all six |
| 10 | Evidence cited gitignored paths | **fixed** — `promote_trace.py` |
| 11 | Scan skipped `snippets/`, `configs/` | **fixed** |
| 12 | `mcp/` shadowed the SDK as a namespace package | **fixed** — renamed `mcp_server/` |
| — | `_selfcheck` widens its own `PLANLINT_ALLOWED_ROOTS` | **open**. Justified (the temp dir is tool-created, not model-supplied) but it is still the tool relaxing its own guard to make a demo pass — the exact shape step 5 asks about. Should become an explicit parameter. |
| — | `traces/` has no index or template | **open**. `agent-probes.md` says what to record; nothing structures where. Four saved conversations with no index cannot be diffed. |
| — | No session tracker | **open**. A five-session time-boxed spike with no per-session done-when checklist. The likeliest way the week overruns quietly. |

---

## During the week

**Session 3 is smaller than the runbook assumes.** The server is written and
tested. What session 3 actually does:

1. Confirm planlint's real JSON flag spelling — `make baseline` reports the
   candidates; write the exact spelling into `PLANLINT_JSON_FLAG`.
2. Point `score_run` at a real sink artifact and **narrow `_collect_scorers`**
   to the pinned schema. It currently walks tolerantly and reports where it
   found each verdict; once the real shape is known, tighten it and record the
   shape in `decisions/`.
3. `make selfcheck` — writes `evidence/03-mcp-selfcheck.json`.

Spend the reclaimed time on the bake-off, which is the part that needs
judgement and cannot be scripted.

**Promote every capture.** `python3 scripts/promote_trace.py traces/raw/<run>`
before citing it from `evidence/02-bakeoff.md`. It refuses on a scan hit.

---

## After the verdict

Gated entirely on `evidence/05-verdict.md`. Do not start any of this before it
is written.

**If "stop at local bake-off bench":** archive this repo, copy the bake-off
matrix into the decision log, and close `decisions/0001`. The tool contract and
its test suite are still worth keeping as a reference for how the three-valued
seam should look — that is a real outcome, not a consolation.

**If "proceed to a week-2 hosted twin":** the stdio server does not carry over.
A hosted Foundry agent consumes *remote* MCP endpoints; a private one needs a
virtual network with a dedicated MCP subnet, in practice Container Apps with
internal-only ingress. What carries is the contract. Budget for:

- Azure subscription, Foundry project, Foundry User role (Foundry Project
  Manager to create connections)
- A reachable remote MCP endpoint, and the identity work around it
- Trace egress as a *decision*, not a toggle: a shared run/trace ID contract,
  secret masking on the export path, and a field allow list — settled before
  the first export, not after
- Triage capacity for the `Agents` open-issue backlog, which a second
  eval/trace plane competes with

**Three things that stay true either way.** Foundry is not the eval source of
truth — its built-in evaluators are reference-similarity metrics and an
in-vendor judge conflicts with the verifier-outside-the-model-under-test rule.
Model Conversion is Windows-targeted and emits neither Hailo nor Jetson
artifacts, so the edge repos keep their pipelines. And the `command_actions.py`
allow list stays authoritative; MCP tool descriptions and results are untrusted
input, so anything Foundry adds there is defence in depth.
