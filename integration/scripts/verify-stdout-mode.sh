#!/usr/bin/env bash
# verify-stdout-mode.sh — integration/system check for stdout mode (manual steps 1.5, 2.5).
#
# Runs the REAL reviewer-target-o-meter against a checked-out repo in stdout mode
# (no PR env vars → no posting) and asserts the Phase-2 observability contract:
#   - the INFO step trace appears on STDERR,
#   - the Markdown preview appears on STDERR,
#   - stdout is the pure FindingsReport JSON (uncontaminated by the trace/preview).
#
# This automates the manual verification steps "make run DIR=... shows INFO on
# stderr; stdout unchanged JSON" so they can run as part of integration/system
# testing instead of by hand.
#
# Usage:
#   OPENROUTER_API_KEY=sk-... ./integration/scripts/verify-stdout-mode.sh [REPO_PATH]
#
# Env:
#   OPENROUTER_API_KEY  (required) — live key for the real agentic run.
#   CONSUMER_REPO       (optional) — default REPO_PATH if the arg is omitted.
#   LOG_LEVEL           (optional) — default INFO; raise to DEBUG for more, drop
#                        to WARNING to confirm the trace is silenced but the
#                        preview still shows.
#
# Exits 0 if all assertions hold, 1 otherwise. The tool's OWN advisory exit code
# (0/1 from findings) is NOT this script's exit — this script checks observability,
# not whether findings were flagged.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "$SCRIPT_DIR/../../reviewer-target-o-meter" && pwd)"

REPO_PATH="${1:-${CONSUMER_REPO:-$PKG_DIR/tests/fixtures/sample-repo}}"
REPO_PATH="$(cd "$REPO_PATH" 2>/dev/null && pwd || echo "$REPO_PATH")"

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "FAIL: OPENROUTER_API_KEY is not set (required for the live run)." >&2
  exit 1
fi
if [ ! -d "$REPO_PATH" ]; then
  echo "FAIL: target repo not found at $REPO_PATH" >&2
  exit 1
fi

export LOG_LEVEL="${LOG_LEVEL:-INFO}"
# Force stdout mode regardless of ambient PR env vars.
unset PR_NUMBER GITHUB_TOKEN GITHUB_REPOSITORY || true

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STDOUT="$TMP/stdout.log"
STDERR="$TMP/stderr.log"

echo ">> running reviewer-target-o-meter (stdout mode) against: $REPO_PATH"
echo ">> LOG_LEVEL=$LOG_LEVEL"
# `make run` itself prints the uv command to stdout; redirect only the tool's
# own streams. We invoke the console script directly to capture cleanly.
cd "$PKG_DIR"
set +e
uv run reviewer-target-o-meter "$REPO_PATH" 1>"$STDOUT" 2>"$STDERR"
TOOL_EXIT=$?
set -e

echo ">> tool advisory exit code: $TOOL_EXIT (0=clean, 1=findings flagged; both OK here)"

fail=0
check() { # check DESCRIPTION CONDITION_MESSAGE
  if eval "$2"; then echo "   PASS: $1"; else echo "   FAIL: $1 ($2)"; fail=1; fi
}

echo ">> assertions:"
# Advisory exit is 0 or 1 — anything else is a crash, not a finding.
check "tool exit is advisory (0 or 1)" "[ \"\$TOOL_EXIT\" -eq 0 ] || [ \"\$TOOL_EXIT\" -eq 1 ]"
# INFO step trace on stderr.
check "INFO step trace on stderr"         "grep -qi 'review start' '$STDERR'"
check "diff breadcrumb on stderr"         "grep -qi 'diff computed' '$STDERR'"
check "review-complete breadcrumb on stderr" "grep -qi 'review complete' '$STDERR'"
# Markdown preview on stderr.
check "Markdown preview header on stderr" "grep -q '^# reviewer-target-o-meter' '$STDERR'"
# stdout is the pure JSON contract.
check "stdout is valid JSON"              "python3 -c \"import json,sys; json.load(open('$STDOUT'))\""
check "stdout has findings key"           "python3 -c \"import json; assert 'findings' in json.load(open('$STDOUT'))\""
check "stdout has no trace (review start)"   "! grep -qi 'review start' '$STDOUT'"
check "stdout has no Markdown preview"       "! grep -q '# reviewer-target-o-meter' '$STDOUT'"

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: PASS — stdout/stderr split + trace + preview all hold."
else
  echo "RESULT: FAIL — one or more assertions failed."
  echo "----- stderr (trace + preview) -----"
  cat "$STDERR"
  echo "----- stdout (JSON) -----"
  head -20 "$STDOUT"
fi
exit "$fail"
