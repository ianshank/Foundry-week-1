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

case "$file_path" in
  *.py) ;;
  *.sh)
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
  if ! output="$(ruff check "$file_path" 2>&1)"; then
    findings="${findings}${output}"$'\n'
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
