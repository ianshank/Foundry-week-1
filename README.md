# Foundry Toolkit spike — week 1

A throwaway repo for one question: **does the Foundry Toolkit earn a place as a
sidecar to the existing harness, or not?**

Five sessions, local only, zero Azure spend, ending in a written verdict. The
week counts as a success if it stops early on a stop condition, and fails only
if the verdict does not get written.

Full procedure: **[RUNBOOK.md](RUNBOOK.md)**.

---

## The one thing this repo is defending

`planlint` exits 0, 1, or 2. Those mean three different things:

| exit | verdict | means |
| --- | --- | --- |
| 0 | `PASS` | ran, found nothing at or above the threshold |
| 1 | `FINDINGS` | ran, found problems |
| 2 | `BLOCKED` | **could not look** — a precondition or usage error |

Exit 2 is not a pass and it is not a spec failure. The whole spike is a test of
whether that distinction survives being handed to a language model — first as
a raw prompt (step 2), then through an MCP tool into an agent (steps 3–4).
Everything in `mcp_server/` exists to make sure that if the distinction is lost, it
was lost by the *model* and not by the wrapper.

The same discipline applies to scoring: a scorer's `passed` is `true`, `false`,
or `null`, and `null` is excluded from `pass_rate`. Collapsing it either way
fabricates a result.

---

## Quickstart

```bash
cp .env.example .env && $EDITOR .env      # paths + guard rails
set -a; source .env; set +a

make setup      # venv + the MCP server + linters
make hooks      # git pre-commit gate (secret scan, gitleaks, lint)
make validate   # ruff, mypy, 7-layer test suite, coverage gate, secret pass -- run before any PR
make baseline   # session 1: version stamp, dialect card, baseline exit codes
```

`make` on its own lists every target against its session.

Branches: `main` (base), `Dev`, `QA`, and feature branches off `main`.

---

## Layout

```text
RUNBOOK.md                  the procedure, with the draft's defects marked [amended]
NEXT_STEPS.md               what to do before session 1, and what is still open
SECURITY.md                 threat model, per-surface controls, known limitations
CHANGELOG.md                what changed and why, where the diff does not say
docs/architecture/C4.md     context / container / component views + verdict flow

configs/probes/             system prompt + bake-off fixtures + the four agent probes
mcp_server/                 the two read-only MCP tools, and their contract tests
  src/foundry_spike_mcp/
    verdicts.py             PASS / FINDINGS / BLOCKED -- the only vocabulary
    guards.py               POLICY: verb + flag allow lists, path containment (hard-coded)
    config.py               CONFIG: paths, timeouts, limits (from the environment)
    planlint.py             run_verb -- the single guarded execution point
    scoring.py              score_run -- true / false / null preserved
    logging_setup.py        stderr-only structured logging
    server.py               transport only; supports mcp 1.x and 2.x

scripts/
  00-baseline.sh            step 0 evidence capture (records exit codes, never aborts on one)
  verifier_probe.py         headless facade for the bake-off verifier probe
  probe/                    modular verifier probe package (cli, runner, screen, client, config)
  scan_evidence.py          the secret gate
  promote_trace.py          raw capture -> tracked evidence, only if it scans clean

tests/                      enterprise 7-layer test suite (94% coverage)
  unit/                     Layer 1: modular component unit tests
  integration/              Layer 2: tool-function, filesystem, and probe pipeline flow
  functional/               Layer 3: planlint exit code-to-verdict mapping
  e2e/                      Layer 4: CLI subprocess executions
  journey/                  Layer 5: complete developer evaluation workflow simulation
  security/                 Layer 6: fuzzing path traversal, flag injections, secrets
  sanity/                   Layer 7: environment health, typing, and entrypoint sanity

.claude/                    skills (probe-evaluator, contract-guard, spike-validate), agents, hooks
.agents/                    Antigravity / Gemini automation skills
.githooks/pre-commit        secret scan + gitleaks + lint on staged Python
Dockerfile                  reproducible regression env (NOT a way to run the server)

evidence/                   the four evidence files; *.template.md are the blanks
traces/                     promoted captures; traces/raw/ is gitignored
decisions/                  the exit artifact — one decision-log row
snippets/                   step 4.5 adapter candidate, parked and unmerged
```

## What is already built, and what is not

**Built and tested:** both MCP tools, their refusals, the three-valued
contract, the stdio server, the evidence templates, and a headless verifier
probe. `make test` proves the verdict logic with no external dependencies at
all, and — once `make setup` has installed the SDK — starts the server and
checks both tools register. CI runs those as separate jobs, because a suite
that needs nothing installed cannot tell you whether the transport works.

**Not built, because it cannot be:** every judgement call. Loading four models,
reading four Playground cells, deciding which model laundered a failure,
writing the verdict. The scaffolding removes the typing, not the thinking.

**Deliberately unpinned:** the exact spelling of planlint's JSON flag
(`PLANLINT_JSON_FLAG`, confirmed by `make baseline`) and the eval-harness sink
schema (`_collect_scorers` walks tolerantly and returns BLOCKED on a shape it
does not recognise, rather than an empty pass). Both get narrowed in session 3
against real artifacts. Guessing them here would have produced code that looks
finished and silently mis-reads.

---

## Three things worth knowing before session 1

**The stdio server is week-1 only.** Tool Catalog connects *local* MCP servers
for use inside VS Code; Foundry Agent Service agents consume *remote* MCP
endpoints, and a private one needs a virtual network with a dedicated MCP
subnet. None of this code reaches a hosted agent. The tool *contract* is the
part that carries.

**Model Conversion is Windows-targeted.** It optimises for Windows CPU / GPU /
NPU and profiles via Windows ML. It does not emit Hailo or Jetson artifacts, so
the edge repos keep their existing pipelines. Slot D is a resource-usage read,
not a deployment path.

**Foundry is not the eval source of truth.** Its built-in evaluators are F1,
relevance, similarity and coherence — reference-similarity metrics, not the
calibration stack — and an in-vendor judge conflicts with the
verifier-outside-the-model-under-test rule. The harness keeps the governance
kernel; this week is only asking whether the Toolkit is a useful bench beside it.

---

## Blast radius

Nothing in this repo writes to `Mango_Code_Agent-Harness`, `Agents`, or
`planlint`. The MCP tools shell out and read files; a test
(`mcp_server/tests/test_seam_is_closed.py`) fails if that ever stops being true. The
planlint verb allow list excludes `init`, `new`, `witness` and `make`, and the
path allow list fails closed.

Three layers keep captures from leaking, because this repository is public
and holds output derived from private source repos:

1. `traces/raw/` and `evidence/raw/` are gitignored, so an unscanned transcript
   cannot be published by an absent-minded `git add -A`.
2. `scripts/promote_trace.py` is the only way a capture becomes tracked, and it
   **refuses** on a scan hit rather than warning.
3. `make hooks` installs a pre-commit gate, and CI runs both the same scan and
   gitleaks over history.

Policy is hard-coded on purpose. `guards.py` holds the verb allow list, the
flag deny list and the credential patterns, and reads no environment variable —
an allow list that can be widened by setting a variable is not an allow list.
Deployment settings live in `config.py`. That line is the one architectural
opinion in this repo worth defending.
