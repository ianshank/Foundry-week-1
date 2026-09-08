---
name: foundry-spike
description: Deterministic evaluation and validation workflows for Foundry week-1 spike. Use when running tests, validating MCP tool contracts, checking tri-state verdicts, running headless verifier probes, or validating repository hygiene and secret-scanning gates.
---

# Foundry Spike Automation Skill

Provides structured deterministic workflows for the Foundry Spike:

## Commands & Actions

- **Run 7-Layer Test Suite**:

  ```bash
  python -m pytest -q
  ```

- **Code Coverage Enforcement**:

  ```bash
  python -m coverage run -m pytest
  python -m coverage report -m
  ```

  No `--fail-under` on the command line. The floor is declared once, in
  `pyproject.toml` `[tool.coverage.report] fail_under`, and a CLI flag
  silently overrides it -- `tests/regression/test_regression_suite.py`
  asserts the flag's absence from CI for exactly that reason. This file used
  to prescribe `--fail-under=80` against a repository whose declared floor is
  90, i.e. it instructed an agent to do the thing a regression guard exists
  to forbid.

- **Type Checking & Code Hygiene**:

  ```bash
  ruff check .
  mypy
  ```

- **Secret Scanning Gate**:

  ```bash
  python scripts/scan_evidence.py
  ```

- **Headless Verifier Probe**:

  ```bash
  python scripts/verifier_probe.py --help
  ```
