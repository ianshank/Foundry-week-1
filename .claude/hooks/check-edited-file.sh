#!/usr/bin/env bash
# PostToolUse hook: lint and type-check the one file that just changed.
#
# Scoped to a single file on purpose. A hook that runs the whole suite on every
# edit takes long enough that it gets turned off, and a hook that is off
# protects nothing. The full gauntlet is `spike-validate` and CI.
#
# Contract with the harness: read the tool-call JSON on stdin, exit 0 to stay
# quiet, exit 2 to feed stderr back to the model as a correction. Any other
# nonzero is treated as a hook malfunction, so a missing linter must exit 0 --
# an un-runnable check is not a finding about the user's code.
set -uo pipefail

payload="$(cat)"

# Extract the edited path without requiring jq, which is not guaranteed here.
file_path="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)
tool_input = data.get("tool_input") or {}
print(tool_input.get("file_path") or "")
' 2>/dev/null)"

[ -n "$file_path" ] || exit 0
[ -f "$file_path" ] || exit 0

# Re-express the path as repo-relative before handing it to any linter.
#
# This is the fix for a bug that made this hook untrustworthy for a whole
# session. The harness supplies `file_path` as a Windows absolute path with a
# **lowercase** drive letter (`e:\Coding_Projects\...`). Ruff builds the
# matcher for `[tool.ruff.lint.per-file-ignores]` by joining the *config
# file's* directory -- discovered as `E:\Coding_Projects\...`, uppercase --
# with each pattern, then compares it against the path it was handed. The two
# differ only in the case of the drive letter, the glob does not match, and
# every `S101` this project exempts for `**/tests/**` is reported as a violation.
#
# Reproduced exactly:
#   ruff check "e:\...\tests\test_claude_assets.py"  -> 34 errors
#   ruff check "E:\...\tests\test_claude_assets.py"  -> All checks passed!
#
# The cost was not the noise. It was that the hook reported ~34 false findings
# per test-file edit, so a genuine `F821` it caught later was nearly dismissed
# as more of the same. A relative path sidesteps drive-letter case entirely
# and is what a developer types anyway.
repo_root="$(git -C "$(dirname "$file_path")" rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -n "$repo_root" ]; then
  cd "$repo_root" || exit 0
  case "$(python3 -c "
import os, sys
try:
    print(os.path.relpath(sys.argv[1], sys.argv[2]).replace(os.sep, '/'))
except ValueError:
    print('')
" "$file_path" "$repo_root" 2>/dev/null)" in
    ""|../*) ;;                       # outside the repo: leave the path alone
    *) file_path="$(python3 -c "
import os, sys
print(os.path.relpath(sys.argv[1], sys.argv[2]).replace(os.sep, '/'))
" "$file_path" "$repo_root")" ;;
  esac
fi

# The harness assets: skills, agents, settings, hooks, and the config files
# that name paths inside the repo. These break *silently* -- a skill pointing
# at a moved file, a hook command whose script lost its +x bit, a gitleaks
# allowlist still written against the old `mcp/` directory name. None of that
# surfaces on the next edit; it surfaces weeks later as "the model ignored the
# skill" or a red CI job nobody associates with a rename. `test_claude_assets.py`
# checks all of it deterministically in well under a second, which is cheap
# enough to run on the edit that caused it.
case "$file_path" in
  *.claude/skills/*|*.claude/agents/*|*.claude/settings.json|*.claude/hooks/*|*/Makefile|Makefile|*.gitleaks.toml)
    if command -v python3 >/dev/null 2>&1; then
      if ! output="$(python3 -m pytest tests/test_claude_assets.py -q --no-header 2>&1)"; then
        printf 'Editing %s broke the harness assets:\n%s\n' "$file_path" "$output" >&2
        printf 'These are deterministic checks -- a failure is a real broken reference, not flakiness.\n' >&2
        exit 2
      fi
    fi
    ;;
esac

case "$file_path" in
  *.py) ;;
  *.sh|*/.githooks/*|.githooks/*)
    if ! output="$(bash -n "$file_path" 2>&1)"; then
      printf 'Shell syntax error in %s:\n%s\n' "$file_path" "$output" >&2
      exit 2
    fi
    exit 0
    ;;
  *) exit 0 ;;
esac

findings=""

if command -v ruff >/dev/null 2>&1; then
  # --force-exclude: ruff ignores `extend-exclude` when handed an explicit
  # file path, so without it an edit under `traces/`, `evidence/` or
  # `snippets/` is linted despite the project having excluded it by name.
  #
  # --no-cache: this tree has had two ruff versions writing into
  # `.ruff_cache/` in the same session (0.16.5 and 0.16.6 directories both
  # exist), because `mcp_server/pyproject.toml` floated `ruff>=0.6` and an
  # editor-bundled binary also lints here. A shared cache across versions is
  # one more variable in a check whose findings must be trustworthy.
  #
  # The provenance line is the important part. This hook reported per-file
  # ignores as violations often enough that a genuine F821 was nearly
  # dismissed as noise -- a hook that cries wolf is worse than no hook. When
  # its finding disagrees with `python -m ruff check .`, the next reader needs
  # to know which binary, which version and which directory produced it,
  # without re-deriving it by hand.
  if ! output="$(ruff check --force-exclude --no-cache "$file_path" 2>&1)"; then
    findings="${findings}${output}"$'\n'
    findings="${findings}(reported by $(command -v ruff), $(ruff --version 2>/dev/null), cwd $PWD)"$'\n'
    findings="${findings}If this disagrees with 'python -m ruff check .', trust that one: it is what CI runs."$'\n'
  fi
fi

# mypy is per-file here rather than whole-project: the project pass belongs to
# the full gauntlet, and a cross-module error surfaced on an unrelated edit is
# noise the model cannot act on.
if command -v mypy >/dev/null 2>&1; then
  case "$file_path" in
    *mcp_server/src/*|*scripts/*)
      if ! output="$(mypy "$file_path" 2>&1)"; then
        findings="${findings}${output}"$'\n'
      fi
      ;;
  esac
fi

if [ -n "$findings" ]; then
  printf 'Checks failed on %s. Fix these before continuing:\n%s\n' "$file_path" "$findings" >&2
  printf 'If a finding is a deliberate exception, add the suppression with a reason on the same line.\n' >&2
  exit 2
fi

exit 0
