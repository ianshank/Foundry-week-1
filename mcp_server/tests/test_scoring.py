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
    """A verdict the wrapper cannot read must not become one it can.

    The last three assertions were lost when the pinned schema landed and this
    test was rewritten. They are the ones that matter: BLOCKED is a statement
    that no opinion could be formed, so a `pass_rate` alongside it is a
    contradiction, and a scorer list with anything in it means something was
    counted. Without them a regression returning BLOCKED *with* `pass_rate:
    1.0` passes -- which is the fabrication this module exists to prevent,
    wearing a refusal as a disguise.
    """
    sink("run-10", {"results": [{"scorer": "weird", "passed": 0.73}]})
    result = score_run("run-10")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert result["ignored"][0]["why"] == "scorer record has a non-boolean, non-null verdict"
    assert result["pass_rate"] is None, "BLOCKED came with a pass rate"
    assert result["scorers"] == [], "BLOCKED came with counted scorers"
    assert result["counts"] == {"true": 0, "false": 0, "null": 0, "unreadable": 0}


# --------------------------------------------------------------------------
# Regression: phantom scorers. A strict pinned schema prevents summary fields
# from fabricating passes.
# --------------------------------------------------------------------------

def test_top_level_result_summary_does_not_fabricate_a_pass(sink):
    """The phantom-scorer regression, restored to the name and shape it had.

    `result` was once in `_PASSED_KEYS`, so a top-level summary field became a
    scorer with `passed=True` and turned a null-only run into PASS with
    `pass_rate: 1.0`. The pinned schema removed the walk that made that
    possible, and in the rewrite this test lost its name and three of its four
    assertions -- keeping only `verdict` and `blocked_reason`.

    Two things were lost with them. The payload's `passed` was flipped `None`
    -> `True`, so the fixture stopped constructing the null-only run that is
    the whole scenario; it now only demonstrates a schema violation. And
    nothing asserted `pass_rate`, so a regression returning BLOCKED with a
    fabricated rate still passed.

    The defect is greppable in history under this name again, which is the
    other half of what a regression guard is for.

    **What this test actually constrains, which is not what its name suggests.**
    Re-adding `"result"` to `_PASSED_KEYS` leaves it green -- verified by
    mutation. `_collect_scorers` refuses at the root before `_PASSED_KEYS` is
    ever consulted, because this fixture carries `scorers:` and not `results:`.
    So the named regression is now defended by two *other* mechanisms: the
    root-`results` pin (see `test_a_results_list_nested_elsewhere_is_still_refused`,
    which does go red when tolerance is restored) and `_normalise_passed`'s
    refusal to read the string `"pass"` as a boolean (see below).

    That is worth saying rather than quietly renaming the test. The pin made
    the original defect unreachable, which is the outcome you want -- but a
    guard whose stated subject is defended by something else is one refactor
    away from being the only thing left, and then it would not fire.
    """
    sink(
        "run-20",
        {
            "run_id": "run-20",
            "result": "pass",
            "scorers": [{"name": "trajectory_shape", "passed": None}],
        },
    )
    result = score_run("run-20")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert result["pass_rate"] is None, "the top-level summary was counted as a pass"
    assert result["scorers"] == []


def test_a_summary_key_inside_a_scorer_record_is_not_read_as_a_verdict(sink):
    """The `_PASSED_KEYS` half, reachable through the pinned schema.

    The test above is named for the phantom-scorer defect but no longer detects
    it, because the root-`results` pin refuses its fixture first. This one puts
    a summary-shaped key *inside* a well-formed scorer record, which is the only
    place `_PASSED_KEYS` is still consulted -- so it goes red if `"result"` is
    re-added to that tuple and starts being read as a verdict.

    The value has to be a **boolean**, and finding that out took a mutation.
    With `result: "pass"` the mutation is invisible, because `_normalise_passed`
    refuses the string regardless of which key it arrived under -- so that
    fixture would have been a third test that does not detect the defect it
    names. With `result: true` the mutation is observable:

        baseline: BLOCKED  pass_rate=None
        mutated : PASS     pass_rate=1.0

    which is the fabricated pass, exactly as the original defect produced it.
    """
    sink("run-26", {"results": [{"scorer": "grounding", "result": True}]})
    result = score_run("run-26")

    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert result["pass_rate"] is None, "a summary key was read as a passing verdict"
    assert result["scorers"] == []


def test_a_summary_beside_a_valid_results_list_is_not_counted(sink):
    """The failure mode the pin newly created, and which nothing tested.

    The pin refuses an artifact with no root `results` list -- so every test
    around it exercises *refusal*. That leaves the accepting path unexamined:
    an artifact that has a perfectly good `results` list and also carries a
    scorer-shaped summary field beside it. The old tolerant walk would have
    found both and reported `pass_rate: 0.5` over one real result and one
    phantom.

    This is the case a real eval-harness artifact is most likely to have, and
    the only one where the answer is a number rather than a refusal.
    """
    sink(
        "run-23",
        {
            "summary": {"scorer": "overall", "passed": True},
            "results": [{"scorer": "grounding", "passed": False}],
        },
    )
    result = score_run("run-23")

    assert result["verdict"] == FINDINGS
    assert [record["scorer"] for record in result["scorers"]] == ["grounding"]
    assert result["pass_rate"] == 0.0, "the summary field was counted as a passing scorer"
    assert result["counts"] == {"true": 0, "false": 1, "null": 0, "unreadable": 0}


def test_a_results_list_nested_elsewhere_is_still_refused(sink):
    """The pin itself, pinned.

    `{"run": {"results": [...]}}` is exactly what the old shape-tolerant walk
    would have found and scored. Refusing it is the narrowing that
    `decisions/0002` records, and this is the test that fails first if someone
    restores tolerance to make a real artifact parse -- which is the correct
    place for that to fail, and what makes the reversal condition enforceable
    rather than aspirational.
    """
    sink("run-25", {"run": {"results": [{"scorer": "a", "passed": True}]}})
    result = score_run("run-25")

    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_SCHEMA
    assert result["pass_rate"] is None

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


# --------------------------------------------------------------------------
# The same two gaps as `planlint`, one module over: a path the OS cannot
# represent, and text that reached the result already structured and so
# skipped the redaction that only ran on raw strings.
# --------------------------------------------------------------------------

TOKEN = "ghp_" + "C" * 36


def test_a_nul_byte_in_the_artifact_path_is_blocked_never_raised(sink):
    sink("run", {"results": [{"scorer": "s", "passed": True}]})
    result = score_run("run", artifact_path=f"{sink.dir}/run\x00.json")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_GUARD_REJECTED
    assert "invalid_path" in result["blocked_detail"]


def test_a_nul_byte_in_the_run_id_is_blocked_never_raised(sink):
    result = score_run("run\x00id")
    assert result["verdict"] == BLOCKED
    assert "\x00" not in json.dumps(result)


def test_a_credential_in_a_scorer_detail_is_redacted(sink):
    """The artifact is a file this wrapper did not write, and its text is
    copied into a result the model reads and a trace an operator commits."""
    sink(
        "run",
        {"results": [{"scorer": "exit_fidelity", "passed": False, "reason": f"used {TOKEN}"}]},
    )
    result = score_run("run")
    assert result["verdict"] == FINDINGS
    assert TOKEN not in json.dumps(result)
    assert "[REDACTED:github-token]" in result["scorers"][0]["detail"]


def test_a_credential_in_a_scorer_name_is_redacted(sink):
    sink("run", {"results": [{"scorer": TOKEN, "passed": True}]})
    result = score_run("run")
    assert TOKEN not in json.dumps(result)


def test_a_non_string_detail_is_left_alone(sink):
    """Redaction applies to text. A structured detail is passed through rather
    than stringified, because guessing at its shape is how evidence gets lost."""
    sink("run", {"results": [{"scorer": "s", "passed": True, "reason": {"code": 7}}]})
    assert score_run("run")["scorers"][0]["detail"] == {"code": 7}


# --------------------------------------------------------------------------
# `_normalise_passed` string forms, and the read paths that raise.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written", ["true", "pass", "passed", "false", "fail", "failed", "null", "skipped", "  TRUE  "]
)
def test_a_string_verdict_is_refused_rather_than_interpreted(sink, written):
    """The pinned schema tightened this, and the tightening is right.

    An earlier revision read `"true"` as `True`. That is an interpretation of
    something the harness did not say in the type JSON has for saying it, and
    this module's whole subject is not guessing. Only a real boolean or null
    counts now; anything else is recorded in `ignored` with a reason and
    excluded from the tally.

    This test previously asserted the lenient reading. The contract changed by
    a merged decision, so the test follows it -- and what it defends is
    unchanged: a verdict is never invented from a value that is not one.
    """
    sink("run", {"results": [{"scorer": "s", "passed": written}]})
    result = score_run("run")
    assert result["scorers"] == []
    assert len(result["ignored"]) == 1
    assert "non-boolean" in result["ignored"][0]["why"]
    assert result["verdict"] == BLOCKED
    assert result["pass_rate"] is None


@pytest.mark.parametrize("written", [True, False, None])
def test_a_real_json_verdict_is_read_exactly(sink, written):
    """The other half: the three values the contract does recognise survive
    unchanged, and `null` stays `null` rather than collapsing either way."""
    sink("run", {"results": [{"scorer": "s", "passed": written}]})
    assert score_run("run")["scorers"][0]["passed"] is written


def test_a_verdict_that_is_none_of_the_three_is_refused_not_coerced(sink):
    """0.73 is not a boolean, and guessing which one it means is the defect
    this module exists to avoid. Under the pinned schema the record is refused
    outright rather than reported with an `unreadable:` marker."""
    sink("run", {"results": [{"scorer": "s", "passed": 0.73}]})
    result = score_run("run")
    assert result["scorers"] == []
    assert result["verdict"] == BLOCKED
    assert result["pass_rate"] is None


def test_an_artifact_that_is_not_utf8_is_blocked_never_raised(sink):
    """UnicodeDecodeError subclasses ValueError as a *sibling* of
    JSONDecodeError, not a parent, so catching the latter missed it and the
    'never raises' contract did not hold."""
    path = sink("run", {"results": []})
    path.write_bytes(b'{"results": [{"scorer": "s", "passed": \xff\xfe true}]}')
    result = score_run("run")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE
    assert "UnicodeDecodeError" in result["blocked_detail"]


def test_an_unreadable_file_is_blocked_never_raised(sink, monkeypatch):
    """The filesystem is mocked here, not the module under test: this pins what
    `score_run` does when a read fails, which is the part that must not raise."""
    sink("run", {"results": [{"scorer": "s", "passed": True}]})

    def explode(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", explode)
    result = score_run("run")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_ARTIFACT_UNREADABLE
    assert "PermissionError" in result["blocked_detail"]


def test_a_document_too_deep_to_read_is_blocked_never_an_empty_pass(sink):
    """Deep nesting is BLOCKED whichever way this document is refused.

    Which refusal fires is a property of the interpreter build, not of this
    package. `json.loads` recurses in C, and how deep it gets before the stack
    guard trips differs between 3.10 and 3.12 -- on 3.10 the parse gives out
    and the answer is `artifact_unreadable`; on 3.12 the parse survives 2000
    levels, the pinned schema then finds no `results` key at the root, and the
    answer is `unrecognized_artifact_schema`.

    An earlier version asserted a *message*, and was red on CI only. This one
    then asserted `artifact_unreadable`, which held while `_collect_scorers`
    still recursed in Python -- the pin landed on main removed that walk, so
    the second limit this test used to describe no longer exists, and the
    assertion went red on 3.12 for the same reason as the first: it named a
    mechanism rather than the contract.

    What the contract promises is what is asserted below. A document this tool
    cannot read is refused, with a reason from the closed set, and it never
    becomes a PASS over an empty scorer list -- which is the failure mode this
    package exists to catch, and the only outcome here that would be wrong.
    """
    path = sink("run", {"results": []})
    depth = 2_000
    path.write_text(
        '{"n": ' * depth + '{"name": "s", "passed": true}' + "}" * depth, encoding="utf-8"
    )
    result = score_run("run")
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] in {BLOCKED_ARTIFACT_UNREADABLE, BLOCKED_ARTIFACT_SCHEMA}
    assert result["blocked_detail"]
    assert result["pass_rate"] is None
    assert result["scorers"] == []


def test_a_surrogate_in_an_artifact_does_not_cost_the_verdict(sink):
    """Regression, found by driving the real server over stdio.

    `score_run` returned a correct PASS and the SDK then failed to serialise
    it, so what reached the model was "Error executing tool score_run" with no
    verdict field -- the exact failure this package exists to prevent, one
    layer further out than the rule is usually applied.
    """
    path = sink("run", {"results": []})
    path.write_text('{"results":[{"scorer":"\\ud800","passed":true}]}', encoding="utf-8")
    result = score_run("run")
    assert result["verdict"] == PASS
    # The real assertion: the whole envelope survives an encode to the wire.
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_a_surrogate_in_an_artifact_key_does_not_cost_the_verdict(sink):
    """`source_path` is assembled from artifact keys and is the one
    externally-derived field that does not flow through `redact`."""
    path = sink("run", {"results": []})
    path.write_text('{"results":[{"scorer":"\\ud800","passed":true}]}', encoding="utf-8")
    result = score_run("run")
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_duplicate_verdict_keys_resolve_to_one_documented_answer(sink):
    """JSON permits duplicate keys and Python keeps the last. Pinned rather
    than left to be discovered: the surviving verdict is chosen by the parser,
    so the behaviour should at least be written down."""
    path = sink("run", {"results": []})
    path.write_text(
        '{"results":[{"scorer":"s","passed":true,"passed":null}]}', encoding="utf-8"
    )
    result = score_run("run")
    assert result["scorers"][0]["passed"] is None
    assert result["verdict"] == BLOCKED
    assert result["blocked_reason"] == BLOCKED_NO_SCORED_RESULTS


def test_an_artifact_with_zero_scorers_is_blocked_not_a_vacuous_pass(tmp_path, monkeypatch):
    """An eval that ran no scorers is not an eval that passed.

    `{"results": []}` is well-formed JSON with a recognised top-level shape and
    nothing inside it, which is the exact input a `pass_rate` computed over an
    empty set would report as 1.0 -- a non-result rendered as a pass, in the
    tool this repository exists to keep honest.

    The behaviour was already correct and covered by nothing: every existing
    test that writes `{"results": []}` immediately overwrites the file before
    calling `score_run`, so the literal never reached the code under test.
    """
    monkeypatch.setenv("EVAL_SINK_DIR", str(tmp_path))
    monkeypatch.setenv("EVAL_ALLOWED_ROOTS", str(tmp_path))
    (tmp_path / "empty-run.json").write_text(json.dumps({"results": []}), encoding="utf-8")

    result = score_run("empty-run")

    assert result["verdict"] == BLOCKED
    assert result["pass_rate"] is None, "a rate over zero scorers must not be a number"
    assert result["blocked_reason"] == "unrecognized_artifact_schema"
