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


def test_nested_and_list_shapes_are_both_found(sink):
    """The sink layout is pinned in session 3; until then, be shape-tolerant
    rather than shape-guessing."""
    sink(
        "run-5",
        {"cases": [{"name": "c1", "scorers": [{"name": "s1", "passed": True}]}, {"scorers": []}]},
    )
    result = score_run("run-5")
    assert [record["scorer"] for record in result["scorers"]] == ["s1"]
    assert result["scorers"][0]["source_path"].startswith("$.cases[0].scorers[0]")


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
    passed = result["scorers"][0]["passed"]
    assert passed is not True and passed is not False and passed is not None
    assert str(passed).startswith("unreadable:")
    assert result["counts"]["unreadable"] == 1
    assert result["pass_rate"] is None


# --------------------------------------------------------------------------
# Regression: phantom scorers. `result` was in _PASSED_KEYS, so a top-level
# summary field became a scorer with passed=True -- turning a null-only run
# into PASS with pass_rate 1.0. The fabrication this module exists to prevent,
# arriving through the shape-tolerant walk instead of through a coercion.
# --------------------------------------------------------------------------


def test_top_level_result_summary_does_not_fabricate_a_pass(sink):
    sink(
        "run-20",
        {
            "run_id": "run-20",
            "result": "pass",
            "scorers": [{"name": "trajectory_shape", "passed": None}],
        },
    )
    result = score_run("run-20")
    assert [record["scorer"] for record in result["scorers"]] == ["trajectory_shape"]
    assert result["pass_rate"] is None
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_NO_SCORED_RESULTS


def test_unnamed_root_verdict_field_is_refused_and_recorded(sink):
    """Refused, not silently dropped: session 3 pins the real schema, and a
    field this wrapper declined to count is exactly what it needs to see."""
    sink("run-21", {"passed": True, "cases": [{"name": "c", "passed": None}]})
    result = score_run("run-21")
    assert [record["scorer"] for record in result["scorers"]] == ["c"]
    assert len(result["ignored"]) == 1
    assert result["ignored"][0]["source_path"] == "$"
    assert result["verdict"] == BLOCKED


def test_a_root_object_that_names_itself_is_still_a_scorer(sink):
    """The root refusal keys on namelessness, not on being the root -- an
    artifact that is one scorer record must not be thrown away."""
    sink("run-22", {"scorer": "exit_code_fidelity", "passed": True})
    result = score_run("run-22")
    assert [record["scorer"] for record in result["scorers"]] == ["exit_code_fidelity"]
    assert result["verdict"] == PASS


def test_scorers_are_named_from_their_key_when_the_record_has_no_name(sink):
    sink("run-23", {"scorers": {"exit_fidelity": {"passed": True}, "refusal": {"passed": False}}})
    result = score_run("run-23")
    named = {record["scorer"]: record["named_by"] for record in result["scorers"]}
    assert named == {"exit_fidelity": "path", "refusal": "path"}
    assert result["verdict"] == FINDINGS


def test_a_bare_array_of_unnamed_records_still_reports(sink):
    """Positional naming: an unnameable *list element* does not exist, so the
    refusal stays narrow to the one shape that caused the defect."""
    sink("run-24", [{"passed": True}, {"passed": False}])
    result = score_run("run-24")
    assert [record["scorer"] for record in result["scorers"]] == ["[0]", "[1]"]
    assert result["pass_rate"] == 0.5
    assert result["ignored"] == []


def test_explicit_name_wins_over_the_path(sink):
    sink("run-25", {"scorers": {"slot_a": {"name": "exit_code_fidelity", "passed": True}}})
    record = score_run("run-25")["scorers"][0]
    assert record["scorer"] == "exit_code_fidelity"
    assert record["named_by"] == "field"


def test_null_never_appears_as_false_anywhere_in_the_payload(sink):
    sink("run-11", {"results": [{"scorer": "a", "passed": None}, {"scorer": "b", "passed": True}]})
    result = score_run("run-11")
    serialised = json.dumps(result)
    assert '"passed": null' in serialised
    assert result["counts"]["false"] == 0
