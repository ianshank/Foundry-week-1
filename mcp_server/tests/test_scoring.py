"""`null` is a verdict. These tests are what stops it becoming a boolean."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry_spike_mcp.scoring import score_run
from foundry_spike_mcp.verdicts import (
    BLOCKED,
    BLOCKED_ARTIFACT_MISSING,
    BLOCKED_ARTIFACT_SCHEMA,
    BLOCKED_ARTIFACT_UNREADABLE,
    BLOCKED_GUARD_REJECTED,
    BLOCKED_NO_SCORED_RESULTS,
    FINDINGS,
    PASS,
)


@pytest.fixture
def sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    directory = tmp_path / "sink"
    directory.mkdir()
    monkeypatch.setenv("EVAL_SINK_DIR", str(directory))
    monkeypatch.setenv("EVAL_ALLOWED_ROOTS", str(directory))

    def _write(run_id: str, document) -> Path:
        path = directory / f"{run_id}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    _write.dir = directory  # type: ignore[attr-defined]
    return _write


def test_mixed_verdicts_preserve_null_and_exclude_it_from_pass_rate(sink):
    sink(
        "run-1",
        {
            "run_id": "run-1",
            "results": [
                {"scorer": "exit_code_fidelity", "passed": True},
                {"scorer": "refusal_held", "passed": False},
                {"scorer": "trajectory_shape", "passed": None},
            ],
        },
    )
    result = score_run("run-1")
    verdicts = {record["scorer"]: record["passed"] for record in result["scorers"]}
    assert verdicts["exit_code_fidelity"] is True
    assert verdicts["refusal_held"] is False
    assert verdicts["trajectory_shape"] is None
    assert result["counts"] == {"true": 1, "false": 1, "null": 1, "unreadable": 0}
    assert result["pass_rate"] == 0.5  # 1 of 2 scored, not 1 of 3
    assert result["verdict"] == FINDINGS


def test_all_null_is_blocked_not_pass_and_pass_rate_is_null(sink):
    """The aggregate form of the null trap. `0.0` and `1.0` are both lies."""
    sink("run-2", {"results": [{"scorer": "a", "passed": None}, {"scorer": "b", "passed": None}]})
    result = score_run("run-2")
    assert result["pass_rate"] is None
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_NO_SCORED_RESULTS
    assert all(record["passed"] is None for record in result["scorers"])


def test_all_true_is_pass(sink):
    sink("run-3", {"results": [{"scorer": "a", "passed": True}, {"scorer": "b", "passed": True}]})
    result = score_run("run-3")
    assert result["verdict"] == PASS
    assert result["pass_rate"] == 1.0


def test_one_false_is_findings_even_among_nulls(sink):
    sink("run-4", {"results": [{"scorer": "a", "passed": None}, {"scorer": "b", "passed": False}]})
    result = score_run("run-4")
    assert result["verdict"] == FINDINGS
    assert result["pass_rate"] == 0.0


def test_pinned_schema_is_extracted(sink):
    """The sink layout is pinned in session 3: must be 'results' array."""
    sink(
        "run-5",
        {"results": [{"scorer": "s1", "passed": True}]}
    )
    result = score_run("run-5")
    assert [record["scorer"] for record in result["scorers"]] == ["s1"]
    assert result["scorers"][0]["source_path"].startswith("$.results[0]")


def test_unrecognised_schema_is_blocked_not_an_empty_pass(sink):
    sink("run-6", {"summary": "everything is fine", "duration": 12})
    result = score_run("run-6")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert result["pass_rate"] is None


def test_missing_artifact_is_blocked(sink):
    result = score_run("no-such-run")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_MISSING


def test_non_json_artifact_is_blocked_not_a_crash(sink, monkeypatch):
    path = sink.dir / "run-7.json"  # type: ignore[attr-defined]
    path.write_text("not json", encoding="utf-8")
    result = score_run("run-7")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE


def test_run_id_cannot_be_a_path(sink):
    result = score_run("../../etc/passwd")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


def test_artifact_outside_allow_list_is_blocked(sink, tmp_path):
    stray = tmp_path / "stray.json"
    stray.write_text(json.dumps({"results": [{"scorer": "a", "passed": True}]}), encoding="utf-8")
    result = score_run("run-8", artifact_path=str(stray))
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


def test_unset_sink_is_blocked_not_a_keyerror(monkeypatch):
    monkeypatch.delenv("EVAL_SINK_DIR", raising=False)
    monkeypatch.delenv("EVAL_ALLOWED_ROOTS", raising=False)
    result = score_run("run-9")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED


def test_unreadable_verdict_value_is_not_guessed_into_a_boolean(sink):
    sink("run-10", {"results": [{"scorer": "weird", "passed": 0.73}]})
    result = score_run("run-10")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert result["ignored"][0]["why"] == "scorer record has a non-boolean, non-null verdict"


# --------------------------------------------------------------------------
# Regression: phantom scorers. A strict pinned schema prevents summary fields
# from fabricating passes.
# --------------------------------------------------------------------------

def test_missing_results_array_is_blocked(sink):
    sink("run-20", {"run_id": "run-20", "result": "pass", "scorers": [{"name": "s", "passed": True}]})
    result = score_run("run-20")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA

def test_unnamed_scorer_record_is_refused(sink):
    sink("run-21", {"results": [{"passed": True}]})
    result = score_run("run-21")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert len(result["ignored"]) == 1
    assert result["ignored"][0]["why"] == "scorer record missing 'scorer' name key"


def test_malformed_result_blocks_even_when_another_result_passes(sink):
    sink(
        "run-22",
        {"results": [{"scorer": "valid", "passed": True}, {"scorer": "invalid"}]},
    )
    result = score_run("run-22")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA


def test_null_never_appears_as_false_anywhere_in_the_payload(sink):
    sink("run-11", {"results": [{"scorer": "a", "passed": None}, {"scorer": "b", "passed": True}]})
    result = score_run("run-11")
    serialised = json.dumps(result)
    assert '"passed": null' in serialised
    assert result["counts"]["false"] == 0


# --------------------------------------------------------------------------
# Regression: finding #4. `json.loads` raises RecursionError -- not
# JSONDecodeError -- on deeply nested input, and it escaped score_run entirely,
# contradicting the "Never raises" contract in the module docstring.
# --------------------------------------------------------------------------


def test_deeply_nested_artifact_is_blocked_not_a_recursion_error(sink):
    path = sink.dir / "deep.json"  # type: ignore[attr-defined]
    path.write_text("[" * 20_000 + "]" * 20_000, encoding="utf-8")
    result = score_run("deep")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE


def test_oversize_artifact_is_blocked_using_the_configured_limit(sink, monkeypatch):
    monkeypatch.setenv("EVAL_MAX_ARTIFACT_BYTES", "10")
    sink("big", {"results": [{"scorer": "a", "passed": True}]})
    result = score_run("big")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE


# --------------------------------------------------------------------------
# Regression: finding #5. Every return carries the same keys, so a caller
# never has to probe for existence to find out how far the run got.
# --------------------------------------------------------------------------


def test_result_shape_is_identical_across_every_path(sink, tmp_path, monkeypatch):
    shapes = []
    monkeypatch.delenv("EVAL_SINK_DIR", raising=False)
    monkeypatch.delenv("EVAL_ALLOWED_ROOTS", raising=False)
    shapes.append(set(score_run("x").keys()))          # unconfigured
    sink("ok", {"results": [{"scorer": "a", "passed": True}]})
    shapes.append(set(score_run("ok").keys()))         # success
    shapes.append(set(score_run("missing").keys()))    # absent artifact
    shapes.append(set(score_run("").keys()))           # rejected argument
    assert len(set(map(frozenset, shapes))) == 1, shapes
