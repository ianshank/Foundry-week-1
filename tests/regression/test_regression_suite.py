"""Regression test suite - guarding against previously fixed defects.

Every test here is a regression guard for a specific finding that was once broken
and fixed. Cross-referenced to NEXT_STEPS.md findings 4-15 and Windows
platform-parity defects D-01/D-02 (shebang scripts, CJK stdout encoding).
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "mcp_server" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from foundry_spike_mcp.config import EvalConfig, PlanlintConfig  # noqa: E402
from foundry_spike_mcp.planlint import lint_openspec, run_verb  # noqa: E402
from foundry_spike_mcp.scoring import score_run  # noqa: E402
from foundry_spike_mcp.verdicts import (  # noqa: E402
    BLOCKED,
    BLOCKED_ARTIFACT_UNREADABLE,
    BLOCKED_TOOL_NOT_FOUND,
    BLOCKED_UNEXPECTED_EXIT,
    FINDINGS,
    PASS,
)

pytestmark = pytest.mark.regression


def _make_stub(tmp_path: Path, body: str, name: str = "planlint") -> Path:
    """Cross-platform executable Python stub. .bat on Windows, shebang on POSIX."""
    script_dir = tmp_path / "bin"
    script_dir.mkdir(parents=True, exist_ok=True)
    py_script = script_dir / f"{name}.py"
    py_script.write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        bat = script_dir / f"{name}.bat"
        bat.write_text(f'@set PYTHONUTF8=1\r\n@"{sys.executable}" "{py_script}" %*')
        return bat
    sh = script_dir / name
    sh.write_text(
        f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return sh


def _target_dir(tmp_path: Path) -> Path:
    t = tmp_path / "repo"
    (t / "openspec" / "changes").mkdir(parents=True)
    return t


# D-01/D-02 Windows platform parity
class TestWindowsPlatformParity:
    def test_ascii_payload_stub_executes(self, tmp_path: Path) -> None:
        target = _target_dir(tmp_path)
        stub = _make_stub(tmp_path, 'import sys\nsys.stdout.buffer.write(b\'{"findings": []}\')\nsys.exit(0)\n')
        cfg = PlanlintConfig(binary=str(stub), target=str(target), allowed_roots=(target,))
        assert lint_openspec(config=cfg)["verdict"] == PASS

    def test_cjk_payload_survives_round_trip(self, tmp_path: Path) -> None:
        payload = json.dumps({"m": "\u6f22" * 10}, ensure_ascii=False)
        stub = _make_stub(tmp_path, f'import sys\nsys.stdout.buffer.write({payload.encode("utf-8")!r})\nsys.exit(1)\n')
        target = _target_dir(tmp_path)
        cfg = PlanlintConfig(binary=str(stub), target=str(target), allowed_roots=(target,))
        result = lint_openspec(config=cfg)
        assert result["verdict"] == FINDINGS
        assert result["findings"] == {"m": "\u6f22" * 10}

    def test_invalid_bytes_produce_parse_error_not_exception(self, tmp_path: Path) -> None:
        stub = _make_stub(tmp_path, 'import sys\nsys.stdout.buffer.write(b"\\xff\\xfe\\xff")\nsys.exit(1)\n')
        target = _target_dir(tmp_path)
        cfg = PlanlintConfig(binary=str(stub), target=str(target), allowed_roots=(target,))
        result = lint_openspec(config=cfg)
        assert result["verdict"] == FINDINGS
        assert result["findings"] is None
        assert result["findings_parse_error"] is not None

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals not available on Windows")
    def test_signal_killed_process_maps_to_blocked_unexpected_exit(self, tmp_path: Path) -> None:
        stub = _make_stub(tmp_path, "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n", name="kill-stub")
        target = _target_dir(tmp_path)
        cfg = PlanlintConfig(binary=str(stub), target=str(target), allowed_roots=(target,))
        result = lint_openspec(config=cfg)
        assert result["verdict"] == BLOCKED
        assert result["blocked_reason"] == BLOCKED_UNEXPECTED_EXIT
        assert result["exit_code"] is not None and result["exit_code"] < 0


# Finding #5 - Stable envelope shape
class TestStableEnvelopeShape:
    EXPECTED = {
        "verdict", "exit_code", "blocked_reason", "blocked_detail",
        "verb", "target", "command", "duration_ms", "findings",
        "findings_parse_error", "findings_truncated", "stdout_excerpt", "stderr", "contract",
    }

    def test_all_keys_present_on_pass(self, tmp_path: Path) -> None:
        target = _target_dir(tmp_path)
        stub = _make_stub(tmp_path, 'import sys\nsys.stdout.buffer.write(b\'{"findings": []}\')\nsys.exit(0)\n')
        cfg = PlanlintConfig(binary=str(stub), target=str(target), allowed_roots=(target,))
        assert self.EXPECTED.issubset(lint_openspec(config=cfg).keys())

    def test_all_keys_present_on_blocked(self) -> None:
        assert self.EXPECTED.issubset(lint_openspec().keys())


# Finding #4 - RecursionError never escapes score_run
class TestRecursionErrorContainment:
    def test_deeply_nested_artifact_is_blocked_not_raised(self, tmp_path: Path) -> None:
        f = tmp_path / "deep.json"
        f.write_text("[" * 20_000 + "]" * 20_000, encoding="utf-8")
        cfg = EvalConfig(sink_dir=tmp_path, allowed_roots=(tmp_path,))
        result = score_run("deep", artifact_path=str(f), config=cfg)
        assert result["verdict"] == BLOCKED
        assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE


# Finding #9 - All listed verbs are reachable
@pytest.mark.parametrize("verb", ["validate", "detect", "list", "explain", "check", "report"])
def test_all_allowed_verbs_reach_subprocess(tmp_path: Path, verb: str) -> None:
    target = _target_dir(tmp_path)
    stub = _make_stub(tmp_path, "import sys\nsys.exit(0)\n")
    cfg = PlanlintConfig(binary=str(stub), target=str(target), allowed_roots=(target,))
    result = run_verb(verb, config=cfg)
    assert result.get("blocked_reason") != BLOCKED_TOOL_NOT_FOUND, f"Verb {verb!r} never reached the subprocess"


# Finding #14 - Coverage gate configured
def test_coverage_gate_is_configured_in_pyproject() -> None:
    ini = _REPO_ROOT / "pyproject.toml"
    assert "fail_under" in ini.read_text(encoding="utf-8")
