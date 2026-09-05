# Session entry points. Each target maps to a runbook step; `make` lists them.
#
# Everything here is local-only and costs nothing. Nothing in this Makefile
# touches Azure, and nothing writes to Mango_Code_Agent-Harness, Agents, or
# planlint -- that is week 1's whole premise.

SHELL := /usr/bin/env bash
# Prefer the venv `make setup` creates, so `make test` does not silently run
# against a system interpreter that has neither pytest nor the package.
PY    ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python3)
PYTEST ?= $(PY) -m pytest

.DEFAULT_GOAL := help
.PHONY: help setup baseline test selfcheck serve probe probe-blocked scan verdict clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Session 1: setup baseline    Session 3: test selfcheck"
	@echo "  Session 2: probe             Session 4-5: serve, then verdict"

setup: ## Install the MCP server and dev deps into a local venv (session 0)
	$(PY) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e "mcp[dev]"
	@echo
	@echo "Now: cp .env.example .env && \$$EDITOR .env"

baseline: ## Runbook step 0.4-0.5: version stamp, dialect card, baseline exit codes
	bash scripts/00-baseline.sh

test: ## Run the contract suite (no network or planlint; server smoke test needs `make setup` first)
	$(PYTEST)

selfcheck: ## Runbook step 3 done-when: prove PASS / FINDINGS / BLOCKED all land
	PYTHONPATH=mcp/src $(PY) -m foundry_spike_mcp selfcheck --out evidence/03-mcp-selfcheck.json

serve: ## Run the stdio MCP server (what Agent Builder connects to)
	PYTHONPATH=mcp/src $(PY) -m foundry_spike_mcp serve

probe: ## Runbook step 2 prompt 2, headless: verifier probe across PROBE_MODELS
	$(PY) scripts/verifier_probe.py --prompt configs/probes/02-verifier.md --expect FINDINGS

probe-blocked: ## The optional exit-2 variant of the verifier probe
	$(PY) scripts/verifier_probe.py --prompt configs/probes/04-verifier-blocked.md --expect BLOCKED

scan: ## Secret-scan evidence/ and traces/ before anything is committed
	$(PY) scripts/scan_evidence.py

verdict: ## Open the step 5 verdict file, creating it from the template
	@test -f evidence/05-verdict.md || cp evidence/05-verdict.template.md evidence/05-verdict.md
	@echo "evidence/05-verdict.md is ready. It is the exit artifact -- write it before closing the week."

clean: ## Remove build and test detritus (leaves evidence/ and traces/ alone)
	rm -rf .venv .pytest_cache mcp/build mcp/dist mcp/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
