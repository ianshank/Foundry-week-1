# 0002 — Pin the eval-harness sink schema in `score_run`

**Status:** ACCEPTED, with a stated reversal condition
**Opened:** 2026-09-08
**Owner:** ianshank
**Decision type:** code contract. Enforced by `mcp_server/tests/test_scoring.py`.

> **Written after the fact, and that is itself worth recording.** `NEXT_STEPS.md`
> required this pin to land *with* a decision record: "Hold this until Track C0
> produces an artifact, then land it with a `decisions/0002` entry recording the
> pinned shape." The pin landed on `main` without one, and `README.md` went on
> advertising the opposite behaviour until 2026-09-08. This document closes that
> gap. It records an already-taken decision as taken — recording it as open
> would be a second kind of inaccuracy.

---

## Question

`score_run` reads an eval-harness sink artifact and reports `true` / `false` /
`null` per scorer plus a `pass_rate` that excludes nulls. What shape is it
allowed to accept?

## Decision

The artifact **must** be a JSON object with a `results` key at the root, whose
value is a list. Each element must be an object carrying:

* `scorer` — the scorer's name, a string;
* `passed` — the three-valued verdict: `true`, `false`, or `null`.

Anything else returns `BLOCKED` with `blocked_reason:
unrecognized_artifact_schema`, and each rejected record is reported in
`ignored[]` with its JSONPath and the reason it was refused.

Nothing is inferred. A `results` list nested anywhere other than the root is
refused. A scorer-shaped object sitting *beside* a valid `results` list — a
summary field, say — is not counted. A `passed` value that is neither boolean
nor null is refused rather than coerced.

## Why pin rather than walk tolerantly

The predecessor walked any nested structure looking for name-shaped and
verdict-shaped keys. `result` was among the keys it accepted, and `result` is a
common *summary* field — so an artifact like

```json
{"run_id": "r", "result": "pass", "scorers": [{"name": "t", "passed": null}]}
```

produced a phantom scorer with `passed=True` at the document root, turning a run
that should have been `BLOCKED / no_scored_results` into `PASS` with
`pass_rate: 1.0`.

That is the fabrication this repository exists to detect, arriving through a
tolerant reader rather than through a coercion. A tolerant walk cannot
distinguish a scorer from a field shaped like one, and the only failure it can
produce is the fabricated pass — the expensive direction.

## What this decision does **not** rest on

**No real eval-harness sink artifact has ever been read.** The pinned shape is
taken from documented output, not from an instance. `evidence/00-demo-eval.txt`
records why one could not be produced:

```
ValueError: judge_calibration.calibration_artifact_id is required to gate on
['helpfulness']: a judge's participation in gating must be traceable to the
calibration run that authorised it
```

`NEXT_STEPS.md` Track B2 raised exactly this objection and lost: "Pinning a
guessed schema converts 'we read something odd, here is what we found' into
'refused, no data'." That objection is not answered by this record. It is
recorded as a live risk, because a pin taken against documentation is a
prediction about a file nobody has opened.

Also removed with the pin: seven contract tests, including the one named for the
phantom-scorer defect. That test has been restored under its original name, with
the assertions it lost, in `mcp_server/tests/test_scoring.py`.

## Reversal condition

When a real sink artifact exists, diff it against the shape above.

* **If it matches** — record that here and the risk closes.
* **If it does not match** — widen the pin **explicitly**, naming the field that
  moved. Do not restore the tolerant walk; the phantom-scorer defect is a
  property of tolerance, not of any particular field.
* **If the artifact cannot be produced without importing harness internals** —
  that is runbook **stop condition 3**, not a schema problem. Record it as one.
  Do not invent a `calibration_artifact_id` to get past the error.

`mcp_server/tests/test_scoring.py::test_a_results_list_nested_elsewhere_is_still_refused`
is what fails first if someone loosens the reader to make a real artifact parse.
That is the correct place for it to fail, and it is what makes this reversal
condition enforceable rather than aspirational.

## Consequences

* `README.md` advertised the tolerant behaviour until 2026-09-08, when it was
  reconciled with the code.
* `evidence/05-verdict.md` §2 records the `true`/`false`/`null` rows as
  unit-proven rather than end-to-end, for this reason.
* The scorer half of `decisions/0001` criterion 2 stays unestablished until a
  real artifact is read.

## Evidence

| Artifact | What it shows |
|---|---|
| `mcp_server/src/foundry_spike_mcp/scoring.py` | the pin, in `_collect_scorers` |
| `mcp_server/tests/test_scoring.py` | the pinned shape and its refusals, including the restored phantom-scorer guard |
| `evidence/00-demo-eval.txt` | why no real artifact exists to check it against |
