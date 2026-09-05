# Security

This repository is a time-boxed engineering spike, not a product. It ships no
service and has no users. What it *does* have is a security posture worth
stating, because the tools here execute a subprocess and read paths supplied by
a language model.

## Reporting

Open a [private security advisory](https://github.com/ianshank/Foundry-week-1/security/advisories/new).
Please do not open a public issue for anything exploitable.

There is no SLA. This is a spike; expect a response when someone is looking at
it, not on a clock.

## Threat model

The interesting adversary is not a network attacker. It is **an argument
supplied by a language model**, arriving through a tool call, and the guidance
that MCP tool descriptions and results are untrusted input applies in reverse
too: arguments coming *from* a model are untrusted input to this code.

| Surface | Control | Where |
|---|---|---|
| Model-supplied path | Absolute-path allow list, resolved before containment so `..` and symlinks out of a root are both caught. Fails closed: no allow list means nothing is readable. | `guards.check_target` |
| Model-supplied argv | There isn't any. Tools take validated scalars and build the command line internally; `assert_safe_argv` is a self-check against a future edit. | `planlint.run_verb` |
| Command execution | Verb allow list (`detect`, `validate`, `graph`, `rules`, `waivers`, `delta`), mutating-flag deny list, no shell. `init`, `new`, `witness` and `make` are refused. | `guards.ALLOWED_VERBS` |
| Runaway subprocess | Mandatory timeout; a timeout maps to `BLOCKED`, never to a verdict. A static test asserts no `subprocess` call lacks one. | `planlint.run_verb`, `test_seam_is_closed` |
| Credentials in output | stderr redacted then truncated (that order — truncating first can bisect a token and leave half a credential behind). | `guards.clean` |
| Credentials in commits | Three layers: `traces/raw/` gitignored, `promote_trace.py` refuses to publish a capture that scans dirty, pre-commit hook plus gitleaks over full history in CI. | `scripts/`, `.gitleaks.toml` |
| Outbound requests | Endpoint schemes restricted to `http`/`https`. Endpoints come from the environment, so `file:///etc/passwd` was otherwise reachable by a typo and `urlopen` would have read it into a saved transcript. | `verifier_probe._validate_endpoint` |

## Policy is hard-coded on purpose

`config.py` reads the environment. `guards.py` does not. The verb allow list,
the flag deny list and the credential patterns cannot be widened by setting a
variable, because an allow list that can be is not an allow list. Changing what
this code may execute costs a code change, a review and a test — deliberately.

If you are tempted to make a guard configurable to get something to pass, that
is [runbook](RUNBOOK.md) step 5's stop condition, and it belongs in
`evidence/05-verdict.md` rather than in a commit.

## Known limitations

Stated rather than left for someone to discover:

- **Time-of-check to time-of-use.** `check_target` resolves and validates a
  path, then `planlint` opens it. A sufficiently motivated local attacker could
  swap a symlink in between. Not mitigated: everything here runs as one
  developer on one machine against their own repositories, and closing it would
  need an fd-based API planlint does not offer.
- **GitHub Actions use floating major tags** (`@v4`, `@v5`, `@v2`) rather than
  commit SHAs. A compromised tag would run with `contents: read` and the
  default token. Accepted for a spike; SHA-pin before this pattern is copied
  into anything with write permissions or secrets.
- **Transitive dependencies are unpinned.** One direct dependency (`mcp`,
  bounded `>=1.2,<3`) with no lockfile, so CI resolves fresh each run. A
  transitive break appears as an unexplained red rather than a diff.
- **No LICENSE.** The repository is public with no licence file, which means
  all rights reserved by default and nobody may legally reuse it. That is a
  decision for the owner, not a defect this file can fix.
- **The repository is public** and accumulates output derived from private
  source repositories. The three capture layers above are mitigation; making
  the repository private is the actual fix.

## Reproducing the checks

```bash
make validate                       # ruff, mypy, tests, credential pass
gitleaks detect --config .gitleaks.toml   # full history
```
