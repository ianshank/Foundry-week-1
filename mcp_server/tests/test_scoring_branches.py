"""Branch coverage tests for edge cases in foundry_spike_mcp.scoring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from foundry_spike_mcp.config import EvalConfig
from foundry_spike_mcp.scoring import (
    BLOCKED_CONFIG_ERROR,
    _collect_scorers,
    _normalise_passed,
    score_run,
)
from foundry_spike_mcp.verdicts import (
    BLOCKED,
    BLOCKED_ARTIFACT_SCHEMA,
    BLOCKED_ARTIFACT_UNREADABLE,
    BLOCKED_GUARD_REJECTED,
)


def test_normalise_passed_strings():
    for val in ("true", "True", "PASS", "passed", "  pass  "):
        assert _normalise_passed(val) is True

    for val in ("false", "False", "FAIL", "failed", "  fail  "):
        assert _normalise_passed(val) is False

    for val in ("null", "None", "skipped", "n/a", "", "   "):
        assert _normalise_passed(val) is None

    assert _normalise_passed("something_else") == "unreadable:'something_else'"
    assert _normalise_passed(123) == "unreadable:123"


def test_collect_scorers_edge_cases():
    # Results is not a list
    scorers, ignored = _collect_scorers({"results": "invalid_not_a_list"})
    assert scorers == []
    assert len(ignored) == 1
    assert "not a list" in ignored[0]["why"]

    # Results contains non-dict item
    scorers, ignored = _collect_scorers({"results": ["not_a_dict"]})
    assert scorers == []
    assert len(ignored) == 1
    assert "not an object" in ignored[0]["why"]

    # Results contains item missing passed key
    scorers, ignored = _collect_scorers({"results": [{"scorer": "my_scorer"}]})
    assert scorers == []
    assert len(ignored) == 1
    assert "missing 'passed' verdict key" in ignored[0]["why"]

    # Results contains item missing name key
    scorers, ignored = _collect_scorers({"results": [{"passed": True}]})
    assert scorers == []
    assert len(ignored) == 1
    assert "missing 'scorer' name key" in ignored[0]["why"]


def test_score_run_config_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVAL_ALLOWED_ROOTS", "relative/path/which/fails")
    result = score_run("run-config-err")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_CONFIG_ERROR


def test_score_run_sink_dir_none_without_artifact_path(tmp_path: Path):
    config = EvalConfig(allowed_roots=(tmp_path,), sink_dir=None)
    result = score_run("run-no-sink", config=config)
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED
    assert "EVAL_SINK_DIR is unset" in result["blocked_detail"]


def test_score_run_os_error_handling(tmp_path: Path):
    sink_file = tmp_path / "run-os-err.json"
    sink_file.write_text("{}", encoding="utf-8")
    config = EvalConfig(allowed_roots=(tmp_path,), sink_dir=tmp_path)

    with patch.object(Path, "read_text", side_effect=OSError("Disk read failed")):
        result = score_run("run-os-err", config=config)
        assert result["verdict"] == BLOCKED
        assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE
        assert "Disk read failed" in result["blocked_detail"]


def test_score_run_with_ignored_verdicts_detail(tmp_path: Path):
    sink_file = tmp_path / "run-ignored.json"
    # Scorer missing name key produces ignored entry
    sink_file.write_text(json.dumps({"results": [{"passed": True}]}), encoding="utf-8")
    config = EvalConfig(allowed_roots=(tmp_path,), sink_dir=tmp_path)

    result = score_run("run-ignored", config=config)
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert "verdict field(s) were refused as unnameable" in result["blocked_detail"]
