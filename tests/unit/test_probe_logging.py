"""The probe plane's logging, including the invariant that makes it safe.

`scripts/probe/` writes to stderr because stdout on the server plane is
JSON-RPC and on the probe plane is the report table that a human pipes
somewhere. A handler pointed at stdout corrupts both, silently, and the
symptom shows up somewhere else entirely -- which is why
`foundry_spike_mcp.logging_setup` has a test asserting the same thing and why
reusing that module was preferred over writing a second one.
"""

from __future__ import annotations

import logging

import pytest

from probe.logging_setup import configure, get_logger


def test_the_logger_is_namespaced_under_the_package() -> None:
    """One namespace for both planes, so one level switch governs both."""
    assert get_logger("runner").name.startswith("foundry_spike_mcp")


def test_two_calls_return_the_same_logger() -> None:
    """`logging.getLogger` is a registry; a per-call logger would stack handlers."""
    assert get_logger("runner") is get_logger("runner")


def test_no_handler_anywhere_in_the_chain_writes_to_stdout() -> None:
    """The invariant. stdout is JSON-RPC on one plane and the report on the other.

    Walks the ancestry rather than checking one logger, because a handler
    installed on a parent is what actually receives the record.
    """
    configure(verbose=False)
    logger: logging.Logger | None = get_logger("runner")

    seen = 0
    while logger:
        for handler in logger.handlers:
            stream = getattr(handler, "stream", None)
            if stream is not None:
                seen += 1
                assert stream is not __import__("sys").stdout, (
                    f"{logger.name} has a handler writing to stdout"
                )
        logger = logger.parent if logger.propagate else None

    assert seen, "no stream handler found at all -- the probe would log nowhere"


def test_verbose_turns_on_debug_and_the_default_does_not() -> None:
    """`--verbose` is the one switch; it must actually move the level."""
    configure(verbose=True)
    assert logging.getLogger("foundry_spike_mcp").level == logging.DEBUG

    configure(verbose=False)
    assert logging.getLogger("foundry_spike_mcp").level != logging.DEBUG


def test_a_record_survives_when_the_package_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback arm is load-bearing, not decoration.

    The Docker `contract` stage installs nothing and `make probe` puts only the
    repo root and `scripts/` on the path. A probe that refused to run because
    it could not configure logging would be a worse failure than one that logs
    plainly.
    """
    import probe.logging_setup as mod

    monkeypatch.setattr(mod, "_SHARED", False)
    logger = mod.get_logger("fallback-check")

    assert logger.handlers or logger.parent, "the fallback produced a logger that goes nowhere"


def test_the_fallback_logger_does_not_propagate_to_an_unknown_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback installs its own stderr handler, so propagation is a leak.

    Raised in review of PR #13. `get_logger`'s fallback added a stderr handler
    and left `propagate` at its default `True`, so any handler higher in the
    chain -- including a root handler pointed at **stdout**, which
    `logging.basicConfig()` installs by default -- would also receive every
    probe record. That weakens the one invariant this module exists to hold,
    and duplicates every line when a root handler happens to exist.

    The shared path does not need this: `foundry_spike_mcp.logging_setup`
    already owns its own propagation. Only the fallback, which is the arm that
    runs where the package is absent, has to defend itself.
    """
    import logging as _logging

    import probe.logging_setup as mod

    monkeypatch.setattr(mod, "_SHARED", False)

    # A root handler aimed at stdout is exactly what basicConfig() leaves behind.
    root = _logging.getLogger()
    sentinel = _logging.StreamHandler(stream=__import__("sys").stdout)
    root.addHandler(sentinel)
    try:
        logger = mod.get_logger("propagation-check")
        assert not logger.propagate, (
            "the fallback logger propagates, so a root stdout handler receives "
            "probe records and the stderr-only invariant is not held"
        )
    finally:
        root.removeHandler(sentinel)
