"""Isolation for the root suite, which had none.

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
import sys
from pathlib import Path

import pytest

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
