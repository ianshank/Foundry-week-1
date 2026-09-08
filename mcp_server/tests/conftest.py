from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest


def configured_env_names() -> tuple[str, ...]:
    """Every environment variable the package reads, from the source of truth.

    This was a hand-written seven-name tuple against a `config.py` that
    declares fifteen, and the eight it omitted were not cosmetic: with
    `EVAL_MAX_ARTIFACT_BYTES=1` in the shell, eighteen tests in
    `test_scoring.py` fail; with `FOUNDRY_SPIKE_STDOUT_LIMIT=1`,
    `test_exit_two_is_blocked_not_pass_and_does_not_raise` fails. The contract
    suite's result depended on the developer's environment, which is the exact
    failure the fixture below exists to prevent.

    `tests/conftest.py` already solved this by reflection; the fix never
    reached here. Reflecting over `ENV_*` means a setting added to `config.py`
    cannot be added without this isolation covering it.

    Deliberately imports only `foundry_spike_mcp`: `cd mcp_server && pytest`
    and the Docker `contract` stage both run this suite standalone, with
    neither `scripts/` nor the root `tests/` on the path.
    """
    from foundry_spike_mcp import config

    return tuple(
        value
        for name, value in vars(config).items()
        if name.startswith("ENV_") and isinstance(value, str)
    )


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in configured_env_names():
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
        # Use sys.stdout.buffer.write to bypass the platform's default text
        # encoding (cp1252 on Windows). Tests may pass non-ASCII payloads such
        # as CJK characters, and sys.stdout on Windows defaults to the locale
        # encoding, which cannot represent them. Writing to the binary buffer
        # with explicit UTF-8 works everywhere and matches how planlint.py
        # reads back the stream: encoding="utf-8", errors="replace" on Popen.
        py_script.write_text(
            "import sys, time\n"
            f"time.sleep({sleep!r})\n"
            f"sys.stdout.buffer.write({stdout.encode('utf-8')!r})\n"
            f"sys.stdout.buffer.flush()\n"
            f"sys.stderr.buffer.write({stderr.encode('utf-8')!r})\n"
            f"sys.stderr.buffer.flush()\n"
            f"sys.exit({exit_code!r})\n",
            encoding="utf-8",
        )
        if sys.platform == "win32":
            bat_script = tmp_path / "bin" / f"{name}.bat"
            # PYTHONUTF8=1 is not needed here because we write to the binary
            # buffer directly; it is set anyway for defensive consistency.
            bat_script.write_text(
                f'@set PYTHONUTF8=1\r\n@"{sys.executable}" "{py_script}" %*'
            )
            return bat_script
        script.write_text(
            f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
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
