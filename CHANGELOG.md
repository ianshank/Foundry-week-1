# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are spike milestones, not releases — nothing here is published.

Entries record *why* a change happened where the reason is not obvious from
the diff, because this repository's whole subject is a distinction that is easy
to lose by accident.

## [Unreleased]

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
