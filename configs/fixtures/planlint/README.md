# planlint self-check fixtures

Targets for `make selfcheck`, which proves all three verdicts land against the
real binary. **Tracked, not gitignored** -- and that is the whole point.

The self-check's FINDINGS case previously pointed at `bad_target/`, which
`.gitignore` excluded. No reviewer could open the thing the evidence depended
on, the directory was an empty tree, planlint correctly found zero specs and
exited 0, and `evidence/03-mcp-selfcheck.json` honestly recorded
`all_expected: false` for two merges. It was then hand-edited to say the case
had landed. A fixture a reviewer cannot open is not evidence.

| Fixture | Trips | Real planlint exit | Verdict |
|---|---|---|---|
| `findings/` | `G001` (requirement with nothing verifying it), `U002` (requirement with no Scenario) -- both ERROR | 1 | FINDINGS |
| `blocked/` | no `openspec/` tree at all, which is a precondition error | 2 | BLOCKED |

There is no `pass/` fixture. The PASS case points at a real OpenSpec repository
via `SELFCHECK_PASS_TARGET`, because a hand-built tree that happens to satisfy
every rule proves less than the production target already recorded clean in
`evidence/00-validate.txt`.

Verify with the real binary:

```
planlint --target configs/fixtures/planlint/findings validate --fail-on ERROR   # exit 1
planlint --target configs/fixtures/planlint/blocked   validate --fail-on ERROR   # exit 2
```
