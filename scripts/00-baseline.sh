#!/usr/bin/env bash
# Runbook step 0.4-0.5: version stamp, dialect card, and both baseline exit codes.
#
# Deliberately NOT `set -e`. The exit codes are the evidence: `planlint
# validate` returning 1 is a legitimate baseline, and a script that aborts on
# it would record nothing and call that success. Every command's status is
# captured and written down; the script's own exit code reports only whether
# the *capture* completed.
set -uo pipefail

SPIKE_HOME="${SPIKE_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
EVIDENCE="$SPIKE_HOME/evidence"
mkdir -p "$EVIDENCE" "$SPIKE_HOME/traces" "$SPIKE_HOME/configs"

SUMMARY="$EVIDENCE/00-baseline.md"
missing=0

log()  { printf '%s\n' "$*" | tee -a "$SUMMARY" >/dev/null; }
note() { printf '  %s\n' "$*" >&2; }

: >"$SUMMARY"
log "# Step 0 baseline"
log ""
log "- Captured: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "- Host: $(uname -srm)"
log "- SPIKE_HOME: \`$SPIKE_HOME\`"
log "- PLANLINT_TARGET: \`${PLANLINT_TARGET:-<unset>}\`"
log "- AGENTS_REPO: \`${AGENTS_REPO:-<unset>}\`"
log ""

# ---------------------------------------------------------------------- 0.4
# The extension is the renamed AI Toolkit and the legacy Foundry sidebar was
# retired, so an undated procedure goes stale without any error being raised.
# The version stamp is what makes this runbook falsifiable later.
log "## Toolkit extension version"
log ""
if command -v code >/dev/null 2>&1; then
  code --list-extensions --show-versions 2>/dev/null \
    | grep -i 'windows-ai-studio' >"$EVIDENCE/00-toolkit-version.txt"
  if [ -s "$EVIDENCE/00-toolkit-version.txt" ]; then
    log '```'
    cat "$EVIDENCE/00-toolkit-version.txt" | tee -a "$SUMMARY" >/dev/null
    log '```'
  else
    log "NOT INSTALLED - \`ms-windows-ai-studio.windows-ai-studio\` not found in \`code --list-extensions\`."
    note "Toolkit extension not installed."
    missing=$((missing + 1))
  fi
else
  log "NOT CAPTURED - the \`code\` CLI is not on PATH."
  note "VS Code 'code' CLI not on PATH; install it from the command palette."
  missing=$((missing + 1))
fi
log ""

# ---------------------------------------------------------------------- 0.5a
log "## planlint"
log ""
if command -v "${PLANLINT_BIN:-planlint}" >/dev/null 2>&1; then
  planlint_bin="${PLANLINT_BIN:-planlint}"

  version="$("$planlint_bin" --version 2>&1)"; log "- \`--version\`: \`$version\`"

  # Which machine-readable flag this build actually accepts. The MCP wrapper
  # reads PLANLINT_JSON_FLAG rather than assuming `--json`, and this is where
  # that value comes from.
  "$planlint_bin" validate --help >"$EVIDENCE/00-planlint-flags.txt" 2>&1
  # Probe for the *option name* only. An earlier revision grepped for
  # "--format=json", which never appears in help text that reads
  # "--format FORMAT", so a supported flag went unreported. Report the option
  # and let the operator write the exact spelling into PLANLINT_JSON_FLAG.
  json_flag_found=""
  for option in --json --format --output; do
    if grep -qE -- "(^|[[:space:],])${option}([[:space:],=]|$)" "$EVIDENCE/00-planlint-flags.txt" 2>/dev/null; then
      log "- \`validate --help\` mentions \`${option}\`"
      [ -n "$json_flag_found" ] || json_flag_found="$option"
    fi
  done
  if [ -n "$json_flag_found" ]; then
    log "- **set \`PLANLINT_JSON_FLAG\`** to the exact spelling this build wants (first candidate: \`$json_flag_found\`)"
  else
    log "- no machine-readable output option found; set \`PLANLINT_JSON_FLAG=\"\"\` (verdicts stay correct, findings degrade to raw text)"
  fi

  if [ -n "${PLANLINT_TARGET:-}" ]; then
    "$planlint_bin" --target "$PLANLINT_TARGET" detect --format json \
      >"$EVIDENCE/00-dialect-card.json" 2>"$EVIDENCE/00-dialect-card.stderr"
    log "- \`detect\` exit: $? -> \`evidence/00-dialect-card.json\`"

    "$planlint_bin" --target "$PLANLINT_TARGET" validate --fail-on ERROR \
      >"$EVIDENCE/00-validate.txt" 2>&1
    validate_exit=$?
    log "- \`validate --fail-on ERROR\` exit: **$validate_exit** ($(
      case $validate_exit in
        0) echo "PASS - no findings at or above ERROR" ;;
        1) echo "FINDINGS - run completed, problems found" ;;
        2) echo "BLOCKED - precondition or usage error; NOT a spec failure" ;;
        *) echo "unexpected - treat as BLOCKED" ;;
      esac
    ))"
    case $validate_exit in
      0|1) ;;
      *) note "planlint validate exited $validate_exit; the baseline expects 0 or 1." ;;
    esac
  else
    log "- SKIPPED - PLANLINT_TARGET is unset."
    missing=$((missing + 1))
  fi
else
  log "- NOT INSTALLED - \`${PLANLINT_BIN:-planlint}\` is not on PATH."
  missing=$((missing + 1))
fi
log ""

# ---------------------------------------------------------------------- 0.5b
log "## eval-harness"
log ""
if command -v eval-harness >/dev/null 2>&1 && [ -n "${AGENTS_REPO:-}" ] && [ -d "${AGENTS_REPO:-}" ]; then
  ( cd "$AGENTS_REPO" && eval-harness list-plugins ) >"$EVIDENCE/00-plugins.txt" 2>&1
  log "- \`list-plugins\` exit: $? -> \`evidence/00-plugins.txt\`"

  ( cd "$AGENTS_REPO" && eval-harness run --config demo/configs/eval.pass.yaml --offline ) \
    >"$EVIDENCE/00-demo-eval.txt" 2>&1
  demo_exit=$?
  log "- \`run --config demo/configs/eval.pass.yaml --offline\` exit: **$demo_exit** (baseline expects 0)"
  [ "$demo_exit" -eq 0 ] || note "Demo eval exited $demo_exit; the documented baseline is 0."
else
  log "- NOT CAPTURED - \`eval-harness\` not on PATH, or AGENTS_REPO unset/missing."
  missing=$((missing + 1))
fi
log ""

log "## Done-when"
log ""
log "- [ ] Toolkit version file written (\`evidence/00-toolkit-version.txt\`)"
log "- [ ] Dialect card captured (\`evidence/00-dialect-card.json\`)"
log "- [ ] planlint validate exit recorded (0 or 1)"
log "- [ ] Demo eval exit recorded (0)"

printf '\nWrote %s\n' "$SUMMARY" >&2
if [ "$missing" -gt 0 ]; then
  printf '%d baseline item(s) could not be captured. The file records which.\n' "$missing" >&2
  exit 1
fi
