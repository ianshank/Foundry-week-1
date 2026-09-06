"""Path setup and isolation for the root suite.

Two conftests were written for this directory independently -- one on main for
import paths, one here for state isolation -- and the merge kept both jobs.

Isolation, the half this branch added:

`mcp_server/tests/conftest.py` clears the tool variables before each test so a
developer's real `PLANLINT_TARGET` cannot leak in and make a guard test pass
for the wrong reason. This directory had no conftest at all, and two kinds of
state were leaking across it:

* **Environment.** The tools read configuration from the process environment.
  A test that sets a variable without `monkeypatch` leaves it set for whatever
  runs next, and the order tests run in is not part of anyone's design.
* **Logging.** `logging_setup` keeps a module-level `_configured` flag and
  installs a handler on a package-level logger, so a test calling
  `configure(force=True)` at DEBUG changes the level for every test after it.
  `mcp_server/tests/test_logging.py` resets it; nothing here did.

Neither has caused a failure yet, which is the reason to fix it now rather
than after a rearrangement makes it look like a real bug. It is also what
stops `pytest -p xdist` from being usable, since both leaks are process-global.

The variable list is derived from `config.py` rather than typed out, so a new
setting cannot be added without this isolation covering it.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

# Repo root, `scripts/` and the package source, as main set up for the suites
# that landed with PR #5 -- they import `probe.*` and the scripts directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (_REPO_ROOT, _REPO_ROOT / "scripts", _REPO_ROOT / "mcp_server" / "src"):
    if os.fspath(_path) not in sys.path:
        sys.path.insert(0, os.fspath(_path))


def _configured_env_names() -> tuple[str, ...]:
    """Every environment variable the package reads, from the source of truth.

    Enumerating them here by hand is how the list goes stale: the two ceilings
    added for the findings payload would have been missed, and the isolation
    would have quietly stopped covering the newest settings -- exactly when it
    is needed most.
    """
    from foundry_spike_mcp import config

    return tuple(
        value
        for name, value in vars(config).items()
        if name.startswith("ENV_") and isinstance(value, str)
    )


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a known-empty configuration."""
    for name in _configured_env_names():
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def restore_logging():
    """Put the package logger back the way it was found.

    Handlers and level are global to the process, so a test that reconfigures
    logging to assert on it otherwise dictates the level for every test that
    runs afterwards.
    """
    from foundry_spike_mcp import logging_setup

    logger = logging_setup.get_logger()
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    saved_propagate = logger.propagate
    saved_flag = logging_setup._configured

    yield

    logger.handlers = saved_handlers
    logger.setLevel(saved_level)
    logger.propagate = saved_propagate
    logging_setup._configured = saved_flag


# ---------------------------------------------------------------------------
# Shared cross-platform test infrastructure
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_stub(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Factory fixture — returns a callable that creates cross-platform executable stubs.

    Usage::

        def test_foo(make_stub, tmp_path):
            stub = make_stub(
                body='import sys; sys.stdout.buffer.write(b\'{"findings": []}\'); sys.exit(0)',
                name="planlint",
            )
            # stub is a Path to a .bat on Windows, shebang script on POSIX

    The factory always writes *body* to ``bin/<name>.py`` and produces a launcher
    appropriate for the host OS.  All I/O in *body* must use
    ``sys.stdout.buffer.write(bytes)`` rather than ``sys.stdout.write(str)`` so
    the payload survives the Windows ``cp1252`` code page without a
    ``UnicodeEncodeError``.
    """

    def _factory(body: str, name: str = "planlint") -> Path:
        script_dir = tmp_path / "bin"
        script_dir.mkdir(parents=True, exist_ok=True)
        py_script = script_dir / f"{name}.py"
        py_script.write_text(body, encoding="utf-8")
        if sys.platform == "win32":
            bat = script_dir / f"{name}.bat"
            # PYTHONUTF8=1 forces UTF-8 stdio on Windows, avoiding cp1252 errors.
            bat.write_text(f'@set PYTHONUTF8=1\r\n@"{sys.executable}" "{py_script}" %*')
            return bat
        sh = script_dir / name
        sh.write_text(
            f"#!/usr/bin/env {sys.executable}\n" + py_script.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        sh.chmod(sh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return sh

    return _factory


@pytest.fixture()
def spec_repo(tmp_path: Path) -> Path:
    """A minimal planlint-compatible repository tree in ``tmp_path``.

    Creates the directory structure that ``check_target`` and ``lint_openspec``
    expect to find — ``openspec/changes/`` — so tests can pass a real filesystem
    path rather than a fake string.

    Returns the repo root (not the ``openspec/`` subdirectory).
    """
    root = tmp_path / "repo"
    (root / "openspec" / "changes").mkdir(parents=True)
    return root
