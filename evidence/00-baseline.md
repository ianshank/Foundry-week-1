# Step 0 baseline

- Captured: 2026-09-05T19:57:33Z
- Host: MINGW64_NT-10.0-26200 3.6.5-22c95533.x86_64 x86_64
- SPIKE_HOME: `/e/Coding_Projects/foundry_week1`
- PLANLINT_TARGET: `e:/Working+Directory/Agents`
- AGENTS_REPO: `e:/Working+Directory/Agents`

## Toolkit extension version

```
ms-windows-ai-studio.windows-ai-studio@1.6.11
```

## planlint

- `--version`: `planlint 0.2.0`
- `validate --help` mentions `--json`
- `validate --help` mentions `--format`
- **set `PLANLINT_JSON_FLAG`** to the exact spelling this build wants (first candidate: `--json`)
- `detect` exit: 0 -> `evidence/00-dialect-card.json`
- `validate --fail-on ERROR` exit: **0** (PASS - no findings at or above ERROR)

## eval-harness

- `list-plugins` exit: 0 -> `evidence/00-plugins.txt`
- `run --config demo/configs/eval.pass.yaml --offline` exit: **1** (baseline expects 0)

## Done-when

- [x] Toolkit version file written (`evidence/00-toolkit-version.txt`)
- [x] Dialect card captured (`evidence/00-dialect-card.json`)
- [x] planlint validate exit recorded (0 or 1)
- [ ] Demo eval exit recorded (0)

Three of four. The fourth is **blocked externally, not skipped**, and the
distinction matters because everything downstream of `score_run` depends on it.

`make baseline` recorded the demo eval as exit **1**, not 0, and
`evidence/00-demo-eval.txt` carries the traceback verbatim:

```
ValueError: judge_calibration.calibration_artifact_id is required to gate on
['helpfulness']: a judge's participation in gating must be traceable to the
calibration run that authorised it
```

The eval harness is refusing to gate on a judge whose calibration it cannot
trace — which is the same class of refusal this spike's wrapper exists to make,
arriving from the other side. Whether that id is a config field with a real
artifact behind it, or something only a calibration run inside the harness can
produce, is not known. If it is the latter, that is runbook stop condition 3.
See `evidence/05-verdict.md` §4 and `decisions/0002-pinned-sink-schema.md`.
