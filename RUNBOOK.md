# Foundry Toolkit Spike — Week 1 Runbook

**Time box:** 5 working sessions, roughly 6–8 hours total
**Azure spend:** zero. Everything here runs on GitHub-hosted models, Ollama, or local ONNX.
**Blast radius:** one throwaway repo. No commits to `Mango_Code_Agent-Harness`, `Agents`, or `planlint` this week.

**Exit artifact:** a decision-log row that says *keep as sidecar* or *drop*, plus four evidence files.

> Deviations from the original draft are marked **[amended]** with the reason.
> Three of them are defects that would have failed at run time; the rest are
> scaffolding that already exists in this repo.

---

## Step 0 — Spike isolation and prerequisites

**0.1** This repo *is* the throwaway working directory. It is outside every
production repo and it holds all configs, traces and notes. Nothing here
imports from, or writes to, `Agents`, `planlint`, or `Mango_Code_Agent-Harness`.

**0.2** Set the paths you will reuse as environment variables rather than
hardcoding them:

```bash
cp .env.example .env
$EDITOR .env
set -a; source .env; set +a
```

**[amended]** `.env.example` carries more than the original three variables.
`PLANLINT_ALLOWED_ROOTS`, `PLANLINT_BIN`, `PLANLINT_JSON_FLAG` and
`EVAL_ALLOWED_ROOTS` exist because step 3.4's refusals need somewhere to read
their allow list from, and because the wrapper should not assume the spelling
of planlint's JSON flag before session 1 has confirmed it.

**0.3** Install prerequisites for MCP servers *before* installing the
extension: the Toolkit validates the environment and will block you otherwise.
MCP servers need a Node or Python runtime — `npm install -g npx` for the Node
path, `uv` for the Python path. Use the Python path; that is where `planlint`
and the eval harness already live.

**0.4–0.5** Capture the version stamp and both baselines:

```bash
make baseline        # writes evidence/00-*.txt|json|md
```

**[amended]** The original inlined a shell sequence in which
`planlint validate --fail-on ERROR` returning 1 — a legitimate baseline —
would abort the capture under any `set -e`. `scripts/00-baseline.sh` records
every exit code as evidence instead of treating a nonzero one as an error, and
additionally captures `planlint validate --help` so the real spelling of the
machine-readable output flag lands in `evidence/00-planlint-flags.txt`.

The version stamp matters: the extension is the renamed AI Toolkit and the
legacy Foundry sidebar was retired, so any procedure written without one goes
stale silently.

**Done when:** version file written, dialect card captured, and both baseline
exit codes recorded (`planlint` 0 or 1, demo eval 0).

---

## Step 1 — Load exactly four models, no more

**Foundry Toolkit view → Developer Tools → Discover → Model Catalog**, using
the **Hosted by** filter. Four models across three hosting paths, so the
comparison says something about the *deployment* and not just the weights:

| Slot | Hosted by | Why |
|---|---|---|
| A | GitHub | Free-tier prototyping baseline; no Azure resource |
| B | GitHub or a publisher (OpenAI / Anthropic / Google) | Frontier reference for planner reasoning |
| C | Ollama | Your 5060 Ti / P40 box, already pulled locally |
| D | ONNX or Foundry Local | The quantized-local path, for the resource-usage read |

Practical notes that will otherwise cost you an hour:

- GitHub models prompt for GitHub credentials; code generation later needs a
  personal access token. Free-tier limits exist, and the Toolkit warns and
  links to paid usage when you hit them.
- The Ollama tab only lists models **already downloaded**, so `ollama pull
  <model>` first. Attachments are not supported for Ollama models — the
  Toolkit connects over the OpenAI-compatible endpoint.
- ONNX models must be converted to the Toolkit's model format via the model
  conversion tool before they can be added. Conversion and its profiling are
  Windows-targeted (CPU / GPU / NPU, profiled via Windows ML); it does not
  emit Hailo or Jetson artifacts. If it stalls, drop slot D rather than
  burning the week on it — and say so in the matrix.

**Done when:** all four appear under **MY RESOURCES → Models** and each opens
in the Playground.

---

## Step 2 — Three-prompt bake-off in the Playground

**Developer Tools → Build → Model Playground.** Same **System Prompt** for
every run — `configs/probes/system-prompt.md` — and fixed parameters
(temperature 0.0, top_p 1.0, max response length 800) so the comparison is not
measuring sampling noise.

Three prompts, each as its own session, fanned out with the toolbar
**Compare**:

1. **Planner** — `configs/probes/01-planner.md`. Paste a real OpenSpec
   proposal and ask for a plan review against the acceptance criteria.
2. **Verifier** — `configs/probes/02-verifier.md`. One `planlint` finding plus
   the invocation; ask whether the run passed. A model that restates a nonzero
   exit as a pass fails here, and that is the single most important signal of
   the week.
3. **Search rationale** — `configs/probes/03-search-rationale.md`. One
   `Strategos-MCTS` node expansion; ask for a justification of child selection.

**[amended]** A fourth fixture, `configs/probes/04-verifier-blocked.md`, runs
the same verifier question against an **exit 2**. Optional, and cheap in the
same Compare session. The original tested exit-2 handling only at the agent
layer in step 4, which means a model that mishandles it never shows up in the
bake-off matrix at all — and exit 2 is the state the entire wrapper
architecture is built around.

**[amended]** `make probe` runs the verifier fixture headlessly across the
GitHub and Ollama slots and saves every transcript with token counts, latency
and a deterministic three-valued screen. It does **not** replace the Playground
runs — only the Playground gives you the local resource profile — but it makes
the week's most important cell reproducible instead of remembered.

Capture for each cell: response, token count, and — for the Ollama and ONNX
slots — **Show resource usage** plus the profiling details, the only place a
local latency/VRAM read is available.

Fill in `evidence/02-bakeoff.md` from `evidence/02-bakeoff.template.md`.

**Done when:** the matrix is complete, has a named winner per prompt, and the
verifier row states which models laundered a failure into a pass.

---

## Step 3 — Local MCP server over planlint and one scorer

`planlint`'s README states its surface as "CLI with an exit code; no UI, no
MCP server." So this wrapper lives in the spike directory, not in the tool's
repo, and it stays a subprocess caller — no imports of `openspec_graph`
internals. That constraint is enforced by
`mcp_server/tests/test_seam_is_closed.py`, not by memory.

**3.1** **[amended — already built]** The scaffold exists at `mcp_server/`. Agent
Builder's **MCP Workflow → Create New MCP Server → Python** generates a sample
tool you would then delete; skip it and register what is here.

**3.2** Tool contract. The whole point is that the three-way exit code
survives the trip into a language model. Do not return a boolean.

Implementation: `mcp_server/src/foundry_spike_mcp/planlint.py`.

**[amended — the draft's sample would not run]** Three defects, all of which
land on the exit-2 path the step's own "done when" requires:

- `subprocess.run(..., timeout=N)` **raises** `TimeoutExpired`; it does not
  return a completed process. The stated refusal ("timeout maps to `BLOCKED`,
  never to `FINDINGS`") was therefore unimplemented — the call would throw and
  the model would see a framework error string with no verdict field in it.
- `json.loads(proc.stdout)` on exit 2 parses a *usage message* as JSON and
  raises. That is the deliberate-BLOCKED demo, i.e. the case that has to work.
- `os.environ["PLANLINT_TARGET"]` raises `KeyError` when unset, and a missing
  `planlint` binary raises `FileNotFoundError`. Both are BLOCKED, not crashes.

The rule that resolves all three: **an exception is not a verdict.** No code
path in `lint_openspec` raises. Every failure mode maps to BLOCKED with a
`blocked_reason`.

**[amended]** The draft mapped unrecognised exit codes to a fourth verdict,
`UNKNOWN`. Dropped. Step 4.2's instructions define agent behaviour for exactly
PASS, FINDINGS and BLOCKED; a fourth state is one the agent has no rule for,
and an agent without a rule improvises. Unmapped codes collapse to BLOCKED
with `blocked_reason: "unexpected_exit_code"`, and the raw code is still
returned, so nothing is lost by the collapse.

**3.3** `score_run(run_id)`: read-only over an existing eval-harness
`json_file` sink artifact. Per-scorer verdicts as `true` / `false` / `null`,
preserving the harness's three-valued convention where a trajectory scorer with
no trajectory yields `passed=None` and is excluded from `pass_rate`.
Collapsing `null` into `false` fabricates failures; into `true`, passes.

Implementation: `mcp_server/src/foundry_spike_mcp/scoring.py`.

**[amended]** Two additions the draft did not specify:

- When *every* scorer is null, `pass_rate` is `null` — not `0.0`, not `1.0` —
  and the run's verdict is BLOCKED. That is the aggregate form of the same
  trap and the one most likely to be papered over by an `or 0` somewhere.
- A `passed` value that is neither `true`, `false` nor `null` (say `0.73`) is
  reported as `"unreadable:0.73"` rather than coerced. Guessing a boolean here
  is the same defect wearing a different hat.

The exact sink schema is **not** pinned yet: `_collect_scorers` walks the
artifact for any object carrying a recognised verdict key and records where it
found it. Pin the real shape in session 3 against a real artifact and narrow
the walk. An unrecognised artifact returns BLOCKED, never an empty pass.

**3.4** Refusals baked into the server, not the prompt —
`mcp_server/src/foundry_spike_mcp/guards.py`:

- No verb outside `detect`, `validate`, `graph`, `rules`, `waivers`, `delta`.
- No `--force`, no writes, no `make`.
- Absolute path allow list from env; reject anything outside it. Fails closed:
  with no allow list set, only `PLANLINT_TARGET` is permitted. There is no
  wildcard.
- Subprocess timeout, and timeout maps to `BLOCKED`, never to `FINDINGS`.
- Truncate stderr; `make scan` runs the secret pass over anything bound for
  export, reusing the same pattern list the tools redact with.
- Bound and redact the *evidence*, not only the verdict. planlint's stdout is
  size-checked before it is parsed and redacted after — keys as well as values —
  so a credential inside valid JSON does not reach the model. Neither step can
  change the verdict: `findings_truncated` and `findings_parse_error` say what
  was lost, and the exit code still decides.

**[amended]** The model never supplies argv. `lint_openspec` takes two
validated scalars (`target`, `fail_on`) and builds the command line itself, so
there is no injection surface to guard — `assert_safe_argv` is a self-check
against a future edit, not a filter on the caller. Microsoft's own guidance is
to treat MCP tool descriptions and results as untrusted input; the same
applies in reverse to arguments arriving from a model.

**3.5** Register and debug: **Tool → + MCP Server → Connect to an Existing MCP
Server → Command (stdio)**. Command and args are in `mcp_server/mcp.json.example`.
Or press **F5** / **Debug in Agent Builder**. If env vars are needed the
Toolkit fails on tool-add and opens `mcp.json` for you to fill in — expect that
step rather than treating it as a bug. (`mcp.json` is gitignored: it will hold
real paths and possibly a token.)

**Done when:** both tools list in Agent Builder and return structured output
for a PASS case, a FINDINGS case, and a deliberately BLOCKED case.

```bash
make validate    # ruff, mypy, the full suite under coverage, the secret pass
make selfcheck   # all three verdicts against the real planlint -> evidence/03-mcp-selfcheck.json
```

**[amended]** Configuration and policy are separated. `config.py` reads the
environment for paths, timeouts and the severity vocabulary; `guards.py` holds
the verb allow list, the flag deny list and the credential patterns and reads
nothing. Widening what the tool may execute takes a code change, a review and a
test -- which is the point.

**[amended]** Logging goes to **stderr**, never stdout. An MCP stdio server
frames JSON-RPC on stdout, and a stray line there makes the tool disappear from
Agent Builder with no useful error. Set `FOUNDRY_SPIKE_LOG_LEVEL=DEBUG` when a
tool misbehaves inside the Toolkit and there is no other window into it;
`FOUNDRY_SPIKE_LOG_FORMAT=json` when the output is going into evidence.

---

## Step 4 — One prompt agent, then break it on purpose

**4.1** One prompt agent. Model: the step 2 planner winner. Tools:
`lint_openspec` and `score_run`, nothing else. Use a `target` variable in the
**Instructions** rather than embedding a path.

**4.2** Instructions must state the authority boundary explicitly: the tool's
exit code is the verdict; the agent reports it and may disagree in prose but
may not restate a nonzero exit as a pass; `BLOCKED` is reported as "could not
evaluate", never as pass or fail. Starting text:
`configs/probes/system-prompt.md`.

**4.3** Four probes, each saved from the **Conversations** tab. Prompts, pass
conditions and the specific failure modes to watch for:
`configs/probes/agent-probes.md`. These are lifted from the `evals/` corpus
already in `planlint` (`override-exit-code`, `omit-exit-code`,
`init-to-clear-exit-2`), so you are reusing graders you have.

**4.4** Capture the trace. Conversation detail plus the run view for at least
one probe that includes a refused or blocked call, into `traces/`. Saving a
prompt agent creates a new version in a Foundry project, so to stay at zero
Azure spend keep the agent local and export conversations manually.

**4.5** Generate the adapter candidate: **View Snippet** (single file), not
**View Code** (full project scaffold). For GitHub-hosted models take the
provider SDK over Agent Framework; it is the smaller diff when it becomes one
more model adapter behind Mango's existing interface. Park it in
`snippets/` — unmerged.

**Done when:** four conversations saved, at least one trace showing a
`BLOCKED` or refused call, and one code snippet parked in the spike repo.

**[amended]** Promote each capture before citing it:
`make promote RUN_DIR=traces/raw/<dir>`. It runs the secret pass and refuses to
copy anything with a hit. `traces/raw/` is gitignored, so an un-promoted capture
is not in the repository and a matrix cell pointing at one dead-ends.

---

## Step 5 — Write the verdict before you close the week

`evidence/05-verdict.md`, from `evidence/05-verdict.template.md`. Fields:

- Toolkit version and date.
- Bake-off winner per prompt, and which models failed the verifier probe.
- Whether the MCP wrapper preserved 0/1/2 and `true`/`false`/`null` end to end.
- Whether any probe required weakening the tool contract to make the agent
  behave. If yes, that is a stop signal, not a tuning task.
- One-line recommendation: proceed to a Week 2 hosted twin, or stop at local
  bake-off bench.
- Estimated Week 2 cost and identity work: subscription, Foundry project,
  Foundry User role, and a reachable **remote** MCP endpoint — a hosted agent
  cannot call your stdio server. A private one needs a virtual network with a
  dedicated MCP subnet, in practice Container Apps with internal-only ingress.

### Stop conditions that end the spike early, with the week still counted as a success

1. **No model passes the verifier probe.** Then Foundry adds nothing to
   governance and stays a bake-off bench only.
2. **The wrapper cannot preserve exit-2 semantics without special-casing.**
   Architectural signal; do not patch around it.
3. **Wrapping the scorer requires importing eval-harness internals** rather
   than reading sink output. The seam is wrong and the eval plane stays closed
   for now.

**[amended] Do not let condition 2 fire on a false positive.** Catching
`TimeoutExpired`, a missing binary, and unparsable stdout so that each maps to
BLOCKED is ordinary robustness — it is what makes exit-2 semantics *work*.
Condition 2 fires when BLOCKED can only be produced by reading planlint's
stderr strings, pattern-matching its human-readable messages, or anything else
that would break on its next release. Condition 3 has a test:
`mcp_server/tests/test_seam_is_closed.py` fails if the wrapper starts importing what
it is supposed to be calling.

---

## Session plan

| Session | Steps | Output |
|---|---|---|
| 1 | 0 | Version stamp, baselines, dialect card |
| 2 | 1–2 | Four models loaded, bake-off matrix |
| 3 | 3.1–3.3 | MCP server pinned to the real planlint and sink schema |
| 4 | 3.4–3.5, 4.1–4.2 | Server registered, agent configured |
| 5 | 4.3–4.5, 5 | Four probe traces, snippet, verdict row |

**[amended]** Session 3's work has shifted. The server is written and tested;
what session 3 actually does is point it at the real `planlint` build and a
real sink artifact, confirm the JSON flag spelling, narrow `_collect_scorers`
to the pinned schema, and run `make selfcheck`. That is a smaller session — use
the slack on the bake-off, which is the part that needs judgement.

---

## What Week 1 deliberately does not do

No hosted deploy, no Azure project, no trace export to Foundry, no golden-task
run, no edits to `Mango_Code_Agent-Harness` or `planlint`, and no LangFuse
changes. Those are Week 2 decisions and they are gated on the Step 5 verdict.

Also not this week, and worth naming so it does not creep in: **Foundry is not
the eval source of truth.** Its built-in evaluators are F1, relevance,
similarity and coherence — reference-similarity metrics, not an
isotonic/ECE/Wilson calibration stack — and an in-vendor judge conflicts with
the verifier-outside-the-model-under-test rule. The harness keeps the
governance kernel.
