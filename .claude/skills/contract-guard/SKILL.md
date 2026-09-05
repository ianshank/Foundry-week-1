---
name: contract-guard
description: The three-valued verdict contract for the Foundry spike's MCP tools - what PASS, FINDINGS, BLOCKED and null mean, and which changes are defects rather than improvements. Use when editing mcp_server/src/foundry_spike_mcp/, adding a tool, changing a return shape, reviewing a diff that touches verdicts or scorers, or deciding whether a failing contract test is wrong.
---

# The contract

`planlint` exits 0, 1, or 2, and those mean three different things:

| exit | verdict | means |
|---|---|---|
| 0 | `PASS` | ran, found nothing at or above the threshold |
| 1 | `FINDINGS` | ran, found problems |
| 2 | `BLOCKED` | **could not look** — a precondition or usage error |

Exit 2 is not a pass and it is not a spec failure. Everything in
`mcp_server/` exists so that if this distinction is lost, it was lost by the
*model* and not by the wrapper.

Scorers are three-valued the same way: `true`, `false`, `null`. `null` means
the scorer produced no verdict — a trajectory scorer with no trajectory — and
is excluded from `pass_rate`. Collapsing it into `false` fabricates failures;
into `true`, passes.

## Invariants

**An exception is not a verdict.** If a tool raises, the model sees a framework
error string with no verdict field, and a model asked to summarise that will
guess. Every failure maps to `BLOCKED` with a `blocked_reason`. This includes
the ones that are easy to miss: `subprocess.run(timeout=)` *raises*
`TimeoutExpired`; `json.loads` raises `RecursionError` (not `JSONDecodeError`)
on deep input; a missing binary raises `FileNotFoundError`.

**The exit code is the verdict. The payload is evidence.** An unparsable
payload downgrades the evidence and never the verdict. Exit 1 with garbage on
stdout is still `FINDINGS`.

**Three verdicts, never four.** Step 4.2 of the runbook defines agent behaviour
for exactly `PASS`, `FINDINGS`, `BLOCKED`. An unmapped exit code collapses to
`BLOCKED` with `blocked_reason: unexpected_exit_code` and the raw code
preserved — never to a new state the agent has no rule for.

**The result envelope is stable.** Every return carries the same keys whether
the run reached planlint or was refused before it started.

**Refusals are refusals.** A verdict-carrying object must be nameable before it
counts as a scorer; an unnamed field on the artifact root is recorded in
`ignored`, not counted. Nothing is silently dropped and nothing is guessed.

**Policy is not configuration.** `guards.ALLOWED_VERBS`, `DENIED_FLAGS` and
`SECRET_PATTERNS` are hard-coded on purpose. An allow list widened by an
environment variable is not an allow list. Deployment settings — paths,
timeouts, the severity vocabulary — live in `config.py` and come from the
environment.

**stdout is the protocol.** An MCP stdio server frames JSON-RPC on stdout. Log
to stderr via `logging_setup`, never `print()`.

## Changes that are defects, not improvements

- Returning a boolean from `lint_openspec`.
- Adding an `UNKNOWN` or fourth verdict.
- `pass_rate` returning `0.0` when nothing was scored (it must be `null`).
- Coercing a non-boolean `passed` value into a boolean.
- Catching an exception and returning `PASS`, or letting one escape at all.
- Importing `openspec_graph`, `planlint` or `eval_harness` — the wrapper is a
  subprocess and file caller. `test_seam_is_closed.py` fails on this, and it is
  runbook stop condition 3, not a lint.
- Making a guard configurable to get a probe to pass.

## If a contract test fails

Read it as a report about the change, not about the test. The one legitimate
reason to edit a contract test is that the *contract itself* changed, which is
a decision that belongs in `decisions/` and in `evidence/05-verdict.md` — not
in a commit that was trying to do something else.
