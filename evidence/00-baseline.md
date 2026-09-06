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

- [ ] Toolkit version file written (`evidence/00-toolkit-version.txt`)
- [ ] Dialect card captured (`evidence/00-dialect-card.json`)
- [ ] planlint validate exit recorded (0 or 1)
- [ ] Demo eval exit recorded (0)
