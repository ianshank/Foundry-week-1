"""stdout belongs to the JSON-RPC protocol. These tests keep it that way.

An MCP stdio server frames its messages on stdout. One log line written there
corrupts the stream, and the symptom is not a misplaced log -- it is the tool
vanishing from Agent Builder, or a parse error with no visible cause. This is
precisely the invariant that survives code review and then dies to a
convenience `print()` three weeks later, so it gets a test rather than a
comment.
"""

from __future__ import annotations

import json
import logging

import pytest

from foundry_spike_mcp import logging_setup
from foundry_spike_mcp.config import LogConfig


@pytest.fixture(autouse=True)
def fresh_logger():
    """Rebuild the logger per test; `configure` is idempotent by design."""
    logging_setup._configured = False
    logger = logging.getLogger(logging_setup.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    yield
    logging_setup._configured = False


def test_every_handler_writes_to_stderr(capsys):
    logger = logging_setup.configure(LogConfig(level="DEBUG"), force=True)
    logger.error("a message that must not reach stdout")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "a message that must not reach stdout" in captured.err


def test_no_handler_targets_stdout():
    """Belt and braces: assert the stream object itself, not just this run's
    output, so a handler added later with the wrong stream fails here."""
    import sys

    logger = logging_setup.configure(LogConfig(), force=True)
    for handler in logger.handlers:
        stream = getattr(handler, "stream", None)
        assert stream is not sys.stdout
        assert stream is sys.stderr


def test_records_do_not_propagate_to_the_root_logger():
    """The root logger's handlers are not ours and cannot be promised to point
    at stderr; propagation would route around this module's only guarantee."""
    logger = logging_setup.configure(LogConfig(), force=True)
    assert logger.propagate is False


def test_configure_is_idempotent_so_lines_are_not_duplicated(capsys):
    logging_setup.configure(LogConfig(level="INFO"), force=True)
    logging_setup.configure(LogConfig(level="INFO"))
    logging_setup.configure(LogConfig(level="INFO"))
    logging.getLogger(logging_setup.LOGGER_NAME).info("once")
    assert capsys.readouterr().err.count("once") == 1


def test_json_format_emits_one_object_per_line(capsys):
    logger = logging_setup.configure(LogConfig(level="INFO", fmt="json"), force=True)
    logger.info("tool call", extra={"tool": "planlint", "verdict": "BLOCKED", "exit_code": 2})
    line = capsys.readouterr().err.strip()
    payload = json.loads(line)
    assert payload["message"] == "tool call"
    assert payload["verdict"] == "BLOCKED"
    assert payload["exit_code"] == 2


def test_text_format_appends_context_pairs(capsys):
    logger = logging_setup.configure(LogConfig(level="INFO"), force=True)
    logger.info("tool call", extra={"tool": "score_run", "verdict": "PASS"})
    err = capsys.readouterr().err
    assert "tool='score_run'" in err and "verdict='PASS'" in err


def test_default_level_keeps_a_well_behaved_server_silent(capsys):
    logger = logging_setup.configure(LogConfig(), force=True)
    logger.info("routine")
    logger.debug("detail")
    assert capsys.readouterr().err == ""


def test_blocked_is_a_warning_so_it_is_visible_without_debug(capsys):
    """BLOCKED is not an error -- the contract says so loudly -- but it is the
    state an operator most often has to explain, so it should not need DEBUG."""
    logger = logging_setup.configure(LogConfig(), force=True)
    logging_setup.log_result(logger, "lint_openspec", {"verdict": "BLOCKED", "exit_code": 2})
    err = capsys.readouterr().err
    assert "could not evaluate" in err
    assert "WARNING" in err


def test_pass_does_not_warn(capsys):
    logger = logging_setup.configure(LogConfig(), force=True)
    logging_setup.log_result(logger, "lint_openspec", {"verdict": "PASS", "exit_code": 0})
    assert capsys.readouterr().err == ""


def test_log_result_omits_absent_context_rather_than_logging_none(capsys):
    logger = logging_setup.configure(LogConfig(level="INFO", fmt="json"), force=True)
    logging_setup.log_result(logger, "score_run", {"verdict": "PASS"})
    payload = json.loads(capsys.readouterr().err.strip())
    assert "exit_code" not in payload
    assert "blocked_reason" not in payload


def test_tool_modules_never_print_to_stdout():
    """Static check across the package: `print` with no explicit stream writes
    to stdout, which is the protocol channel."""
    import ast
    from pathlib import Path

    src = Path(logging_setup.__file__).parent
    offenders = []
    for path in src.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
                and not any(kw.arg == "file" for kw in node.keywords)
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    # __main__.py's selfcheck is a CLI, not the server; it is allowed to print.
    offenders = [o for o in offenders if not o.startswith("__main__.py")]
    assert not offenders, f"bare print() writes to the protocol channel: {offenders}"
