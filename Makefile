# Session entry points and the validation gauntlet. `make` lists everything.
#
# Every target here is local-only and costs nothing. Nothing touches Azure, and
# nothing writes to Mango_Code_Agent-Harness, Agents, or planlint -- that is
# week 1's whole premise.

SHELL := /usr/bin/env bash
# Prefer the venv `make setup` creates, so `make test` does not silently run
# against a system interpreter that has neither pytest nor the package.
# Windows puts the venv interpreter at `Scripts/python.exe`, not `bin/python`.
# Checking only the POSIX path meant this always fell through to `python3` on
# Windows -- which resolves to the Microsoft Store shim, an interpreter with
# neither pytest nor the package. That is precisely the outcome the comment
# above says this line exists to prevent, and it went unnoticed because the
# repo added a windows-latest CI leg and fixed twelve Windows-local test
# failures while the Makefile stayed silently Unix-only.
PY     ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || (test -x .venv/Scripts/python.exe && echo .venv/Scripts/python.exe) || echo python3)
PYTEST ?= $(PY) -m pytest
SRC    := mcp_server/src

# Every command that reaches the tools goes through this, so the import path is
# defined in exactly one place.
RUN := PYTHONPATH=$(SRC) $(PY)

# Every shell script the repo ships, discovered rather than listed. The list
# used to be hard-coded in three places (here, CI, the hook) and a fourth
# script would have been added to none of them.
SHELL_SCRIPTS := $(shell ls .githooks/* 2>/dev/null) \
                 $(wildcard scripts/*.sh) $(wildcard .claude/hooks/*.sh)

.DEFAULT_GOAL := help
.PHONY: help setup hooks baseline test regression lint typecheck scan secrets \
        validate coverage selfcheck serve probe probe-blocked promote verdict \
        test-unit test-integration test-functional test-e2e test-journey \
        test-security test-sanity test-regression aqa test-live test-7layers \
        test-contract test-root \
        shellcheck docker-test docker-transport docker-lint clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Session 1: setup hooks baseline    Session 3: validate selfcheck"
	@echo "  Session 2: probe promote           Session 4-5: serve, then verdict"
	@echo
	@echo "  Before any PR: make validate"

# ---------------------------------------------------------------- setup

setup: ## Create the venv and install the server with dev deps (session 0)
	$(PY) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "mcp_server[dev]" ruff mypy
	@echo
	@echo "Now: cp .env.example .env && \$$EDITOR .env && make hooks"

hooks: ## Install the git pre-commit gate (secret scan + gitleaks + lint)
	git config core.hooksPath .githooks
	@echo "core.hooksPath -> .githooks (bypass with --no-verify; CI still checks)"

# ------------------------------------------------------- validation gauntlet

# `$(PY) -m` rather than a bare `ruff`/`mypy`. PY already prefers .venv, but
# these two targets went through PATH -- so on a fresh `make setup && make
# validate` they either failed outright or silently linted with a system ruff
# at a different version than the venv the rest of the gauntlet uses.
lint: ## ruff over the whole repo
	$(PY) -m ruff check .

typecheck: ## mypy over mcp_server/src and scripts
	$(PY) -m mypy

test: ## The full suite (contract + smoke; smoke skips without the SDK)
	$(PYTEST)

regression: ## The suite with the SDK required -- what CI's transport job runs
	REQUIRE_MCP=1 $(PYTEST)

coverage: ## Run the suite under coverage and enforce both floors
	$(PY) -m coverage run -m pytest -q
	$(PY) -m coverage report
# `coverage json` then a second, tiny pytest run, because the per-file floor
# needs a report that only exists after the first run finished. The global
# floor above catches the aggregate sagging; this catches one file being
# abandoned while better-covered files subsidise it -- which the aggregate
# cannot see, and which `server.py` (40 units, the file the transport job
# exists to guard) could do today without breaching 90.
	$(PY) -m coverage json -q
	$(PYTEST) tests/regression/test_coverage_floor.py -q

# -------------------------------------------------- 7-layer test targets
# Layer 1: unit, 2: integration, 3: functional, 4: e2e, 5: journey,
# 6: security, 7: sanity. Plus regression (guard layer) and aqa.

test-unit: ## Layer 1: unit tests
	$(PYTEST) tests/unit/ -v

test-integration: ## Layer 2: integration tests
	$(PYTEST) tests/integration/ -v

test-functional: ## Layer 3: functional tests
	$(PYTEST) tests/functional/ -v

test-e2e: ## Layer 4: end-to-end, including the stdio server over real JSON-RPC
	# `mcp_server/tests/test_server_e2e_stdio.py` is the strongest end-to-end
	# test in this repository -- it spawns `python -m foundry_spike_mcp serve`
	# and drives a real JSON-RPC handshake over stdio across eight cases,
	# including stdout purity at DEBUG. It lives under `mcp_server/tests/`
	# because that suite must also run standalone, so this target did not
	# reach it: the layer named `e2e` was running two `--help` invocations
	# while the real thing did not count as one. Named here rather than
	# moved, because moving it would break `cd mcp_server && pytest`.
	$(PYTEST) tests/e2e/ mcp_server/tests/test_server_e2e_stdio.py -v

test-journey: ## Layer 5: user journey tests
	$(PYTEST) tests/journey/ -v

test-security: ## Layer 6: security gate tests
	$(PYTEST) tests/security/ -v

test-sanity: ## Layer 7: sanity / environment checks
	$(PYTEST) tests/sanity/ -v

test-regression: ## Regression guard layer: fixed-defect guards (D-01/D-02, F4, F5, F9)
	$(PYTEST) tests/regression/ -v

aqa: ## AQA acceptance layer: tests marked with @pytest.mark.aqa
	$(PYTEST) -m aqa -v

test-live: ## Lane D: contact a real vendor LLM (opt-in: PROBE_LIVE=1 PROBE_MODELS=...)
	PROBE_LIVE=$${PROBE_LIVE:-1} $(PYTEST) -m live_llm -v -rs

test-contract: ## The MCP tool contract suite (mcp_server/tests/) -- 300+ tests
	$(PYTEST) mcp_server/tests/ -v

test-root: ## The root-level suites outside the layer taxonomy
	$(PYTEST) tests/*.py -v

# `test-7layers` ran 109 of 577 tests and its help text said "all". The layer
# targets pass explicit paths, which overrides `pytest.ini`'s `testpaths`, so
# it silently skipped every one of mcp_server/tests/ -- the entire verdict
# contract -- plus the four root-level files and tests/aqa/. Someone running
# it before a PR, believing the name, skipped the thing this repository is
# about. It now names what it runs and runs what it names.
test-7layers: test-unit test-integration test-functional test-e2e test-journey test-security test-sanity test-regression test-contract test-root aqa ## Every layer, the contract suite, the root suites and AQA


scan: ## Credential pass over evidence/ traces/ snippets/ configs/ decisions/
	$(PY) scripts/scan_evidence.py

secrets: scan ## The full credential gate: scan_evidence + gitleaks over history
	@if command -v gitleaks >/dev/null 2>&1; then \
	  gitleaks detect --config .gitleaks.toml --no-banner --redact; \
	else \
	  echo "gitleaks not installed -- CI's secrets job still runs it over full history."; \
	  echo "  brew install gitleaks   |   https://github.com/gitleaks/gitleaks"; \
	fi

shellcheck: ## Every shell script parses (what CI's contract job asserts)
	@bash -n $(SHELL_SCRIPTS) && echo "shell scripts parse: $(words $(SHELL_SCRIPTS)) file(s)"

# The set below is exactly what CI asserts, in the same order:
#   lint/typecheck -> quality job    coverage -> quality job's floor
#   regression     -> transport job  secrets  -> secrets job
# `regression` was the gap: `make validate` was green while CI's transport leg
# was the only thing that had ever run the suite with the SDK required, so the
# one failure mode the transport job exists to catch was undetectable locally.
validate: lint typecheck coverage regression aqa secrets shellcheck ## Everything CI checks, stopping at the first failure
	@echo
	@echo "All checks passed. Safe to open a PR."

# ------------------------------------------------------------- the week

baseline: ## Step 0.4-0.5: version stamp, dialect card, baseline exit codes
	bash scripts/00-baseline.sh

probe: ## Step 2 prompt 2, headless: verifier probe across PROBE_MODELS
	$(PY) scripts/verifier_probe.py --prompt configs/probes/02-verifier.md --expect FINDINGS

probe-blocked: ## The optional exit-2 variant of the verifier probe
	$(PY) scripts/verifier_probe.py --prompt configs/probes/04-verifier-blocked.md --expect BLOCKED

promote: ## Promote a raw capture into tracked traces/: make promote RUN_DIR=traces/raw/<dir> [AS=<name>]
	@test -n "$(RUN_DIR)" || { echo "usage: make promote RUN_DIR=traces/raw/<dir> [AS=<name>]"; exit 2; }
	$(PY) scripts/promote_trace.py "$(RUN_DIR)" $(if $(AS),--as "$(AS)",)

selfcheck: ## Step 3 done-when: prove PASS / FINDINGS / BLOCKED all land
	$(RUN) -m foundry_spike_mcp selfcheck --out evidence/03-mcp-selfcheck.json

serve: ## Run the stdio MCP server (what Agent Builder connects to)
	$(RUN) -m foundry_spike_mcp serve

verdict: ## Create evidence/05-verdict.md from the template -- the exit artifact
	@test -f evidence/05-verdict.md || cp evidence/05-verdict.template.md evidence/05-verdict.md
	@echo "evidence/05-verdict.md is ready. Write it before closing the week."

# ------------------------------------------------------------- containers
# The regression environment, not a way to run the server -- Agent Builder
# spawns that over stdio and a container boundary breaks the registration.

docker-test: ## Contract suite on the declared Python floor, nothing installed
	docker build --target contract -t foundry-spike:contract . && docker run --rm foundry-spike:contract

docker-transport: ## Same, plus the SDK, so the server smoke test actually runs
	docker build --target transport -t foundry-spike:transport . && docker run --rm foundry-spike:transport

docker-lint: ## ruff + mypy in the container
	docker build --target lint -t foundry-spike:lint . && docker run --rm foundry-spike:lint

clean: ## Remove build and test detritus (leaves evidence/ and traces/ alone)
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache \
	       mcp_server/build mcp_server/dist mcp_server/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
