# Next steps

Rewritten 2026-09-06 against a four-discipline review of `main` and of the open
pull request #5. The evidence behind every item is in
[`docs/roadmap/2026-09-06-review.md`](docs/roadmap/2026-09-06-review.md).

---

## Where this actually stands

`main` is green and carries a well-tested three-valued contract — the artifact
this week was supposed to produce a decision about. The decision itself exists
only on an unmerged pull request, and it recommends spending money on a week 2
while citing a self-check file whose own summary field reads
`all_expected: false`.

That is the whole situation. The scaffolding works. The paperwork does not yet
support the recommendation it makes. Everything below is ordered by that.

**The good news is the size of the gap.** Turning an unsupportable "proceed"
into a defensible verdict — in either direction — is roughly half a day of
capture work, listed as Track C. It is the only work on this page the week
actually asked for, and it is smaller than the pull request currently sitting
in front of it.

---

## Track A — Two live risks, before anything else

About twenty minutes in total. Do these first because one of them is a
credential path.

| # | Action | Why | Owner |
|---|---|---|---|
| A1 | `.gitignore`: replace `mcp/mcp.json` with `mcp_server/mcp.json` and `**/mcp.json` | The directory was renamed; `git check-ignore mcp_server/mcp.json` returns nothing. The file the runbook tells you to fill with real paths and possibly a token is committable today. PR #5 does not fix this. | SWE |
| A2 | Set the repository default branch to `main` | It is still `claude/foundry-toolkit-spike-prep-d92qfh`, the stale prep branch that PR #1 was merged *from*. | SWE |
| A3 | Then close dependabot PRs #2, #3, #4 | All three target that stale branch, because `dependabot.yml` sets no `target-branch` and inherits the default. Merging them changes nothing on `main`. Once A2 lands they regenerate against the right base. | SWE |
| A4 | Decide LICENSE, or make the repository private | Public with no licence is all-rights-reserved: nobody may reuse it, including a future you. PR #5 proposes MIT. This is the owner's call and it gates everything else about publishing captures. | VP / owner |

A2 is the root cause of A3 and was already flagged in the previous revision of
this file. It is still open, and it means every new pull request opened without
an explicit base targets a branch nobody is developing on.

A4 is a decision, not a task. It has been open since the first review and it
gates the capture work in Track C, because that work commits model transcripts
derived from private repositories.

---

## Track B — Split PR #5

**Recommendation: do not merge as-is.** Three unrelated kinds of change in 63
files, and the week's actual deliverable is trapped behind the other two. Its
head commit is not green.

Split into three, in this order:

**B1 — Evidence (merge first).** The `evidence/00-*` captures, the self-check
JSON, the trace and its index, the session tracker, the verdict, the two filled
probe fixtures, the `__main__.py` self-check change, `promote_trace.py
--dest-root`, and the `.gitignore` additions.

Corrections required before it lands:
- Copy the filled matrix to `evidence/02-bakeoff.md`. The decision record cites
  that path and it does not exist; the template was filled in place.
- Untick the four completion boxes on a matrix with six blank cells, or fill the
  cells. The template's own rule is that "dropped" is an answer and blank is not.
- Correct the verdict rows that claim results for probes that were not run, and
  the resource-usage row that reports a VRAM figure no script measures and a
  latency figure that disagrees with the committed measurement.
- Scrub the Windows user path from `evidence/03-mcp-selfcheck.json`.

**B2 — The scoring contract change (hold).** `scoring.py` now requires a root
`results` list and blocks the entire run if any single record is malformed.
Seven contract tests were deleted to match. The previous revision of this file
made pinning conditional on seeing a real sink artifact, and none exists — the
demo eval aborts before writing one, because the harness refuses to gate on a
judge with no calibration artifact.

Pinning a guessed schema converts "we read something odd, here is what we found"
into "refused, no data." Hold this until Track C0 produces an artifact, then
land it with a `decisions/0002` entry recording the pinned shape.

The strongest reason to hold is one of the deleted tests:
`test_top_level_result_summary_does_not_fabricate_a_pass`. That is the
regression test for a real bug in this repository's history, where a top-level
summary field was counted as a scorer and a run that should have been BLOCKED
returned `PASS` with `pass_rate: 1.0`. Deleting the regression test for a
fabricated pass, in a repository whose subject is fabricated passes, is a
bigger problem than the missing decision record.

**B3 — Scaffolding (trim hard, or drop).** The probe decomposition is defensible
on its own merits. The seven new test directories are not: about a third of the
90 net-new tests exercise new behaviour, and the rest assert that Python is at
least 3.10, that files exist, that functions are callable, or re-parametrise
cases already covered in `test_guards.py`.

If this lands at all: delete the sanity layer, fold the non-duplicate cases into
the existing files, restore the coverage floor to 85 (both the Makefile and CI
now pass `--fail-under=80`, overriding `pyproject.toml`), drop the UTF-16
`requirements.txt`, reconcile every published test count to one measured number
with its environment stated, and remove the `sys.path` mutation that `scoring.py`
now performs on itself in an import fallback — a tool module should not repair
its own import path, and that fallback also swallows `ConfigError`.

---

## Track C — Make the verdict decidable

**This is the week's actual work: roughly half a day.** Nothing else on this
page substitutes for it. C4 needs VS Code and Agent Builder in front of a human,
so it does not compress the way the others do, and 45 minutes for it is
optimistic — the runbook treats those probes as most of a session.

| # | Action | Effort | Owner |
|---|---|---|---|
| C0 | Get one real eval-harness sink artifact by supplying the calibration artifact id the demo config is missing, then run `score_run` against it | 45 min | SWE |
| C1 | Build a target that genuinely produces findings at or above the threshold, and re-run `make selfcheck` until `all_expected` is `true` | 30 min | SWE |
| C2 | Run the exit-2 fixture against at least one model and promote the trace | 20 min | SWE |
| C3 | Run `make probe` across a second and third slot so the verifier row has more than one model in it | 30 min | SWE |
| C4 | Run the four agent probes and save the conversations, including one BLOCKED or refused call | 45 min, optimistic | SWE |
| C5 | Export the adapter snippet into `snippets/`, unmerged | 15 min | SWE |
| C6 | Rewrite the verdict against what C0–C5 actually produced | 45 min | VP / owner |

C1 is the one that matters most. Exit 1 is the only leg of the three-valued
contract never demonstrated end to end against the real binary, and it is the
row the current verdict marks as verified. The wrapper is almost certainly
correct — the mapping is unit-tested and exit 0 and exit 2 both check out
live — but "almost certainly correct" is not what the document claims.

C0 unblocks more than it looks like. `score_run` is half the tool surface and
appears in no evidence file at all, because the demo eval aborts before writing
a sink artifact: the harness refuses to gate on a judge with no calibration
artifact id. Until one artifact exists, the scorer's `null` handling is unproven
outside unit tests and the schema pin in PR #5 has nothing to pin against. If
C0 turns out to need harness changes rather than a config field, that is
runbook stop condition 3 and it should be recorded as one, not worked around.

**If C3 and C4 cannot be afforded, that is fine, and it is not a failure.** The
honest verdict then reads *bake-off bench only: one model held the verifier
probe, the comparative claim is unsupported.* The runbook counts stopping on a
stop condition as a success. What is not available is "proceed, spend the money"
on one model, one prompt, one run.

Note for C6: the decision record's fourth criterion — that the Playground gives
a faster read than the existing bench — has no field anywhere in the verdict
template, and no evidence. Either add the field and answer it, or record it as
unanswered. It is the criterion the decision record itself flags as most likely
to be answered generously, which is a good reason not to leave it implicit.

---

## Track D — The four reproduced defects

All four were reproduced against the tree. Together they are under half a day,
and all of them sit on code that would carry into a hosted week 2.

| # | Defect | Fix | Effort |
|---|---|---|---|
| D1 | A NUL byte in a model-supplied path escapes `lint_openspec` and `score_run` as `ValueError`, so the model sees a protocol error with no verdict field | Catch `ValueError` in `guards.check_target`, map to `BLOCKED / guard_rejected: invalid_path` | 30 min |
| D2 | A findings payload that parses as valid JSON is neither truncated nor redacted; both controls live in the unparsable branch only | Bound and redact the parsed payload; set a `findings_truncated` flag | 30 min |
| D3 | `scripts/scan_evidence.py` on an absolute path outside the repository ends in a traceback | Handle the out-of-tree case | 20 min |

D1 is the only true contract breach on the list: it is the single place where
*an exception is not a verdict* does not hold.

D2 is more than a size problem. With the limit set to 100 bytes a valid payload
came back at 4.5 MB, and because `guards.redact` runs in the same branch as the
truncation, a credential inside valid JSON output reaches the model and any
trace built from it unscrubbed. `SECURITY.md` lists that surface as controlled.
It is controlled only on the unparsable path.

D3 is a cosmetic fix, not a hole in the gate. Paths are joined against the
repository root, so only an absolute out-of-tree argument reaches the crash, and
it exits non-zero either way.

**Not on this list, because PR #5 already fixes it:** the self-check's handling
of an unset `PLANLINT_ALLOWED_ROOTS`. On `main` it replaces the target fallback
with its scratch directory, so the step-3 self-check cannot pass when the
variable is left unset. The branch fixes it with `dataclasses.replace` and an
injected config, which is the right shape. A previous draft of this plan
scheduled 45 minutes to redo work already done; that was wrong, and it is
another reason to land Track B1 promptly.

Two more, cheap:

- **D5 — Test that policy is not configuration.** This is the repository's one
  stated architectural opinion and it has no test. A parametrized test that sets
  plausible environment variables and asserts the refusals are unchanged, plus a
  static check that `guards.py` imports no `os`, is about ten lines. *(SQE, 20
  min.)*
- **D6 — Add `coverage`, `ruff` and `mypy` to the `[dev]` extras.** The extras
  list is just `pytest`, so `make validate` is red immediately after `make
  setup` on a fresh clone, on three counts. CI installs all three separately,
  which is how this survived. *(SWE, 5 min.)*
- **D7 — Reconcile the declared SDK floor with what is tested.** `mcp>=1.2` is
  advertised, but the smoke suite resolves a 2.x module path at import time, so
  on mcp 1.2.0 it errors during collection under `REQUIRE_MCP=1` and skips
  silently without it. Either fix the loader test and add a 1.x leg to CI, or
  narrow the floor to what is actually exercised. *(SQE, 30 min.)*

---

## Track E — Gated entirely on the verdict

Do none of this before Track C is written up.

**If the verdict is "bench only":** archive the repository, copy the matrix into
the decision log, close `decisions/0001`. The tool contract and its suite are
worth keeping as a reference for how a three-valued seam should look. That is a
real outcome, not a consolation prize.

**If the verdict is "proceed":** the stdio server does not carry. A hosted agent
consumes *remote* MCP endpoints, and a private one needs a virtual network with
a dedicated MCP subnet. What carries is the contract, and the seams for it
mostly exist already — `run_verb(config=)` and `score_run(config=)` take
injected configuration today; `build_server()` should too.

What a hosted deployment will hit first, in order:

1. **Process-global state.** Configuration is re-read from `os.environ` per call
   and logging configures itself at import. A long-lived multi-tenant process
   wants configuration injected, not ambient.
2. **No concurrency cap.** N tool calls means N `planlint` processes, each with a
   120-second timeout and no ceiling.
3. **Grandchildren survive a timeout.** `subprocess.run(timeout=)` kills the
   direct child only. Use `start_new_session=True` and kill the process group.
4. **Unbounded payloads** (D3) stop being a local memory question and become a
   wire and context question.
5. **The identity model is "absolute path under an absolute root."** There is no
   caller or tenant identity in the allow list, and the target repository must
   be on the server's disk.

Budget separately for the Azure subscription, the Foundry project and roles, the
reachable remote endpoint and its identity work, trace egress as a decision
rather than a toggle, and triage capacity for the `Agents` backlog that a second
eval plane competes with.

---

## Do not do

Named explicitly, because the repository's failure mode is scaffolding crowding
out the deliverable.

- No further CI, container, or type-checker work. The four-job split is well
  designed; leave it alone apart from restoring the coverage floor and
  installing the SDK in the coverage job so `server.py` counts.
- No lockfile. One direct dependency, bounded. The maintenance cost is real and
  the payoff for a five-session spike is not.
- No TOCTOU work. Documented, accepted, and closing it needs an API `planlint`
  does not offer.
- No SHA-pinning of Actions until this workflow is copied somewhere with write
  permissions or secrets.
- No new test layers. Coverage is 88–92% depending on whether the SDK is
  installed. The gap is specific invariants, listed as D5, not volume.
- No slot D. The runbook already permits dropping it and PR #5 dropped it.

---

## Open findings, current

Replaces the previous table, which recorded several items as fixed that are not.

| Finding | State |
|---|---|
| `_selfcheck` and `PLANLINT_ALLOWED_ROOTS` | **Fixed on PR #5**, open on `main`. Also mis-described: it narrows the guard, it does not widen it |
| `traces/` has no index | **Fixed on PR #5**, not on `main` |
| No session tracker | **Fixed on PR #5**, not on `main` |
| Evidence cites gitignored paths | **Drift, not a risk.** The template points at `traces/raw/`, which is gitignored by design; the runbook says to promote captures out of it before citing them |
| `mcp.json` is gitignored | **False, and a live risk.** See A1 |
| `make scan` reaches `snippets/` | **Fixed in code, stale in `snippets/README.md`**, which still says the opposite |
| NUL byte escapes as an exception | **Open.** See D1 |
| Findings payload unbounded and unredacted | **Open.** See D3 |
| Declared SDK floor `mcp>=1.2` cannot run its own smoke suite | **Open.** See D7 |
| Scanner crashes out of tree | **Open.** See D4 |
| "Policy is not configuration" untested | **Open.** See D5 |
| `make validate` red after `make setup` | **Open.** See D6 |
| Outcome vocabulary differs across three documents | **Open.** Keep / bench-only / drop, versus proceed / stop at bench, versus sidecar or not |
| Criterion 4 has no field in the verdict template | **Open.** See C5 |
| Actions on floating major tags | **Open, accepted** |
| No dependency lockfile | **Open, accepted** |
| TOCTOU between check and subprocess | **Open, accepted** |

---

## Three things that stay true either way

Unchanged from the previous revision, because nothing in this review disturbs
them.

Foundry is not the eval source of truth: its built-in evaluators are
reference-similarity metrics, and an in-vendor judge conflicts with the
verifier-outside-the-model-under-test rule. Model Conversion is Windows-targeted
and emits neither Hailo nor Jetson artifacts, so the edge repositories keep their
pipelines. And the `command_actions.py` allow list stays authoritative — MCP tool
descriptions and results are untrusted input, so anything Foundry adds there is
defence in depth.
