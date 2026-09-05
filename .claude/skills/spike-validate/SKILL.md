---
name: spike-validate
description: Run the full pre-PR validation gauntlet for the Foundry week-1 spike - ruff, mypy, the contract suite, the server smoke test, and the secret pass - and report what failed. Use before any commit that touches mcp_server/, scripts/, or configs/probes/, when asked to validate, check, or verify the repo, or when preparing a pull request.
---

# Pre-PR validation

Run these in order and **stop at the first failure**. Each one is cheap and
each one catches a different class of defect; running them out of order wastes
time debugging a type error that a lint failure already explained.

```bash
ruff check .              # style, imports, bandit rules
mypy                      # types across mcp_server/src and scripts
python -m pytest -q       # contract suite (no SDK needed) + smoke (skips without it)
make scan                 # credential pass over evidence/ traces/ snippets/ configs/
```

With the SDK installed, also:

```bash
REQUIRE_MCP=1 python -m pytest mcp_server/tests/test_server_smoke.py -q
```

`REQUIRE_MCP=1` turns the smoke test's skip into a hard failure. Without it a
missing SDK is silently tolerated, which is exactly how a server that could not
import once shipped under a green tick.

## What a failure means

| Failure | What it is telling you |
|---|---|
| `ruff` S-rules | A security lint fired. Fix it or justify the `noqa` with a reason, never a bare code. |
| `mypy` | A real type mismatch. The config is not `strict`; what it does check, it checks because it caught something. |
| `test_planlint_contract` | The three-way exit code no longer survives. This is runbook stop condition 2 territory — read the failure before assuming it is the test that is wrong. |
| `test_scoring` | `true`/`false`/`null` collapsed somewhere, or `pass_rate` counted a null. |
| `test_seam_is_closed` | The wrapper started importing what it is supposed to be calling. Stop condition 3. |
| `test_logging` | Something writes to stdout. On a stdio MCP server that corrupts the protocol channel. |
| `test_server_smoke` | The transport is broken even though the logic is fine. |
| `make scan` | A credential is in a file bound for the repository. Redact before doing anything else. |

## Rules that are not negotiable

These are the invariants the whole spike exists to protect. If a change makes
one of them fail, the change is wrong — not the test.

1. **An exception is not a verdict.** No path in `lint_openspec` or `score_run`
   may raise. Every failure maps to `BLOCKED` with a `blocked_reason`.
2. **The exit code is the verdict; the payload is evidence.** An unparsable
   payload never changes a verdict.
3. **Three verdicts, never four.** `PASS`, `FINDINGS`, `BLOCKED`. A fourth state
   is one the agent has no rule for.
4. **`null` is a scorer verdict.** Never coerce it to a boolean; never count it
   in `pass_rate`.
5. **Policy stays in code.** Verb allow list, flag deny list and credential
   patterns live in `guards.py` and are not environment-configurable.
6. **stdout belongs to JSON-RPC.** Logging goes to stderr.

## Do not

- Do not add `# type: ignore` or `# noqa` without a reason on the same line.
- Do not weaken a test to make a change pass. If a probe only passes after the
  tool contract is loosened, that is runbook step 5's stop signal, and it gets
  recorded in `evidence/05-verdict.md` rather than fixed.
- Do not commit anything under `traces/raw/` — promote it with
  `python3 scripts/promote_trace.py <dir>`, which refuses on a scan hit.
