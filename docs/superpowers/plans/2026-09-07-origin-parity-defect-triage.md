# Origin-Parity Defect Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four defects found by running every test lane against the changes `origin/h` carries over `origin/main` — including the live-HTTP lane no test currently exercises — and lock each one behind a regression guard and an AQA acceptance test.

**Architecture:** Branch `qa/origin-parity-defect-triage` is already cut from `origin/h` (a4d3f22). All four defects live in the probe harness (`scripts/probe/`, `scripts/promote_trace.py`), which is the one subsystem whose transport path has only ever been tested through an injected `post_fn`. Fixes are surgical: a new exit-code state, a promotion content gate, POSIX-normalised evidence paths, and an argparse-level error for an unwritable `--out`. Each fix lands with a `tests/regression/` guard (fails if the fix is reverted) and, where the defect concerns real dependencies, a `tests/aqa/` acceptance test that drives a real HTTP socket.

**Tech Stack:** Python 3.10+ (CI floor), pytest 9.x, `http.server.ThreadingHTTPServer` for the live-endpoint lane, ruff, mypy, coverage.

**Spec:** This plan is its own spec — the requirements are the four triaged defects in "Diagnostic Baseline" below, each with the reproduction that produced it. There is no separate design doc.

## Global Constraints

Copied verbatim from the repo's existing configuration. Every task's requirements implicitly include this section.

- **Python floor is 3.10.** `pyproject.toml` sets `target-version = "py310"`; CI's `contract` job runs ubuntu/3.10. No `tomllib` without a `tomli` fallback, no `match`, no `StrEnum`, no `typing.Self`.
- **Line length 100**, `E501` ignored, but ruff rule sets `E W F I B S UP C4 SIM PTH RET ARG TRY` are all on. `PTH` means **use `pathlib`, not `os.path`**. `TRY` means **no bare `raise Exception`, and no long bodies in `try:`**.
- **`mypy` must pass with zero issues** over `mcp_server/src` and `scripts` (currently: "Success: no issues found in 19 source files").
- **Coverage floor is `fail_under = 90`** in `pyproject.toml` `[tool.coverage.report]`. Current actual is 93%. **Never add `--fail-under` to `ci.yml`** — `tests/regression/test_regression_suite.py::test_ci_coverage_floor_matches_pyproject` asserts its absence.
- **New pytest markers must be registered in `pytest.ini`.** Unregistered markers are a collection error. `regression` and `aqa` already exist; this plan adds `live_llm`.
- **Tests must pass in all four lanes** (see "Verification Lanes"). A test that only passes with the MCP SDK installed must skip cleanly without it, unless `REQUIRE_MCP=1`.
- **No file may carry a UTF-8 BOM.** `a4d3f22` removed the last one; Task 6 guards it.
- **Evidence and trace artifacts are tracked content.** Anything written into `traces/` or `evidence/` must be byte-identical across Windows and Linux for the same logical run.
- **`.probe_tmp/` is not a real directory.** Tests write live-endpoint output under `tmp_path` only. Never leave artifacts in the working tree.

---

## Diagnostic Baseline

This is what was actually run, and what it found. An implementer should not re-derive it, but every reproduction below is re-runnable.

### What was compared

`origin/h` (a4d3f22) vs `origin/main` (95efe16) — 16 files, +783/−100:

```
.github/workflows/ci.yml, CHANGELOG.md, Makefile, NEXT_STEPS.md,
docs/architecture/C4.md, mcp_server/src/foundry_spike_mcp/planlint.py,
mcp_server/tests/{conftest,test_planlint_contract,test_server_e2e_stdio}.py,
pytest.ini, tests/aqa/*, tests/conftest.py, tests/integration/*,
tests/regression/*
```

### Lanes that came back green (do not re-litigate these)

| Lane | Command | Result |
|---|---|---|
| Full suite, mocks allowed | `python -m pytest -q` | 344 passed, 8 skipped |
| No mocks — SDK required | `REQUIRE_MCP=1 python -m pytest -q` | same, 8 platform skips only |
| CI `contract` parity — SDK hidden | pytest with a meta-path finder blocking `mcp` | passed, 10 skips |
| `REQUIRE_MCP=1` **with SDK hidden** | as above | **fails loudly at collection** — the guard is real, not decorative |
| Lint | `python -m ruff check .` | All checks passed |
| Types | `python -m mypy` | Success: no issues in 19 source files |
| Coverage floor | `coverage run --branch --source=mcp_server/src,scripts -m pytest` | **93%** vs floor 90 |

All 8 skips are legitimate platform skips (POSIX signals, symlink privileges, CRLF, executable bits).

### GPU: not applicable — verified, not assumed

Two NVIDIA GPUs are present on the host (RTX 5060 Ti, RTX 5060). The repo has **no GPU code path**: `torch` is not a dependency, and `grep -rniE '\b(cuda|gpu|torch|nvidia)\b'` over `*.py *.md *.yml *.sh *.toml` returns three hits, all prose (`docs/architecture/C4.md:24` labels the Ollama box, `README.md:141` and `RUNBOOK.md:87` describe Windows ML targeting). There is no GPU lane to run and none to add.

### Live LLM API: the seam, and why it is the gap

`scripts/probe/client.py` speaks OpenAI-compatible HTTP to three providers (`github`, `ollama`, `openai-compatible`). **No test in the repo has ever opened a socket against it** — `call_model` is always driven with an injected `post_fn`, so `_post`, the `urllib` error branches, and the response-shape branches are exercised only in simulation. `client.py` reads 93% covered, which is coverage of the fake.

No live credential or endpoint is available in this environment: no `GITHUB_TOKEN`, no `OPENAI_*`/`ANTHROPIC_*`/`AZURE_*`, `localhost:11434` is not listening, and `ollama` is not on `PATH`. So the live-vendor lane is built here as **opt-in** (Task 5) and skips with a stated reason when unconfigured — and the defects below were found instead by driving the real client against a **real local HTTP server** (`ThreadingHTTPServer`, real socket, real JSON), which is a no-mock test the CI can always run.

### Triaged defects

---

**D-03 — Probe exits 0 when no model was ever reached. (High)**

*Reproduction.* With nothing listening on port 8799:

```
$ OLLAMA_ENDPOINT="http://127.0.0.1:8799/v1" \
  python scripts/verifier_probe.py --models "ollama:m" --expect FINDINGS --out .probe_tmp
-> ollama:m
   ERROR  (URLError: <urlopen error [WinError 10061] ... actively refused it>)
exit=0
```

Same exit 0 for an unknown provider (`notaprovider:m`) and for `github:gpt-4o` with `GITHUB_TOKEN` unset.

*RCA.* `scripts/probe/cli.py`, last line of `main`:

```python
return 1 if any(row["screen"] == LAUNDERED for row in rows) else 0
```

The exit code encodes exactly one fact — *did any model launder a failing run* — but every caller reads it as two: *did the run happen*, and *did it launder*. There is no third state for "the run did not happen", so the absence of laundering and the absence of a run are the same byte. `make probe` is wired to this, so a bake-off where every endpoint was unreachable reports success. The printed banner already says "REVIEW and ERROR rows are not results" — the design knows; the exit code does not.

*Fix.* Add exit code 2 for "no usable row". Preserve the partial-run case deliberately: a multi-model bake-off where *some* slots answered is still a usable run, so 2 fires only when **no** row reached a model. Exit 1 (laundering) keeps priority over 2.

---

**D-04 — A run that never reached a model can be promoted into tracked evidence. (Medium)**

*Reproduction.* Take the `github:gpt-4o`-with-no-token capture from D-03, whose only row is `status: ERROR`:

```
$ python -c "from scripts.promote_trace import promote; print(promote(src, destination_root=dest))"
PROMOTED -> ...\_tracked\20260907T153520Z-02-verifier
```

*RCA.* `scripts/promote_trace.py::promote` gates on exactly one thing — the credential scan. That gate is correct and load-bearing (a promoted transcript is one `git push` from public), but it is a *confidentiality* gate, and nothing checks *evidentiary content*. So `traces/` can hold, and `evidence/02-bakeoff.md` can cite, a run directory in which no model was ever contacted. That is the same failure as D-03 one layer up, and it is the layer that reaches the reader.

*Fix.* Refuse promotion when `summary.json` is present and every row's `status` is `ERROR`. Absent `summary.json` → promote as today (manual exports are a supported input; `promote_trace.py`'s docstring says so). Escape hatch: `--allow-error-run` for the case where the error transcript *is* the evidence.

---

**D-05 — `summary.json` records native path separators. (Medium)**

*Reproduction.* A live run on Windows writes:

```json
"prompt": "configs\\probes\\02-verifier.md",
"system_prompt": "configs\\probes\\system-prompt.md",
```

The same run on Linux writes `configs/probes/02-verifier.md`.

*RCA.* `scripts/probe/runner.py::_rel` returns `str(path.resolve().relative_to(REPO))`, and `str(Path)` is platform-native. Evidence artifacts are tracked content, so two captures of the same logical run diff against each other for reasons that have nothing to do with the run. This is precisely the Windows-parity class branch `h` was created to fix (its 12 fixes were all `WinError 193` / `cp1252`), and it survived because no test looks at the *content* of `summary.json` paths.

*Fix.* `_rel` returns `PurePosixPath` form. POSIX output is unchanged, so this is a Windows-only behaviour change.

---

**D-06 — Unhandled `OSError` on an unwritable `--out`. (Low)**

*Reproduction.* Point `--out` at a directory the process cannot create:

```
  File "scripts\probe\cli.py", line 81, in main
    out_dir.mkdir(parents=True, exist_ok=True)
PermissionError: [WinError 5] Access is denied: 'C:\\Program Files\\Git\\traces'
```

*RCA.* `cli.py:81` calls `mkdir` outside any handler, while every other argument problem in `main` routes through `parser.error` (missing file, template placeholder, empty `--models`, malformed `PROBE_*`). One input validates by traceback and the rest by message.

*Fix.* Wrap the `mkdir` in `except OSError` → `parser.error`.

---

**D-07 — BOM: already fixed upstream, not yet guarded. (Low)**

Local `h` (1e24893) carried a UTF-8 BOM at `tests/integration/test_mcp_integration.py:1`. `origin/h` a4d3f22 removed it. This branch is cut from a4d3f22 so **the fix is already present** — no code change is needed. What is missing is the guard: nothing prevents the next editor from reintroducing one, anywhere. Task 6 adds a repo-wide regression test.

---

## Verification Lanes

Four lanes. Every task's final step runs at least lane A; Task 7 runs all four.

| | Lane | Command |
|---|---|---|
| **A** | Mocks allowed (default) | `python -m pytest -q` |
| **B** | No mocks — SDK required | `REQUIRE_MCP=1 python -m pytest -q` |
| **C** | Live local HTTP endpoint | `python -m pytest -q -m aqa` (self-hosting; needs no credential) |
| **D** | Live vendor LLM | `PROBE_LIVE=1 PROBE_MODELS=... python -m pytest -q -m live_llm` |

Lane D skips unless `PROBE_LIVE=1` **and** the slot's endpoint/credential resolve. That is intentional: an acceptance test that silently passes without contacting a vendor is the same defect as D-03.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `tests/aqa/live_endpoint.py` (create) | The one place a real HTTP LLM endpoint is stood up. A `ThreadingHTTPServer` context manager plus a scripted-reply handler. Imported by the AQA tests; holds no assertions. | 1 |
| `tests/aqa/test_aqa_live_endpoint.py` (create) | AQA acceptance for the probe against a real socket: HELD, LAUNDERED, REVIEW, dead endpoint, mixed run. Marked `aqa`. | 1, 2 |
| `scripts/probe/cli.py` (modify) | Exit-code contract (D-03) and `--out` error handling (D-06). | 2, 4 |
| `scripts/probe/runner.py` (modify) | `_rel` POSIX normalisation (D-05). | 3 |
| `scripts/promote_trace.py` (modify) | Content gate on promotion (D-04). | 4 |
| `tests/regression/test_probe_exit_contract.py` (create) | Guards D-03. Separate file from the existing suite: that file is organised by the `h` gap analysis (F4/F5/F9/F14), and these are a different defect generation. | 2 |
| `tests/regression/test_evidence_portability.py` (create) | Guards D-04, D-05, D-07 — the three defects about what lands in tracked evidence. Files that change together live together. | 3, 4, 6 |
| `tests/aqa/test_aqa_live_llm.py` (create) | Lane D. Opt-in vendor acceptance. Marked `aqa` and `live_llm`. | 5 |
| `pytest.ini` (modify) | Register the `live_llm` marker. | 5 |
| `Makefile` (modify) | `test-live` target for lane D; extend `aqa`. | 5 |
| `.github/workflows/ci.yml` (modify) | Run lane C in CI. Lane D is never wired to CI — no vendor credential belongs in this repo's Actions. | 7 |
| `CHANGELOG.md` (modify) | Record the four fixes. | 7 |

---

## Task 1: The live HTTP endpoint harness

Stand up the thing every later task tests against. No production code changes — this task's deliverable is that a real socket can be driven from pytest, proven by one passing acceptance test.

**Files:**
- Create: `tests/aqa/live_endpoint.py`
- Create: `tests/aqa/test_aqa_live_endpoint.py`

**Interfaces:**
- Consumes: `scripts.probe.cli.main`, `scripts.probe.config.PROBES` (both already exist and are importable via `pytest.ini`'s `pythonpath = mcp_server/src scripts .`).
- Produces, for Tasks 2–4:
  - `live_llm_endpoint(reply: str, *, status: int = 200, body: bytes | None = None) -> ContextManager[str]` — yields the base URL, e.g. `http://127.0.0.1:54321/v1`.
  - `run_probe(base_url: str, out_dir: Path, *, models: str = "ollama:probe-test", expect: str = "FINDINGS", extra: list[str] | None = None, monkeypatch) -> int` — sets `OLLAMA_ENDPOINT` and returns `main()`'s exit code.
  - `read_summary(out_dir: Path) -> dict` — parses the single `summary.json` under `out_dir`.

- [ ] **Step 1: Write the failing test**

Create `tests/aqa/test_aqa_live_endpoint.py`:

```python
"""AQA lane C: the probe against a real HTTP endpoint, not an injected post_fn.

`scripts/probe/client.py` speaks OpenAI-compatible HTTP, and until this file
existed every test drove it through `post_fn=`. That covers the parsing and
none of the transport: `_post`, the `urllib` error branches and the
response-shape branches were all measured against a fake. These tests open a
real socket on loopback, so the bytes on the wire are the bytes the client
built.

No credential and no vendor: the server is `http.server`, started per test on
an ephemeral port. That is what keeps this lane runnable in CI. The vendor
lane is `tests/aqa/test_aqa_live_llm.py`, which is opt-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.aqa.live_endpoint import live_llm_endpoint, read_summary, run_probe

pytestmark = pytest.mark.aqa


def test_probe_reaches_a_real_endpoint_and_records_the_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A declared FINDINGS verdict over real HTTP screens HELD and exits 0."""
    with live_llm_endpoint("VERDICT: FINDINGS\n- a real finding") as base_url:
        code = run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 0
    summary = read_summary(tmp_path)
    assert len(summary["results"]) == 1
    row = summary["results"][0]
    assert row["status"] == "OK"
    assert row["screen"] == "HELD"
    assert row["declared"] == "FINDINGS"
    # Proof the transport ran rather than a stub: the server reports usage,
    # and only a real response body can carry it through.
    assert row["total_tokens"] == 18
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/aqa/test_aqa_live_endpoint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.aqa.live_endpoint'`

- [ ] **Step 3: Write the harness**

Create `tests/aqa/live_endpoint.py`:

```python
"""A real OpenAI-compatible HTTP endpoint for the AQA lane.

Not a mock and not a fixture: a `ThreadingHTTPServer` on loopback, bound to an
ephemeral port so tests can run in parallel and never collide. It exists so
the probe's transport is exercised by the transport, and it deliberately holds
no assertions -- the tests own those.

Port 0 rather than a constant: a hard-coded port makes the suite fail for
whoever already has that port, and makes two of these tests unrunnable at once.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from probe.cli import main as probe_main


def _handler_for(reply: str, status: int, body: bytes | None) -> type[BaseHTTPRequestHandler]:
    """Build a handler class closed over one scripted response."""

    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            payload = body if body is not None else json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": reply}}],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                    },
                }
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            """Silence the default stderr access log; pytest captures enough."""

    return _Handler


@contextmanager
def live_llm_endpoint(
    reply: str = "VERDICT: FINDINGS\n- a real finding",
    *,
    status: int = 200,
    body: bytes | None = None,
) -> Iterator[str]:
    """Serve one scripted OpenAI-compatible reply; yield the `/v1` base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(reply, status, body))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_probe(
    base_url: str,
    out_dir: Path,
    *,
    models: str = "ollama:probe-test",
    expect: str = "FINDINGS",
    extra: list[str] | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    """Drive the probe CLI at `base_url` and return its exit code.

    `ollama` is the slot used throughout because it is the one provider whose
    `credential_required` is False, so the lane needs no secret to run.
    """
    monkeypatch.setenv("OLLAMA_ENDPOINT", base_url)
    argv = [
        "--models", models,
        "--expect", expect,
        "--timeout", "15",
        "--out", str(out_dir),
        *(extra or []),
    ]
    return probe_main(argv)


def read_summary(out_dir: Path) -> dict[str, Any]:
    """Parse the one `summary.json` the probe wrote under `out_dir`."""
    summaries = sorted(out_dir.glob("*/summary.json"))
    if len(summaries) != 1:
        raise AssertionError(f"expected exactly one summary.json under {out_dir}, got {summaries}")
    return json.loads(summaries[0].read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run the test and make sure it passes**

Run: `python -m pytest tests/aqa/test_aqa_live_endpoint.py -v`
Expected: PASS

- [ ] **Step 5: Confirm the marker selects it and nothing else broke**

Run: `python -m pytest -q -m aqa` — expected: the new test plus the existing `tests/aqa/test_aqa_cross_platform.py` cases, all passing.
Run: `python -m pytest -q` — expected: full suite still green.
Run: `python -m ruff check . && python -m mypy` — expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/aqa/live_endpoint.py tests/aqa/test_aqa_live_endpoint.py
git commit -m "test(aqa): drive the probe against a real HTTP endpoint

The probe's transport had only ever been tested through an injected
post_fn, so _post and every urllib branch were measured against a fake.
This stands up a loopback ThreadingHTTPServer on an ephemeral port, which
needs no credential and so can run in CI.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: D-03 — exit 2 when no model was reached

**Files:**
- Modify: `scripts/probe/cli.py` (the `return` at the end of `main`)
- Create: `tests/regression/test_probe_exit_contract.py`
- Modify: `tests/aqa/test_aqa_live_endpoint.py` (add the live-socket acceptance cases)

**Interfaces:**
- Consumes: `live_llm_endpoint`, `run_probe`, `read_summary` from Task 1; `scripts.probe.screen.ERROR` and `LAUNDERED`.
- Produces: the documented exit contract for `scripts/verifier_probe.py` — `0` usable run, no laundering; `1` at least one row laundered; `2` no row reached a model. Task 7 documents it in `CHANGELOG.md`.

- [ ] **Step 1: Write the failing regression guard**

Create `tests/regression/test_probe_exit_contract.py`:

```python
"""Regression guard: D-03 -- the probe must not exit 0 on a run that never happened.

Before this guard, `main` returned `1 if any laundered else 0`. One byte
carried one fact (did anything launder) while every caller read two (did the
run happen, and did it launder). An unreachable endpoint, a misspelled
provider and a missing credential all produced exit 0, so `make probe` was
green for a bake-off in which no model was ever contacted.

The three cases below are the three ways a row reaches ERROR without any
network being available, which is what makes them runnable anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probe.cli import main as probe_main

pytestmark = pytest.mark.regression

NO_USABLE_ROW = 2


def _run(out_dir: Path, models: str) -> int:
    return probe_main(["--models", models, "--expect", "FINDINGS",
                       "--timeout", "5", "--out", str(out_dir)])


def test_unknown_provider_does_not_exit_zero(tmp_path: Path) -> None:
    """A misspelled provider never reaches a model, so the run is not usable."""
    assert _run(tmp_path, "notaprovider:some-model") == NO_USABLE_ROW


def test_missing_required_credential_does_not_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """github requires a token; without one the slot errors before any request."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert _run(tmp_path, "github:gpt-4o") == NO_USABLE_ROW


def test_unset_endpoint_does_not_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openai-compatible has no default endpoint; unset means no request."""
    monkeypatch.delenv("OPENAI_COMPATIBLE_ENDPOINT", raising=False)
    assert _run(tmp_path, "openai-compatible:whatever") == NO_USABLE_ROW
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/regression/test_probe_exit_contract.py -v`
Expected: all three FAIL with `assert 0 == 2`.

- [ ] **Step 3: Write the minimal implementation**

In `scripts/probe/cli.py`, add `ERROR` to the existing screen import:

```python
from .screen import ERROR, LAUNDERED, _strip_html_comments
```

Then replace the final line of `main`:

```python
    return 1 if any(row["screen"] == LAUNDERED for row in rows) else 0
```

with:

```python
    # Three states, because callers read three facts off this byte and there
    # used to be only two available. `make probe` was green for a bake-off in
    # which no endpoint answered, because "nothing laundered" and "nothing ran"
    # were the same exit code.
    #
    # Laundering outranks an unusable run: if any model that *did* answer
    # laundered a failing verdict, that is the finding, and a second dead slot
    # in the same run must not downgrade it to a plumbing complaint.
    if any(row["screen"] == LAUNDERED for row in rows):
        return 1
    if all(row["screen"] == ERROR for row in rows):
        return 2
    return 0
```

Note `all(...)` on a non-empty list: `main` already `parser.error`s on an empty `--models`, so `rows` is never empty here.

- [ ] **Step 4: Run the guard to verify it passes**

Run: `python -m pytest tests/regression/test_probe_exit_contract.py -v`
Expected: 3 passed.

- [ ] **Step 5: Add the live-socket acceptance cases**

Append to `tests/aqa/test_aqa_live_endpoint.py`:

```python
def test_laundered_reply_over_real_http_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model declaring PASS on a run expected to have findings is laundering."""
    reply = "VERDICT: PASS\nEverything looks good, the run passed and it is safe to merge."
    with live_llm_endpoint(reply) as base_url:
        code = run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 1
    assert read_summary(tmp_path)["results"][0]["screen"] == "LAUNDERED"


def test_reply_without_a_verdict_line_screens_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No VERDICT line is not a pass and not a launder -- a human must read it."""
    with live_llm_endpoint("I looked at the artifact and have some thoughts.") as base_url:
        code = run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 0
    assert read_summary(tmp_path)["results"][0]["screen"] == "REVIEW"


def test_dead_endpoint_exits_two_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-03 over the real transport: a refused connection is not a passing run.

    The endpoint is obtained from a live server that is then shut down, which
    guarantees the port is genuinely closed rather than merely unlikely.
    """
    with live_llm_endpoint() as base_url:
        dead_url = base_url
    code = run_probe(dead_url, tmp_path, monkeypatch=monkeypatch)

    assert code == 2
    assert read_summary(tmp_path)["results"][0]["status"] == "ERROR"


def test_partial_run_still_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One live slot plus one dead slot is a usable run, not a failed one.

    This is the boundary D-03's fix must not overrun: exit 2 means *no* model
    answered. A bake-off that reached three of four models still produced
    three results, and failing it would make the exit code useless for the
    thing it is actually for.
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with live_llm_endpoint("VERDICT: FINDINGS\n- one") as base_url:
        code = run_probe(
            base_url, tmp_path, models="ollama:live,github:unreachable", monkeypatch=monkeypatch
        )

    assert code == 0
    screens = {row["slot"]: row["screen"] for row in read_summary(tmp_path)["results"]}
    assert screens == {"ollama:live": "HELD", "github:unreachable": "ERROR"}
```

- [ ] **Step 6: Run every lane touched**

Run: `python -m pytest tests/aqa/ tests/regression/ -v` — expected: all pass.
Run: `python -m pytest -q` — expected: full suite green.
Run: `python -m ruff check . && python -m mypy` — expected: clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/probe/cli.py tests/regression/test_probe_exit_contract.py \
        tests/aqa/test_aqa_live_endpoint.py
git commit -m "fix(probe): exit 2 when no model was reached (D-03)

The exit code carried one fact and callers read two, so an unreachable
endpoint, an unknown provider and a missing credential all exited 0 --
make probe was green for a bake-off that never contacted a model.
Laundering still outranks an unusable run, and a partial run still
exits 0.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: D-05 — platform-stable evidence paths

**Files:**
- Modify: `scripts/probe/runner.py:14-19` (`_rel`)
- Create: `tests/regression/test_evidence_portability.py`

**Interfaces:**
- Consumes: `read_summary`, `live_llm_endpoint`, `run_probe` from Task 1.
- Produces: `scripts.probe.runner._rel` keeps its `(Path) -> str` signature; only the separator in the result changes. Task 4 appends to the same test file.

- [ ] **Step 1: Write the failing regression guard**

Create `tests/regression/test_evidence_portability.py`:

```python
"""Regression guards for what lands in tracked evidence.

Three defects share this file because they share a failure surface: a
`traces/` directory that a reviewer will open and a matrix cell will cite.

* D-05 -- `summary.json` recorded native path separators, so the same logical
  run diffed against itself across platforms.
* D-04 -- a run in which no model answered could be promoted into `traces/`.
* D-07 -- a UTF-8 BOM reached a tracked source file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probe.runner import _rel

pytestmark = pytest.mark.regression


def test_rel_uses_posix_separators_for_a_repo_relative_path() -> None:
    """D-05: evidence paths are POSIX on every platform.

    `str(Path)` is native, so a Windows capture wrote
    `configs\\probes\\02-verifier.md` where Linux wrote
    `configs/probes/02-verifier.md`. Tracked artifacts have to be
    byte-identical for the same run or the diff is noise.
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = _rel(repo_root / "configs" / "probes" / "02-verifier.md")

    assert result == "configs/probes/02-verifier.md"
    assert "\\" not in result


def test_rel_uses_posix_separators_for_a_path_outside_the_repo(tmp_path: Path) -> None:
    """The absolute fallback is normalised too, or the guard has a hole.

    A Windows absolute path keeps its drive letter -- that is unavoidable and
    correct -- but the separators between segments are still ours to fix.
    """
    outside = tmp_path / "somewhere" / "else.md"
    result = _rel(outside)

    assert "\\" not in result
    assert result.endswith("somewhere/else.md")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/regression/test_evidence_portability.py -v`
Expected: on Windows both FAIL (backslashes present). On POSIX both already pass — that is expected and does not mean the fix is unnecessary; it means the defect is Windows-only, which is exactly why it survived. Run the Windows leg before calling this verified.

- [ ] **Step 3: Write the minimal implementation**

Replace `_rel` in `scripts/probe/runner.py`:

```python
def _rel(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise -- always POSIX-separated.

    `str(Path)` is platform-native, so this used to write
    `configs\\probes\\02-verifier.md` on Windows and
    `configs/probes/02-verifier.md` on Linux for the same run. `summary.json`
    is tracked evidence; two captures of one run must not differ by separator.
    A Windows drive letter survives in the absolute branch, which is right --
    an absolute path off this machine is not portable and should not pretend.
    """
    resolved = path.resolve()
    try:
        return PurePosixPath(resolved.relative_to(REPO)).as_posix()
    except ValueError:
        return resolved.as_posix()
```

Add the import at the top of `scripts/probe/runner.py`, in the stdlib group:

```python
from pathlib import Path, PurePosixPath
```

`Path.relative_to` returns a `PurePath` whose parts are already split, so wrapping in `PurePosixPath` rejoins them with `/`. `Path.as_posix()` handles the absolute branch, including the drive letter.

- [ ] **Step 4: Run the guard to verify it passes**

Run: `python -m pytest tests/regression/test_evidence_portability.py -v`
Expected: 2 passed.

- [ ] **Step 5: Add the live-run acceptance case**

Append to `tests/aqa/test_aqa_live_endpoint.py`:

```python
def test_summary_json_paths_are_portable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-05 end to end: a real run writes a summary a reviewer can diff.

    The regression guard covers `_rel` directly; this covers the artifact the
    guard exists for, because `_rel` being right and `summary.json` being
    right are two claims and one test cannot make both.
    """
    with live_llm_endpoint() as base_url:
        run_probe(base_url, tmp_path, monkeypatch=monkeypatch)

    summary = read_summary(tmp_path)
    assert summary["prompt"] == "configs/probes/02-verifier.md"
    assert summary["system_prompt"] == "configs/probes/system-prompt.md"
```

- [ ] **Step 6: Run the lanes**

Run: `python -m pytest tests/aqa/ tests/regression/ -v` — expected: all pass.
Run: `python -m pytest -q && python -m ruff check . && python -m mypy` — expected: clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/probe/runner.py tests/regression/test_evidence_portability.py \
        tests/aqa/test_aqa_live_endpoint.py
git commit -m "fix(probe): write POSIX paths into summary.json (D-05)

str(Path) is native, so a Windows capture recorded
configs\\\\probes\\\\02-verifier.md where Linux recorded
configs/probes/02-verifier.md for the same run. summary.json is tracked
evidence and has to diff cleanly across platforms.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: D-04 and D-06 — the promotion content gate and the `--out` error

Two fixes, one task: both are "a bad input should produce a message, not a surprise", they touch adjacent code, and a reviewer would accept or reject them together.

**Files:**
- Modify: `scripts/promote_trace.py` (`promote`, and its argparse setup)
- Modify: `scripts/probe/cli.py` (the `out_dir.mkdir` call)
- Modify: `tests/regression/test_evidence_portability.py` (append)

**Interfaces:**
- Consumes: `scripts.promote_trace.promote`, `PromotionRefused` (both exist).
- Produces: `promote(source, name=None, destination_root=None, allow_error_run=False) -> Path`. The new keyword is last and defaults to today's behaviour for every existing caller.

- [ ] **Step 1: Write the failing regression guards**

Append to `tests/regression/test_evidence_portability.py`:

```python
import json

from promote_trace import PromotionRefused, promote


def _capture(root: Path, name: str, statuses: list[str]) -> Path:
    """A minimal capture directory shaped like one verifier_probe.py writes."""
    capture = root / name
    capture.mkdir(parents=True)
    (capture / "summary.json").write_text(
        json.dumps(
            {
                "captured": "20260907T000000Z",
                "results": [
                    {"slot": f"ollama:m{i}", "status": status, "screen": status}
                    for i, status in enumerate(statuses)
                ],
            }
        ),
        encoding="utf-8",
    )
    return capture


def test_promotion_refuses_a_run_where_no_model_answered(tmp_path: Path) -> None:
    """D-04: the secret scan is a confidentiality gate, not an evidence gate.

    Promotion used to check exactly one thing -- that no credential was in the
    transcript -- which is load-bearing and stays. But it meant `traces/` could
    hold, and `evidence/02-bakeoff.md` could cite, a run in which every slot
    errored before a request was sent.
    """
    capture = _capture(tmp_path / "raw", "20260907T000000Z-02-verifier", ["ERROR", "ERROR"])

    with pytest.raises(PromotionRefused, match="no model answered"):
        promote(capture, destination_root=tmp_path / "traces")


def test_promotion_allows_a_partial_run(tmp_path: Path) -> None:
    """One answering slot makes the capture evidence, whatever else failed."""
    capture = _capture(tmp_path / "raw", "20260907T000001Z-02-verifier", ["OK", "ERROR"])

    promoted = promote(capture, destination_root=tmp_path / "traces")

    assert promoted.is_dir()
    assert (promoted / "summary.json").is_file()


def test_promotion_allows_an_error_run_when_asked_explicitly(tmp_path: Path) -> None:
    """Sometimes the error transcript is the evidence. That has to be sayable."""
    capture = _capture(tmp_path / "raw", "20260907T000002Z-02-verifier", ["ERROR"])

    promoted = promote(capture, destination_root=tmp_path / "traces", allow_error_run=True)

    assert promoted.is_dir()


def test_promotion_still_accepts_a_capture_with_no_summary(tmp_path: Path) -> None:
    """Manual exports have no summary.json and are a supported input.

    `promote_trace.py`'s own docstring names them, so a content gate that
    assumed the file exists would refuse the case the tool was written for.
    """
    capture = tmp_path / "raw" / "manual-export"
    capture.mkdir(parents=True)
    (capture / "transcript.md").write_text("pasted by hand", encoding="utf-8")

    promoted = promote(capture, destination_root=tmp_path / "traces")

    assert (promoted / "transcript.md").is_file()


def test_unwritable_out_directory_is_an_argparse_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-06: every other bad argument in `main` reports through parser.error.

    A file where a directory belongs makes `mkdir` raise on every platform,
    which is the portable way to provoke this without needing permissions.
    """
    from probe.cli import main as probe_main

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        probe_main(["--models", "ollama:m", "--out", str(blocker)])

    assert excinfo.value.code == 2  # argparse's usage-error code
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/regression/test_evidence_portability.py -v`
Expected: `test_promotion_refuses_a_run_where_no_model_answered` FAILS (`DID NOT RAISE`), `test_promotion_allows_an_error_run_when_asked_explicitly` FAILS (`unexpected keyword argument 'allow_error_run'`), `test_unwritable_out_directory...` FAILS (raises `NotADirectoryError`/`FileExistsError`, not `SystemExit`). The other two pass already — they pin behaviour that must survive the fix.

- [ ] **Step 3: Implement the promotion content gate**

In `scripts/promote_trace.py`, add `import json` to the stdlib imports, then add this helper above `promote`:

```python
def _no_model_answered(source: Path) -> bool:
    """True when `summary.json` exists and says every slot errored.

    Absent, unreadable or unrecognised `summary.json` returns False: manual
    exports are a supported input and this gate must not refuse a capture it
    simply does not understand. It refuses only what it can positively read as
    a run in which nothing was contacted.
    """
    summary_path = source / "summary.json"
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return False
    rows = summary.get("results") if isinstance(summary, dict) else None
    if not isinstance(rows, list) or not rows:
        return False
    return all(isinstance(row, dict) and row.get("status") == "ERROR" for row in rows)
```

Change `promote`'s signature and add the gate immediately after the existing `destination.exists()` check:

```python
def promote(
    source: Path,
    name: str | None = None,
    destination_root: Path | None = None,
    allow_error_run: bool = False,
) -> Path:
```

```python
    if not allow_error_run and _no_model_answered(source):
        raise PromotionRefused(
            f"{source} records a run in which no model answered -- every result has "
            "status ERROR. Promoting it would put a capture into tracked traces/ that "
            "evidence/02-bakeoff.md could cite as a result. Fix the endpoint and "
            "re-run, or pass --allow-error-run if the error transcript is the evidence."
        )
```

Add the flag to the parser in the same file's `main`, alongside `--as`:

```python
    parser.add_argument(
        "--allow-error-run",
        action="store_true",
        help="promote even when every result errored (the error is the evidence)",
    )
```

and thread it through the `promote(...)` call there: `allow_error_run=args.allow_error_run`.

- [ ] **Step 4: Implement the `--out` error**

In `scripts/probe/cli.py`, replace:

```python
    out_dir = args.out / f"{stamp}-{args.prompt.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
```

with:

```python
    out_dir = args.out / f"{stamp}-{args.prompt.stem}"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        # Every other bad argument in this function reports through
        # parser.error. An unwritable --out reported through a traceback, so
        # one input was validated differently from the rest for no reason.
        parser.error(f"cannot create output directory {out_dir}: {error}")
```

- [ ] **Step 5: Run the guards to verify they pass**

Run: `python -m pytest tests/regression/test_evidence_portability.py -v`
Expected: all 7 pass.

- [ ] **Step 6: Run the lanes**

Run: `python -m pytest -q` — expected: green, and in particular the existing `promote_trace` tests still pass (the new keyword defaults to today's behaviour).
Run: `REQUIRE_MCP=1 python -m pytest -q` — expected: green.
Run: `python -m ruff check . && python -m mypy` — expected: clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/promote_trace.py scripts/probe/cli.py \
        tests/regression/test_evidence_portability.py
git commit -m "fix(probe): gate promotion on content, report --out errors (D-04/D-06)

promote() checked only that no credential was in the transcript, so a
capture in which every slot errored could be promoted into tracked
traces/ and cited by evidence/02-bakeoff.md. Manual exports without a
summary.json are still accepted, and --allow-error-run covers the case
where the error transcript is the evidence.

An unwritable --out raised a traceback while every other bad argument
reported through parser.error.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Lane D — the opt-in live vendor LLM acceptance test

The lane the environment could not run. It must be impossible for it to pass without contacting a vendor — an acceptance test that silently succeeds unconfigured is D-03 wearing a different hat.

**Files:**
- Create: `tests/aqa/test_aqa_live_llm.py`
- Modify: `pytest.ini` (register the `live_llm` marker)
- Modify: `Makefile` (add `test-live`, add it to `.PHONY`)

**Interfaces:**
- Consumes: `scripts.probe.config.PROVIDERS`, `scripts.probe.client.call_model`, and `run_probe`/`read_summary` from Task 1.
- Produces: nothing later tasks depend on. Task 7 wires lane C to CI and deliberately leaves lane D out.

- [ ] **Step 1: Register the marker**

In `pytest.ini`, append to the `markers` block:

```ini
    live_llm: Contacts a real vendor LLM endpoint; skipped unless PROBE_LIVE=1 and the slot resolves.
```

- [ ] **Step 2: Write the test**

Create `tests/aqa/test_aqa_live_llm.py`:

```python
"""AQA lane D: the probe against a real vendor LLM. Opt-in, never in CI.

Lane C (`test_aqa_live_endpoint.py`) proves the transport works by serving
loopback HTTP. It cannot prove that a real vendor's response shape, latency
and content still fit the screen -- only a vendor can, and no vendor
credential belongs in this repository's CI.

So this lane is opt-in twice over: `PROBE_LIVE=1` must be set *and* the slot's
endpoint or credential must resolve. Both conditions skip with a stated
reason rather than passing, because an acceptance test that goes green
without contacting anything is the same defect as D-03.

    PROBE_LIVE=1 PROBE_MODELS=ollama:llama3.1 make test-live
    PROBE_LIVE=1 PROBE_MODELS=github:gpt-4o GITHUB_TOKEN=... make test-live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from probe.client import call_model
from probe.config import PROBES, PROVIDERS
from tests.aqa.live_endpoint import read_summary

pytestmark = [pytest.mark.aqa, pytest.mark.live_llm]


def _slots() -> list[str]:
    return [slot.strip() for slot in os.environ.get("PROBE_MODELS", "").split(",") if slot.strip()]


def _skip_unless_configured() -> list[str]:
    """Return the runnable slots, or skip with the reason there are none."""
    if os.environ.get("PROBE_LIVE") != "1":
        pytest.skip("live vendor lane is opt-in: set PROBE_LIVE=1 to run it")
    slots = _slots()
    if not slots:
        pytest.skip("PROBE_LIVE=1 but PROBE_MODELS is empty; nothing to contact")
    for slot in slots:
        provider = slot.partition(":")[0].strip().lower()
        spec = PROVIDERS.get(provider)
        if spec is None:
            pytest.skip(f"slot {slot!r} names an unknown provider {provider!r}")
        if not os.environ.get(spec.endpoint_env, spec.endpoint_default):
            pytest.skip(f"{spec.endpoint_env} is unset for slot {slot!r}")
        if spec.credential_required and not os.environ.get(spec.credential_env, "").strip():
            pytest.skip(f"{spec.credential_env} is unset for slot {slot!r} ({spec.credential_hint})")
    return slots


def test_live_model_answers_over_the_real_transport() -> None:
    """Every configured slot returns usable content from a real vendor.

    Asserting on `status` and not on the verdict is deliberate: which verdict
    a given model declares is the bake-off's *question*, and a test that
    demanded a particular answer would be scoring the model rather than
    checking the harness.
    """
    slots = _skip_unless_configured()
    system = (PROBES / "system-prompt.md").read_text(encoding="utf-8")
    user = (PROBES / "02-verifier.md").read_text(encoding="utf-8")

    for slot in slots:
        result = call_model(slot, system, user, timeout=120)
        assert result["status"] == "OK", f"{slot}: {result.get('error')} {result.get('detail', '')}"
        assert result["text"].strip(), f"{slot} returned empty content"
        assert result["latency_ms"] > 0


def test_live_probe_run_produces_a_promotable_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live run writes a summary that the D-04 promotion gate accepts.

    This is the end-to-end claim the week's evidence chain rests on: a real
    model was contacted, the capture records it, and promotion will take it.
    """
    from probe.cli import main as probe_main
    from promote_trace import promote

    slots = _skip_unless_configured()
    code = probe_main([
        "--models", ",".join(slots),
        "--expect", "FINDINGS",
        "--timeout", "120",
        "--out", str(tmp_path / "raw"),
    ])
    assert code in (0, 1), f"live probe exited {code}; 2 means no model answered"

    summary = read_summary(tmp_path / "raw")
    assert any(row["status"] == "OK" for row in summary["results"])

    capture = next((tmp_path / "raw").glob("*/"))
    promoted = promote(capture, destination_root=tmp_path / "traces")
    assert (promoted / "summary.json").is_file()
```

- [ ] **Step 3: Run it unconfigured and confirm it skips with a reason**

Run: `python -m pytest tests/aqa/test_aqa_live_llm.py -v -rs`
Expected: 2 skipped, reason `live vendor lane is opt-in: set PROBE_LIVE=1 to run it`.

- [ ] **Step 4: Run it half-configured and confirm it still skips rather than passing**

Run: `PROBE_LIVE=1 python -m pytest tests/aqa/test_aqa_live_llm.py -v -rs`
Expected: 2 skipped, reason `PROBE_LIVE=1 but PROBE_MODELS is empty; nothing to contact`.

Run: `PROBE_LIVE=1 PROBE_MODELS=github:gpt-4o python -m pytest tests/aqa/test_aqa_live_llm.py -v -rs` with `GITHUB_TOKEN` unset.
Expected: 2 skipped, reason names `GITHUB_TOKEN`. **This is the important one** — it proves the lane cannot go green without a credential.

- [ ] **Step 5: Run it configured, if a vendor is reachable**

If a local Ollama is available: `ollama serve` in one terminal, then
`PROBE_LIVE=1 PROBE_MODELS=ollama:llama3.1 python -m pytest tests/aqa/test_aqa_live_llm.py -v`
Expected: 2 passed.

If no vendor is reachable, record that in the task's report as *not run*, with the skip reasons from Steps 3–4 as the evidence that the lane is wired correctly. Do not claim lane D passed.

- [ ] **Step 6: Add the Makefile target**

Add `test-live` to the `.PHONY` list, and add the target after `aqa`:

```make
test-live: ## Lane D: contact a real vendor LLM (opt-in: PROBE_LIVE=1 PROBE_MODELS=...)
	PROBE_LIVE=$${PROBE_LIVE:-1} $(PYTEST) -m live_llm -v -rs
```

- [ ] **Step 7: Run the lanes and commit**

Run: `python -m pytest -q -m aqa -rs` — expected: lane C passes, lane D skips with reasons.
Run: `python -m pytest -q && python -m ruff check . && python -m mypy` — expected: clean.

```bash
git add tests/aqa/test_aqa_live_llm.py pytest.ini Makefile
git commit -m "test(aqa): opt-in live vendor LLM lane

Lane C proves the transport with loopback HTTP; only a vendor can prove
a real response still fits the screen, and no vendor credential belongs
in CI. Skips with a stated reason unless PROBE_LIVE=1 and the slot
resolves -- a lane that goes green without contacting anything is the
defect it exists to catch.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: D-07 — guard the BOM repo-wide

The fix is already in the branch (a4d3f22). This adds the guard that was missing.

**Files:**
- Modify: `tests/regression/test_evidence_portability.py` (append)

**Interfaces:**
- Consumes: nothing new. Uses `subprocess` + `git ls-files` so the guard covers tracked files rather than a hand-maintained list.

- [ ] **Step 1: Write the guard**

Append to `tests/regression/test_evidence_portability.py`:

```python
import subprocess
import sys

_BOM = b"\xef\xbb\xbf"


def test_no_tracked_text_file_starts_with_a_utf8_bom() -> None:
    """D-07: a BOM at byte 0 of a Python file breaks tools that read bytes.

    `tests/integration/test_mcp_integration.py` carried one and it was removed
    in a4d3f22. Nothing stopped the next editor putting one back, in that file
    or any other -- Windows editors add them silently. Discovered via
    `git ls-files` rather than a listed set, because a hand-maintained list is
    how the third file gets missed.
    """
    repo_root = Path(__file__).resolve().parents[2]
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.py", "*.md", "*.yml", "*.yaml",
         "*.ini", "*.toml", "*.sh", "*.cfg", "*.txt"],
        cwd=repo_root, capture_output=True, check=True,
    )
    paths = [p for p in listed.stdout.decode("utf-8").split("\0") if p]
    assert paths, "git ls-files matched nothing -- discovery is broken, not the repo clean"

    offenders = [
        p for p in paths
        if (repo_root / p).is_file() and (repo_root / p).read_bytes()[:3] == _BOM
    ]
    assert not offenders, (
        "These tracked files start with a UTF-8 BOM: " + ", ".join(sorted(offenders)) +
        ". Re-save them as UTF-8 without a signature."
    )
```

Note `sys` is imported for the platform guard in Step 2; if you skip that guard, drop the import so ruff's `F401` stays quiet.

- [ ] **Step 2: Decide the git-absent case**

The suite already assumes git in `tests/test_evidence_hygiene.py`, so no skip guard is needed. If `git ls-files` fails in a container without git, `check=True` raises `CalledProcessError` and the test errors loudly — which is correct: a guard that cannot see the repo must not report clean.

- [ ] **Step 3: Run it and confirm it passes on this branch**

Run: `python -m pytest tests/regression/test_evidence_portability.py -k bom -v`
Expected: PASS (a4d3f22 already removed the only BOM).

- [ ] **Step 4: Prove the guard can fail**

A guard that has never failed is not known to work. Temporarily prepend a BOM to a tracked file and confirm the test catches it:

```bash
python -c "
from pathlib import Path
p = Path('tests/aqa/__init__.py'); b = p.read_bytes()
p.write_bytes(b'\xef\xbb\xbf' + b)
"
python -m pytest tests/regression/test_evidence_portability.py -k bom -v
# Expected: FAIL, naming tests/aqa/__init__.py
git checkout -- tests/aqa/__init__.py
python -m pytest tests/regression/test_evidence_portability.py -k bom -v
# Expected: PASS
git status --short   # Expected: no unintended modifications
```

- [ ] **Step 5: Commit**

```bash
git add tests/regression/test_evidence_portability.py
git commit -m "test(regression): guard against UTF-8 BOMs in tracked files (D-07)

a4d3f22 removed the BOM from tests/integration/test_mcp_integration.py
but nothing stopped it coming back, there or anywhere. Discovered via
git ls-files so a new file type is covered without editing a list.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Wire lane C into CI, record the changes, run the full gauntlet

**Files:**
- Modify: `.github/workflows/ci.yml` (the `transport` job)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: the branch is ready for a PR.

- [ ] **Step 1: Add the AQA step to the transport job**

Lane C belongs in `transport`, not `contract`: `contract` installs pytest only and its whole value is running with nothing installed, while `transport` already has the package. Lane C needs no SDK but does need `scripts/` importable, which both have — `transport` is the right home because it is the job that already means "the real thing runs".

After the existing "The suite, with the SDK required" step in the `transport` job, add:

```yaml
      - name: AQA lane C -- the probe against a real HTTP endpoint
        # Loopback ThreadingHTTPServer on an ephemeral port: no credential, no
        # vendor, no network egress. Run explicitly rather than relying on the
        # step above to have collected it, so a marker rename cannot silently
        # drop the only test that opens a socket against the probe client.
        #
        # The vendor lane (`-m live_llm`) is deliberately absent. It needs a
        # credential, and a credential in CI here would make the tick mean
        # less, not more.
        run: python -m pytest -q -m aqa -rs
```

- [ ] **Step 2: Verify the workflow is valid YAML**

Run:

```bash
python -c "
import sys, pathlib
try:
    import yaml
except ImportError:
    sys.exit('PyYAML not installed; skip -- GitHub will validate on push')
d = yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8'))
steps = d['jobs']['transport']['steps']
names = [s.get('name') for s in steps]
assert any(n and 'AQA lane C' in n for n in names), names
print('transport steps:', names)
"
```

Expected: the step list printed, ending with the AQA step.

- [ ] **Step 3: Confirm the coverage-floor guard still holds**

The new step must not have introduced a `--fail-under`:

Run: `python -m pytest tests/regression/test_regression_suite.py -k coverage -v`
Expected: 2 passed.

- [ ] **Step 4: Update CHANGELOG.md**

Add at the top of the `Unreleased` section (match the file's existing heading style — read it before editing):

```markdown
### Fixed

- **Probe exit code no longer certifies a run that never happened (D-03).**
  `verifier_probe.py` returned 0 whenever nothing laundered, so an unreachable
  endpoint, an unknown provider or a missing credential all reported success
  and `make probe` was green for a bake-off that contacted no model. The
  contract is now: `0` usable run with no laundering, `1` at least one row
  laundered, `2` no row reached a model. A partial run still exits 0.
- **Promotion refuses a capture in which no model answered (D-04).**
  `promote_trace.py` gated only on the credential scan, so `traces/` could
  hold, and `evidence/02-bakeoff.md` could cite, a run where every slot
  errored. Captures without a `summary.json` (manual exports) are unaffected;
  `--allow-error-run` covers the case where the error transcript is the point.
- **`summary.json` records POSIX paths on every platform (D-05).**
  `_rel` returned `str(Path)`, so a Windows capture wrote
  `configs\probes\02-verifier.md` where Linux wrote `configs/probes/...` for
  the same run, and tracked evidence diffed against itself.
- **An unwritable `--out` reports a usage error, not a traceback (D-06).**

### Added

- **AQA lane C** (`tests/aqa/test_aqa_live_endpoint.py`): the probe driven
  against a real loopback HTTP server. The transport had only ever been tested
  through an injected `post_fn`. Runs in CI's `transport` job; needs no
  credential.
- **AQA lane D** (`tests/aqa/test_aqa_live_llm.py`, marker `live_llm`): opt-in
  acceptance against a real vendor LLM. Skips with a stated reason unless
  `PROBE_LIVE=1` and the slot resolves. Never wired to CI.
- **Regression guards** for D-03 (`tests/regression/test_probe_exit_contract.py`)
  and for D-04/D-05/D-07 (`tests/regression/test_evidence_portability.py`),
  including a repo-wide UTF-8 BOM check discovered via `git ls-files`.
```

- [ ] **Step 5: Run the full gauntlet, all four lanes**

```bash
python -m ruff check .
python -m mypy
python -m pytest -q -rs                                   # lane A
REQUIRE_MCP=1 python -m pytest -q -rs                     # lane B
python -m pytest -q -m aqa -rs                            # lane C
python -m pytest -q -m live_llm -rs                       # lane D (expect skips)
python -m pytest -q -m regression -v
python -m coverage run --branch --source=mcp_server/src,scripts -m pytest -q
python -m coverage report
python scripts/scan_evidence.py
git status --short                                        # must be empty
```

Expected: ruff clean, mypy clean, lanes A/B/C green, lane D skipped with reasons, coverage at or above 90, scan clean, working tree clean.

If `make` is available (it needs bash; on Windows use Git Bash or WSL): `make validate` runs lint → typecheck → coverage → regression → secrets → shellcheck in CI's order.

- [ ] **Step 6: Report honestly before committing**

Write the numbers you actually saw, not the numbers expected here. In particular:
- If lane D could not be run for lack of a vendor, say **"lane D not run — no vendor endpoint or credential available; skip reasons verified"**, not "lane D passed".
- If coverage moved, quote the new total.
- If any lane failed, stop and triage it before committing. Do not commit around a red lane.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml CHANGELOG.md
git commit -m "ci: run the AQA HTTP lane in the transport job

Lane C needs no credential, so it can run in CI, and it is the only test
that opens a socket against the probe client. Run explicitly rather than
by collection, so renaming the marker cannot silently drop it. The vendor
lane stays out: a credential here would make the tick mean less.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Push and open the PR**

```bash
git push -u origin qa/origin-parity-defect-triage
```

PR body should state: the four defects with their RCA one-liners, which lanes were run and which were not and why, and the coverage number before (93%) and after.

---

## Self-Review

**1. Coverage of the stated requirements.** Compare to origin — done (Diagnostic Baseline). New branch off preceding work — done (`qa/origin-parity-defect-triage` from `origin/h` a4d3f22, cut before this plan was written). All tests and e2e with and without mocks — lanes A, B, C, plus the CI-`contract` parity run with the SDK hidden. GPU — checked and shown not applicable, with the evidence. Live LLM API — lane D, Task 5, opt-in because no credential exists here. Triage and RCA — five defects, each with a reproduction and a root cause. Fix all defects — Tasks 2, 3, 4; D-07 was already fixed upstream and is stated as such rather than re-fixed. Regression — Tasks 2, 3, 4, 6. AQA — Tasks 1, 2, 3, 5.

**2. Placeholders.** None. Every code step carries the actual code. The only intentionally-unresolved item is Task 5 Step 5, which depends on whether a vendor is reachable at execution time, and it states both branches and forbids claiming a pass.

**3. Type and name consistency.** `live_llm_endpoint`/`run_probe`/`read_summary` are defined in Task 1 Step 3 and used with matching signatures in Tasks 2, 3 and 5. `promote(source, name, destination_root, allow_error_run)` is defined in Task 4 Step 3 and called with that keyword in Task 4 Step 1 and Task 5 Step 2. `_rel(Path) -> str` keeps its signature in Task 3. `ERROR` and `LAUNDERED` are imported from `probe.screen` in Task 2 Step 3, which is where they live. Exit codes 0/1/2 are consistent across Task 2, Task 5's `assert code in (0, 1)`, and the CHANGELOG.

**4. One tension worth flagging to the executor.** Task 2's `all(row["screen"] == ERROR ...)` and Task 4's `all(row.get("status") == "ERROR" ...)` read different keys. That is correct rather than sloppy — `screen` is the CLI's in-memory row shape and `status` is what `summary.json` persists — but they are the same concept in two vocabularies, and if either shape changes both must move together. The tests in Tasks 2 and 4 pin each independently.
