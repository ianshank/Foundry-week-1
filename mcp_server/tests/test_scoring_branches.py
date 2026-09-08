"""Branch coverage tests for edge cases in foundry_spike_mcp.scoring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from foundry_spike_mcp.config import EvalConfig
from foundry_spike_mcp.scoring import (
    BLOCKED_CONFIG_ERROR,
    _aggregate,
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


def test_normalise_passed_rejects_non_json_verdict_values():
    for val in ("true", "True", "PASS", "passed", "false", "FAIL", "null", "None", ""):
        assert _normalise_passed(val) == f"unreadable:{val!r}"

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
    assert result["blocked_detail"] == "artifact has 1 invalid scorer record(s)"


# ---------------------------------------------------------------------------
# `_aggregate`'s `unreadable` counter.
# ---------------------------------------------------------------------------


def test_the_unreadable_counter_is_defensive_and_not_reachable_from_score_run():
    """This branch is unreachable through the public API, on purpose.

    `_collect_scorers` routes every record whose `passed` is not `True`, `False`
    or `None` into `ignored` and blocks, so by the time `_aggregate` runs, the
    value is one of the three by construction. Coverage therefore reports the
    `else` arm as missing, and the tempting response -- delete the branch and
    the `unreadable` key with it -- is wrong twice over.

    It is wrong as a contract change: `counts` is on the wire in every
    envelope, seeded from `_EMPTY_COUNTS`, and
    `test_scoring.py::test_pass_rate_excludes_nulls` pins the key set by exact
    dict equality. Removing a key is a return-shape change, which is a defect in
    this repository's terms, not a simplification.

    It is wrong as engineering: the branch is what makes `_aggregate` total. If
    `_collect_scorers` is ever relaxed to pass a value through, the counter
    catches it instead of `pass_rate` silently absorbing it into a denominator.

    So the branch is exercised directly, and this docstring is here so the next
    coverage-driven tidy-up has something to read before deleting it.
    """
    records = [
        {"scorer": "a", "passed": True},
        {"scorer": "b", "passed": False},
        {"scorer": "c", "passed": None},
        {"scorer": "d", "passed": "unreadable: 0.73"},
    ]

    pass_rate, counts = _aggregate(records)

    assert counts == {"true": 1, "false": 1, "null": 1, "unreadable": 1}
    assert pass_rate == 0.5, "the unreadable record must not enter the denominator"


def test_a_run_of_only_unreadable_records_has_no_pass_rate():
    """No opinion is not the same as a zero rate.

    A denominator of zero must produce `None`, never `0.0` -- the distinction
    the whole three-valued contract rests on. Guarded here for the same reason
    the branch above is: if `_collect_scorers` is ever relaxed, this is what
    stops "nothing readable" being reported as "nothing passed".
    """
    pass_rate, counts = _aggregate([{"scorer": "a", "passed": "unreadable: x"}])

    assert pass_rate is None
    assert counts["unreadable"] == 1
