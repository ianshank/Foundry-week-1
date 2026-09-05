# Adapter candidates — parked, unmerged

Runbook step 4.5. **View Snippet** (single file), not **View Code** (full
project scaffold). For GitHub-hosted models take the provider SDK over Agent
Framework: it is the smaller diff when it becomes one more model adapter behind
Mango's existing interface.

Nothing here is imported by anything. It is a diff preview for a week-2
decision that has not been made, and it stays that way until
`evidence/05-verdict.md` says otherwise.

Strip any token before committing — `make scan` does not reach this directory
by default, so run `python3 scripts/scan_evidence.py snippets` on it explicitly.
