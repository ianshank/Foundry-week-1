from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

# Every test starts from a known-empty environment for the variables the tools
# read. Otherwise a developer's real PLANLINT_TARGET leaks into the suite and
# the guard tests pass for the wrong reason.
_TOOL_ENV = (
    "PLANLINT_TARGET",
    "PLANLINT_ALLOWED_ROOTS",
    "PLANLINT_BIN",
    "PLANLINT_TIMEOUT",
    "PLANLINT_JSON_FLAG",
    "EVAL_SINK_DIR",
    "EVAL_ALLOWED_ROOTS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _TOOL_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_planlint(tmp_path: Path):
    """Build a stand-in `planlint` with a chosen exit code and output.

    A fake binary rather than a mocked `subprocess.run`: the failure modes
    under test -- a timeout, a missing executable, a usage message on stdout --
    are properties of real process handling, and mocking them out would test
    the mock.
    """

    def _make(
        *,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        sleep: float = 0.0,
        name: str = "planlint",
    ) -> Path:
        script = tmp_path / "bin" / name
        script.parent.mkdir(parents=True, exist_ok=True)
        py_script = tmp_path / "bin" / f"{name}.py"
        py_script.write_text(
            "import sys, time\n"
            f"time.sleep({sleep!r})\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"sys.exit({exit_code!r})\n",
            encoding="utf-8",
        )
        if sys.platform == "win32":
            bat_script = tmp_path / "bin" / f"{name}.bat"
            bat_script.write_text(f'@"{sys.executable}" "{py_script}" %*')
            return bat_script
        script.write_text(f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(), encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return script

    return _make


@pytest.fixture
def spec_repo(tmp_path: Path) -> Path:
    """An allowed target directory."""
    repo = tmp_path / "repo"
    (repo / "openspec" / "changes").mkdir(parents=True)
    return repo


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, spec_repo: Path):
    """Point the tools at a fake binary and an allowed root."""

    def _configure(binary: Path, target: Path | None = None, **env: str) -> Path:
        chosen = target or spec_repo
        monkeypatch.setenv("PLANLINT_BIN", str(binary))
        monkeypatch.setenv("PLANLINT_TARGET", str(chosen))
        monkeypatch.setenv("PLANLINT_ALLOWED_ROOTS", str(chosen))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return chosen

    return _configure


# `pythonpath` in pyproject covers `pytest` from the package root; this keeps
# the suite runnable from anywhere, including a bare `python -m pytest`.
sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1] / "src"))
