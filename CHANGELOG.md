# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are spike milestones, not releases — nothing here is published.

Entries record *why* a change happened where the reason is not obvious from
the diff, because this repository's whole subject is a distinction that is easy
to lose by accident.

## [Unreleased]

### Fixed (Windows platform-parity — branch h)

- **D-01: Shebang scripts are not executable on Windows (WinError 193).** All
  fake `planlint` binaries in the test fixtures used `#!/usr/bin/env python3`
  scripts with `chmod(0o755)` — the standard POSIX pattern. On Windows,
  `subprocess.Popen` cannot execute a shebang script directly and raises
  `OSError: [WinError 193] %1 is not a valid Win32 application`. Every stub now
  writes a `.bat` launcher on Windows and a shebang script on POSIX, keyed on
  `sys.platform`. The pattern is encapsulated in the `make_stub` fixture in
  `tests/conftest.py` so future tests share one canonical implementation.

- **D-02: `sys.stdout.write` raises `UnicodeEncodeError` on Windows (cp1252).**
  Fake scripts writing non-ASCII text (CJK characters for the byte-ceiling
  tests) called `sys.stdout.write(str)`. Windows sets the console codepage to
  cp1252 by default, which cannot encode CJK. The write raises before any bytes
  reach the subprocess pipe, producing empty stdout and a false PASS in the
  truncation tests. All fake scripts now write to `sys.stdout.buffer` (binary
  buffer, UTF-8 explicit). The `.bat` launcher also sets `PYTHONUTF8=1` to
  force UTF-8 stdio for all Python processes spawned on Windows.

- **D-03: `mypy` reports `attr-defined` error on `os.killpg` (POSIX-only).**
  `_CAN_KILL_GROUPS = hasattr(os, "killpg")` correctly guards the POSIX call
  at runtime, but mypy cannot track `hasattr` narrowing and emits an error on
  Windows-targeted mypy runs. Added `# type: ignore[attr-defined]` with
  explanatory comment.

- **POSIX-signal tests skip on Windows.** `test_a_process_killed_by_a_signal`
  used `os.kill(pid, signal.SIGKILL)` — a POSIX-only system call. On Windows
  it raises `OSError`. The test is now decorated with
  `@pytest.mark.skipif(sys.platform == "win32", ...)` with a rationale
  explaining that the negative-returncode branch is covered by in-process
  exit-code parametrize tests that don't require a real signal.

### Added (branch h)

- **`tests/regression/` — regression guard layer.** A new test layer whose
  invariant is: every test here corresponds to a specific defect that was once
  broken and fixed. A failure means a fix was reverted. Covers D-01/D-02
  (platform parity), F4 (RecursionError containment), F5 (stable envelope
  shape), F9 (all allowed verbs reachable), F14 (coverage gate). Verb list
  parametrize imports from `guards.ALLOWED_VERBS` — the source of truth —
  rather than a hardcoded list that can drift.

- **`make_stub` and `spec_repo` fixtures in `tests/conftest.py`.** The
  cross-platform stub factory and the minimal openspec repo tree are now shared
  fixtures available to every test layer. Tests that previously duplicated this
  logic (`tests/regression/`, `tests/integration/`) now consume the fixture.

- **`pytest.ini` — registered `regression` and `aqa` markers.** An
  unregistered marker emits a `PytestUnknownMarkWarning` on every collection.
  Both markers are now declared with descriptions.

- **`Makefile` — `test-regression`, `aqa`, and `test-7layers` targets.**
  `make test-regression` runs only the regression guard layer. `make aqa` runs
  tests marked `@pytest.mark.aqa`. `make test-7layers` chains all eight layers
  (7 functional + regression) in dependency order. All 7-layer targets were
  also added (unit, integration, functional, e2e, journey, security, sanity)
  to make the previously undocumented Makefile `.PHONY` entries actually run.

### Changed (branch h)

- **CI `contract` job now runs on `windows-latest` in addition to
  `ubuntu-latest`.** The 12 failures fixed in branch h were all Windows-local.
  CI was green throughout because it only tested on Linux. The Windows leg
  closes this blind spot with `python-version: "3.12"` only (the floor, 3.10,
  is Ubuntu-only to keep costs bounded). The shellcheck step is skipped on
  Windows since `mapfile` and `bash -n` are POSIX-only.

- **CI coverage step no longer hard-codes `--fail-under=80`.** The quality job
  previously overrode `pyproject.toml`'s `fail_under = 90` with a lower CLI
  flag. `coverage report` now runs without `--fail-under`, letting
  `pyproject.toml` be the single source of truth.

### Fixed (four more places an exception stood in for a verdict)

- **A NUL byte in a model-supplied path escaped `guards.check_target` as a bare
  `ValueError`.** `Path.resolve` raises rather than returns for a path the
  operating system cannot represent — an embedded NUL is `ValueError`, a symlink
  loop is `OSError`. Both arrive from a *model-supplied* argument, so letting
  them through handed the model a framework error with no verdict field: the one
  thing this package exists to prevent. Now a `GuardRejection` with reason
  `invalid_path`. The message deliberately does not echo the target — a NUL byte
  pasted back into a JSON result is a second problem on top of the first.
- **The same call in `config._abs_paths` escaped every `except ConfigError`.**
  `ConfigError` *subclasses* `ValueError` and not the other way round, so a bare
  `ValueError` from `resolve` went past all of them. A malformed setting is now
  BLOCKED, and the result says which variable was wrong.
- **A sink artifact that is not valid UTF-8 raised `UnicodeDecodeError` out of
  `score_run`.** It sits beside `JSONDecodeError` under `ValueError` rather than
  under it, so the existing handler missed it. Refused rather than decoded with
  replacement: substituting U+FFFD into a scorer name would let a run report on
  evidence it could not actually read.
- **A findings payload that parsed was neither size-bounded nor redacted.**
  Redaction and the bounded excerpt only ever ran on the branch where
  `json.loads` *failed* — the uncommon one. On the common branch a credential
  inside valid JSON went back to the model verbatim, and a valid 30 MB document
  was returned whole. Both are closed in `planlint._read_findings`, which can
  only downgrade the evidence: exit 1 with a payload too large to hand back is
  still FINDINGS.

### Added (the evidence path)

- **`guards.redact_structure`** — redacts every string inside an already-parsed
  payload, dict keys included. Redacting the raw JSON *text* before parsing
  would be simpler and is wrong: one credential pattern consumes to the next
  whitespace, so on `{"authorization": "Bearer abc"}` it eats the closing quote
  and leaves text that no longer parses. Structure first, then strings. The walk
  is iterative because a recursive one raises `RecursionError` on a deeply
  nested document — the same trap `json.loads` sets, one layer further in — and
  still depth-bounded, because a payload shaped by an attacker can nest far
  enough to exhaust memory rather than stack. Redacting keys introduces a
  collision two different credentials share; the second is suffixed rather than
  left to overwrite the first, which would drop evidence silently in the exact
  path the function exists to defend.
- **`findings_truncated`** in the `lint_openspec` / `run_verb` envelope, `false`
  rather than `null` where no payload was ever read. Nothing was truncated, and
  that is a fact rather than an absence; a caller branching on the key should
  not have to treat null as a third state.
- **`FOUNDRY_SPIKE_FINDINGS_MAX_BYTES`** (262144) and
  **`FOUNDRY_SPIKE_FINDINGS_MAX_DEPTH`** (64). The size is measured on the raw
  stream *before* `json.loads`, so an oversized payload is never built into an
  object at all — parsing first to find out whether the result is too big to
  keep is the exhaustion this prevents. Measured in **UTF-8 bytes**, because the
  setting is named in bytes and `stdout` arrives decoded: 100k CJK characters
  are 300k bytes and would have walked through a ceiling counting code points.
  Set far below `EVAL_MAX_ARTIFACT_BYTES`, which bounds a file a human chose,
  where this bounds a subprocess's output stream.
- **`config=` on `lint_openspec`.** Not part of the MCP tool surface — a model
  never supplies it. It lets in-process callers (`__main__`'s self-check, the
  tests) vary configuration without mutating `os.environ`, which is global,
  order-dependent and has bitten this repository once already.
- **`mcp_server/tests/test_policy_is_not_configuration.py`** — pins the
  invariant that `README.md`, `SECURITY.md`, `config.py`'s docstring and the C4
  component view all state in prose. An opinion four documents repeat is worth
  one test.
- **Dev extras carry the linters.** `[dev]` held `pytest` alone, so
  `make setup && make validate` was red on a fresh clone at the first of three
  steps — CI installs `ruff`, `mypy` and `coverage` separately and never
  noticed. The floor for a contributor and the floor for CI should be the same
  floor.

### Changed

- **The `.gitignore` rule for `mcp.json` is path-independent.** It named
  `mcp/mcp.json` until that directory was renamed to `mcp_server/`, at which
  point it silently protected nothing — while `RUNBOOK.md` step 3.5 went on
  telling the operator to fill that file with real paths and possibly a GitHub
  token. Matching by name means the next rename cannot reopen the hole.
- **The declared SDK floor is actually exercised.** `mcp>=1.2` was advertised
  and never once run: the smoke suite's import guard named a 2.x-only submodule,
  so on 1.2 it errored during collection under `REQUIRE_MCP` and skipped
  silently without it. The guard now probes the package, a separate test
  re-asserts the namespace-shim hazard it was working around, and CI's transport
  job runs the whole suite on both ends of the range. A supported version is one
  CI runs.
- **`scan_evidence.py` survives an absolute out-of-tree target.**
  `Path.relative_to` raises for a path that is not under the repo, so pointing
  the gate at a staging directory before exporting it — the one use that most
  needs a gate — ended in a traceback rather than a scan.

### Added (Architecture, Quality Gates & Enterprise Hardening)

- **Modular Decomposition of `scripts/verifier_probe.py`**: Decomposed 490-line monolithic script into `scripts/probe/` package (`config.py`, `screen.py`, `client.py`, `runner.py`, `cli.py`), retaining a 100% backwards-compatible facade with decoupled `post_fn` injection for testability.
- **Enterprise 7-Layer Test Suite (94% branch coverage)**:
  1. *Unit*: Modular probe tests (`tests/unit/test_probe_modular.py`) and scoring branch coverage (`mcp_server/tests/test_scoring_branches.py`).
  2. *Integration*: Direct tool-function, filesystem, and probe pipeline flow (`tests/integration/test_mcp_integration.py`).
  3. *Functional*: Deterministic planlint exit code-to-verdict mapping (`tests/functional/test_planlint_functional.py`).
  4. *End-to-End*: Subprocess CLI execution for `scan_evidence.py`, `promote_trace.py`, and `verifier_probe.py` (`tests/e2e/test_e2e_workflow.py`).
  5. *User Journey*: Complete developer evaluation lifecycle from OpenSpec authoring to trace promotion (`tests/journey/test_engineer_workflow.py`).
  6. *Security*: Fuzzing path traversal, flag injections, mutating verbs rejection, and secret pattern masking (`tests/security/test_security_gates.py`).
  7. *Sanity*: Runtime environment, dependency checks, PEP 561 compliance, and CLI entrypoint callability (`tests/sanity/test_sanity_environment.py`).
- **Deterministic Skills and Agents**:
  - `.claude/skills/probe-evaluator/SKILL.md`: Automates probe runs, model response screening (`HELD`/`LAUNDERED`/`REVIEW`), and evidence promotion.
  - `.claude/agents/probe-orchestrator.md`: Subagent for model bake-off orchestration and transcript auditing.
  - `.agents/skills/foundry-spike/SKILL.md`: Workspace-level skill for Antigravity automated validation.
- **Trace Isolation and Test Hygiene**:
  - Added `--dest-root` to `scripts/promote_trace.py` to isolate promoted traces in tests and prevent repository pollution.
  - Added `.eval-runs/`, `mock_findings/`, `bad_target/`, and `scratch/` to `.gitignore` and `.dockerignore`.
  - Added PEP 561 marker `mcp_server/src/foundry_spike_mcp/py.typed`.
  - Updated `Makefile` with dedicated targets: `test-unit`, `test-integration`, `test-functional`, `test-e2e`, `test-journey`, `test-security`, `test-sanity`, `test-7layers`, and `--fail-under=80` coverage gate.

### Fixed (Code Hygiene & Typing)

- **Cleaned all 17 Ruff lint violations**: Resolved unused arguments (`ARG001`), whitespace (`W293`), unnecessary else (`RET505`), late imports (`E402`), import ordering (`I001`), and path/shell security lints (`PTH123`, `S607`).
- **Resolved all Mypy type discrepancies**: Configured `mypy_path` and `explicit_package_bases` in `pyproject.toml`, achieving 0 Mypy errors across all 18 source modules.


### Fixed (final hardening scan)

- **gitleaks panicked at config load and took CI red.** The custom rule used
  `(?!user\b)` -- a negative lookahead. gitleaks compiles with Go's RE2, which
  has no lookarounds, and it does not degrade gracefully: it panics before
  scanning anything, then the action fails again trying to upload a SARIF that
  was never produced. Rewritten without lookarounds, verified against the real
  `gitleaks` binary (3 test vectors detected, 3 portable forms not), and
  `test_evidence_hygiene.py` now rejects RE2-incompatible constructs in that
  file so the class of bug cannot recur.
- **Coverage was never measured.** First run put it at 76%, with every CLI
  entry point at or near zero -- `__main__.py` 0%, `scan_evidence` 48%,
  `verifier_probe` 57%. The library functions were well covered; the commands
  operators and CI actually invoke were not, which made the earlier "finding #6
  fixed" claim weaker than stated. `tests/test_cli_entrypoints.py` covers all
  four `main()` functions including exit codes. Now **91%** with branch
  coverage, floored at 85 in CI.

### Added

- `SECURITY.md` -- threat model (the adversary is a model-supplied argument,
  not a network attacker), the control for each surface, and the known
  limitations stated rather than left to be discovered: TOCTOU on path
  validation, floating Action tags, unpinned transitives, no LICENSE, public
  repository.
- `.github/CODEOWNERS` and `.github/dependabot.yml`. Dependabot exists mainly
  for `github-actions`: the workflow uses floating major tags, so a compromised
  tag would run in CI with no diff to review. Major bumps of `mcp` are ignored
  on purpose -- 1.x to 2.x already cost a broken server under green CI.
- Coverage gate in CI and `make coverage`; `make validate` now includes it.

- **Base branches** `main`, `Dev`, `QA`, all at the scaffold commit. The
  repository was created empty, so GitHub had made the working branch the
  default and no pull request had a base to target.
- **`config.py`** — every deployment tunable in one loader, read from the
  environment, with typed defaults and a `ConfigError` for malformed values.
  Absent falls back to a documented default; *malformed* is a BLOCKED result,
  because silently substituting a default hides an operator mistake.
- **`logging_setup.py`** — structured logging on **stderr only**, text or JSON,
  quiet by default. stdout is the JSON-RPC channel on a stdio MCP server; a
  stray line there makes the tool vanish from Agent Builder with no useful
  error. `test_logging.py` asserts it, including a static check that no module
  under `mcp_server/src/` calls bare `print()`.
- **SDK compatibility** for both `mcp` majors: `FastMCP` (1.x) and `MCPServer`
  (2.x), newest first, with an actionable error when neither is present. Both
  paths are tested — the installed one for real, the other through a stub.
- **`planlint.run_verb`** — one guarded execution point for every read-only
  verb, plus `detect_dialect`. The allow list previously advertised six verbs
  while only `validate` could ever run.
- **`scripts/promote_trace.py`** — copies a raw capture into tracked `traces/`
  only if it scans clean, closing the gap where `evidence/02-bakeoff.md` cited
  paths under gitignored `traces/raw/`.
- **`.gitleaks.toml`** — history-level credential scanning with a narrow
  allowlist for the fixtures that necessarily contain credential *shapes*.
  `traces/`, `evidence/`, `snippets/` and `configs/` are deliberately not
  allowlisted.
- **`.githooks/pre-commit`** — secret pass, gitleaks (when installed) and lint
  on staged Python. Installed with `make hooks`.
- **`Dockerfile` + `.dockerignore`** — reproducible regression environment on
  the declared Python floor, with `contract`, `transport` and `lint` stages.
  Deliberately *not* a way to run the server: Agent Builder spawns it over
  stdio, and a container boundary breaks that registration.
- **`.claude/`** — two skills (`spike-validate`, `contract-guard`), a read-only
  `contract-reviewer` agent, a post-edit hook, and a permissions allowlist.
  `tests/test_claude_assets.py` validates all of it deterministically:
  frontmatter shape, name/directory agreement, trigger language in every
  description, referenced paths resolving, hook scripts existing and being
  executable, and no credentials in any of it.
- **`ruff` + `mypy`** configured and wired into CI. The previous revision
  carried `# noqa: S310`, `S603` and `E402` for linters that were never run —
  suppressions claiming a finding had been considered when nothing had looked.
- **`docs/architecture/C4.md`** — context, container and component views, plus
  the verdict-flow diagram and the week-2 shape that shows what does *not*
  carry over.
- **`NEXT_STEPS.md`**, this changelog.

### Changed

- **`mcp/` renamed to `mcp_server/`.** The old name resolved as an empty
  namespace package when the repo root was on `sys.path`, so a bare
  `import mcp` succeeded with no SDK installed and `importorskip("mcp")` never
  skipped. Runtime was unaffected (an installed regular package outranks a
  namespace portion), but the guard was hollow.
- **`verifier_probe.py`**: sampling parameters (`temperature`, `top_p`,
  `max_tokens`, timeout) are CLI/env driven and **recorded in `summary.json`**.
  The runbook requires them identical across cells, which makes them
  configuration that has to be evidenced, not constants buried in a call.
  Provider dispatch is a table of frozen `Provider` records rather than an
  if/elif chain, so adding an OpenAI-shaped endpoint is one row.
- **Endpoint schemes are validated** (`http`/`https` only) rather than
  suppressed with a lint comment. Endpoints come from the environment, so
  `file:///etc/passwd` was reachable by a typo and `urlopen` would have read it
  into a saved transcript.
- **`scan_evidence.py`** now covers `snippets/`, `configs/` and `decisions/` by
  default. The previous revision documented those as caveats in a README — a
  gate with a written-down hole is not a gate.
- **`00-baseline.sh`** flag probe fixed: it grepped for `--format=json`, which
  never appears in help text reading `--format FORMAT`, so a supported flag
  went unreported.
- **Result envelopes are stable.** `lint_openspec` and `score_run` return the
  same key set on every path — they previously returned between six and nine
  keys depending on how far the run got.
- **CI split** into `contract` (nothing installed) and `transport` (SDK
  installed, `REQUIRE_MCP=1`). A single green tick was standing in for two
  different claims.

### Fixed

- **`RecursionError` escaped `score_run` and `lint_openspec`.** It comes from
  `json.loads` on deeply nested input and is *not* a `JSONDecodeError`, so it
  bypassed the handler and contradicted the "never raises" contract.
- **The verifier screen accused correct refusals.** `\bpassed\b` fires inside
  "has not passed", so a model that held the line scored LAUNDERED — in the one
  cell the week turns on. Now negation-aware on both lists; `fail` is
  deliberately not a negator, so "the lint failed earlier but this run passed"
  still reaches a human as REVIEW.
- **`score_run` could fabricate a pass.** `result` was in the verdict-key list,
  so a top-level summary field became a scorer: `{"result": "pass", "scorers":
  [{"passed": null}]}` returned PASS with `pass_rate: 1.0` where it should have
  been BLOCKED. Verdict-carrying objects must now be nameable, and an unnamed
  field on the artifact root is recorded in `ignored` rather than counted.

## [0.1.0] — scaffold

Initial spike scaffold: the two read-only MCP tools and their contract tests,
evidence capture, probe fixtures, the headless verifier backstop, and the
decision-log row the week exits on.

Three defects in the source runbook's sample code were corrected rather than
reproduced, all landing on the exit-2 path that step 3's own "done when"
requires: `subprocess.run(timeout=)` raises rather than returning,
`json.loads(proc.stdout)` on exit 2 parses a usage message, and
`os.environ["PLANLINT_TARGET"]` raises when unset. Resolved by one rule — **an
exception is not a verdict**. The runbook's fourth verdict, `UNKNOWN`, was
dropped: step 4.2 defines agent behaviour for exactly three states.
