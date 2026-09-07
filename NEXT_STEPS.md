# Next steps

Rewritten 2026-09-06 against a four-discipline review of `main` and of the open
pull request #5. The evidence behind every item is in
[`docs/roadmap/2026-09-06-review.md`](docs/roadmap/2026-09-06-review.md).

**Status: Tracks A, D, and E are done.** Track E (Windows platform-parity,
branch `h`) closed 12 test failures that were Windows-local and invisible to CI.
It also established the regression guard layer and shared cross-platform test
fixtures. What is left is Track B, which is a decision about someone else's pull
request, and Track C, which needs a human in front of VS Code with the real
binaries. Neither can be done from here.

---

## Track E — Windows platform-parity (branch h, complete 2026-09-06)

Branch `h` closed 12 test failures that existed on Windows but were invisible to
the Linux-only CI. The root causes and their fixes:

| ID | Root cause | Fix |
|---|---|---|
| D-01 | Shebang scripts are not executable on Windows (`WinError 193`) | `.bat` launchers on Windows, shebang on POSIX; encapsulated in `make_stub` fixture |
| D-02a/b | `sys.stdout.write(str)` raises `UnicodeEncodeError` on Windows `cp1252` | All fake scripts write to `sys.stdout.buffer`; `.bat` sets `PYTHONUTF8=1` |
| D-02c | POSIX-signal tests used `os.kill(pid, SIGKILL)` which raises on Windows | `@pytest.mark.skipif(win32)` with rationale and coverage note |
| D-03 | `mypy` `attr-defined` on `os.killpg` (runtime-guarded but mypy can't track `hasattr`) | `# type: ignore[attr-defined]` with explanatory comment |

**Deliverables that landed:**

- `tests/regression/` — 16-test regression guard layer (verbs from `ALLOWED_VERBS`, not hardcoded)
- `tests/conftest.py` — `make_stub` and `spec_repo` shared fixtures (DRY, single source of truth)
- `pytest.ini` — `regression` and `aqa` markers registered
- `Makefile` — `test-regression`, `aqa`, `test-7layers` and all 7 individual layer targets
- `.github/workflows/ci.yml` — `windows-latest` in `contract` job matrix; coverage floor uses `pyproject.toml`
- `CHANGELOG.md` — full entry for D-01/D-02/D-03 and the new deliverables

**Open items from E (low priority):**

| # | Item | Owner |
|---|---|---|
| E1 | Add `tests/aqa/` acceptance test layer (AQA marker is registered but no tests yet) | SQE |
| E2 | Consider adding Windows to the `transport` job (SDK + server startup on Windows) | SWE |

---

## Where this actually stands

PR #5 has landed, so `main` now carries the probe decomposition, the layered
test suites, the session tracker, a trace index, an MIT licence and the week's
verdict. This branch carries the review that preceded it and the defect fixes
that came out of that review.

What the merge does **not** change is the evidence position, and it is worth
being exact rather than gracious about it. `evidence/03-mcp-selfcheck.json` on
`main` still reads `all_expected: false`; `evidence/02-bakeoff.md` — the path
the decision record cites — still does not exist, only its template; and three
of four model slots still have no data. The verdict is written. It is not yet
supported by what is committed underneath it.

**The good news is the size of the gap.** Turning that into a defensible
verdict — in either direction — is roughly half a day of capture work, listed
as Track C. It is the only work on this page the week actually asked for.

## Operator pre-work

| # | Action | Why now |
|---|---|---|
| 1 | **Decide whether this repo stays public.** | It accumulates planlint findings with real spec paths, pasted OpenSpec proposals, MCTS node dumps and model transcripts — from source repos that are private. The licence question is now answered (MIT, landed with PR #5); this one is not. |
| 2 | `cp .env.example .env` and fill it in | Nothing runs without `PLANLINT_TARGET` and an allow list. Both fail closed. |
| 3 | `make setup && make test` | Confirms the floor works on your machine before a session is on the clock. |
| 4 | `make hooks` | Installs the pre-commit secret gate. |

---

## Track A — Two live risks, before anything else

About twenty minutes in total. Do these first because one of them is a
credential path.

| # | Action | Why | Owner |
|---|---|---|---|
| A1 | **Done.** `.gitignore` matches `mcp.json` at any depth | The rule named the pre-rename path, so the file the runbook tells you to fill with real paths and possibly a token was committable. Matched by name now, so the next rename cannot reopen it, with a test over three locations. | SWE |
| A2 | **Open, and not doable from a commit.** Set the repository default branch to `main` | It is still `claude/foundry-toolkit-spike-prep-d92qfh`, the stale prep branch that PR #1 was merged *from*. | owner |
| A3 | **Open.** Then close dependabot PRs #2, #3, #4 | All three target that stale branch, because `dependabot.yml` sets no `target-branch` and inherits the default. Merging them changes nothing on `main`. Once A2 lands they regenerate against the right base. | SWE |
| A4 | **Open.** Decide whether the repository stays public | The licence is settled; the visibility question is not, and it gates the capture work in Track C because that work commits transcripts derived from private repositories. | owner |

A2 is the root cause of A3, and it costs more than tidiness: CodeRabbit only
auto-reviews pull requests whose base is the repository default, so every PR
targeting `main` currently goes unreviewed by it. It also means any pull
request opened without an explicit base targets a branch nobody develops on.

## What PR #5 closed, and what it did not

Credit where it is due, and precision where it matters. These landed and hold:
the `verifier_probe.py` decomposition, `traces/index.md`, `session_tracker.md`,
an MIT `LICENSE`, `promote_trace.py --dest-root`, and the layered test suites.

These are recorded as fixed and are not:

| Claim | State after the merge |
|---|---|
| "`evidence/05-verdict.md` was empty — **fixed**" | The file exists. Its exit-1 contract row still cites a self-check whose own `all_expected` is `false`, three of four model slots still have no data, and four agent probes are still marked passed without having been run. Written is not the same as supported. |
| "coverage enforced with `--fail-under=80`" | The floor is 90 now, measured with the SDK installed so `server.py` is actually in the denominator. Under the old arrangement that file scored 0% and the gate could not see the one thing it exists to guard. |
| "`evidence/02-bakeoff.md`" | Still absent; only `02-bakeoff.template.md` exists, and the decision record cites the former. |

Everything else from the earlier findings list — the escaped `RecursionError`,
the unstable envelope, the unreachable verbs, the namespace shadowing, the
scanner gaps — is genuinely closed.

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
| D1 | **Done.** A NUL byte in a model-supplied path escaped both tools as `ValueError` | Caught in `guards.check_target` and mapped to `BLOCKED / guard_rejected: invalid_path`. The same call in `config._abs_paths` escaped every `except ConfigError` and is now a `ConfigError` | landed |
| D2 | **Done.** A findings payload that parsed as valid JSON was neither truncated nor redacted | Bounded on the encoded byte length before parsing, then redacted structurally; `findings_truncated` added to every envelope | landed |
| D3 | **Done.** `scan_evidence.py` ended in a traceback on an absolute out-of-tree path | One reusable display helper: relative inside the repo, absolute outside. Still fails closed | landed |

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

- **D5 — Done. Policy is not configuration, now tested.** This is the repository's one
  stated architectural opinion and it has no test. A parametrized test that sets
  plausible environment variables and asserts the refusals are unchanged, plus a
  static check that `guards.py` imports no `os`, is about ten lines. *(SQE, 20
  min.)*
- **D6 — Done. `coverage`, `ruff` and `mypy` added to the `[dev]` extras.** The extras
  list is just `pytest`, so `make validate` is red immediately after `make
  setup` on a fresh clone, on three counts. CI installs all three separately,
  which is how this survived. *(SWE, 5 min.)*
- **D7 — Done. The declared SDK floor is now exercised.** `mcp>=1.2` is
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
| `mcp.json` is gitignored | **Now true.** See A1 |
| `make scan` reaches `snippets/` | **Fixed**, and `snippets/README.md` no longer says the opposite |
| NUL byte escapes as an exception | **Fixed.** See D1 |
| Findings payload unbounded and unredacted | **Fixed.** See D2 |
| Declared SDK floor `mcp>=1.2` cannot run its own smoke suite | **Fixed.** See D7 |
| Scanner crashes out of tree | **Fixed.** See D3 |
| "Policy is not configuration" untested | **Fixed.** See D5 |
| `make validate` red after `make setup` | **Fixed.** See D6 |
| Outcome vocabulary differs across three documents | **Fixed.** All three now say keep as sidecar / bench only / drop |
| Criterion 4 has no field in the verdict template | **Fixed.** Section 2b asks for two timings and a named baseline |
| Actions on floating major tags | **Open, accepted** |
| No dependency lockfile | **Open, accepted** |
| TOCTOU between check and subprocess | **Open, accepted** |
| A sink artifact that is not valid UTF-8 raised out of `score_run` | **Fixed.** Found while testing D1; `UnicodeDecodeError` is a sibling of `JSONDecodeError`, not a parent |
| `redact_structure` dropped evidence on a key collision | **Fixed.** Found by the contract review of the D2 commit |

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
