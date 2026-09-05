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
  python -m coverage report -m --fail-under=80
  ```

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
