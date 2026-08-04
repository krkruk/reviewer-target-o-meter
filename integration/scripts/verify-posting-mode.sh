#!/usr/bin/env bash
# verify-posting-mode.sh — integration/system check for posting mode (manual step 2.6).
#
# Runs the REAL reviewer-target-o-meter in posting mode (PR env vars set) against a
# checked-out repo and asserts the trace + Markdown preview still stream to stderr
# AROUND the post, and stdout stays empty on a successful post (today's behavior:
# post → exit, no stdout emit). This mirrors what the consumer GitHub Actions step
# log shows, locally.
#
# By default it runs in DRY-RUN mode: a fake PR number + a throwaway token against
# the real GITHUB_REPOSITORY you pass, so the post will FAIL (bad token / 401) and
# degrade to stdout + a WARNING — exercising the degrade breadcrumb path, which is
# the safe, side-effect-free local check. Set POST_REAL=1 with a real token + PR to
# actually post a comment (creates a real PR comment — use with care).
#
# Usage:
#   OPENROUTER_API_KEY=sk-... ./integration/scripts/verify-posting-mode.sh REPO_PATH GITHUB_REPOSITORY [PR_NUMBER]
#   (e.g.  ... ./integration/scripts/verify-posting-mode.sh ../target-o-meter krkruk/target-o-meter 42)
#
# Env:
#   OPENROUTER_API_KEY   (required) live key.
#   POST_REAL=1          (optional) actually post a comment (needs a real token in
#                         GITHUB_TOKEN and a real PR_NUMBER); default is dry-run.
#   GITHUB_TOKEN         (optional) real token; required when POST_REAL=1.
#   LOG_LEVEL            (optional) default INFO.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "$SCRIPT_DIR/../../reviewer-target-o-meter" && pwd)"

REPO_PATH="${1:?usage: $0 REPO_PATH GITHUB_REPOSITORY [PR_NUMBER]}"
GH_REPO="${2:?usage: $0 REPO_PATH GITHUB_REPOSITORY [PR_NUMBER]}"
PR_NUMBER="${3:-${PR_NUMBER:-0}}"

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "FAIL: OPENROUTER_API_KEY is not set (required for the live run)." >&2
  exit 1
fi
if [ ! -d "$REPO_PATH" ]; then
  echo "FAIL: target repo not found at $REPO_PATH" >&2
  exit 1
fi

export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export PR_NUMBER="$PR_NUMBER"
export GITHUB_REPOSITORY="$GH_REPO"
export GITHUB_API_URL="${GITHUB_API_URL:-https://api.github.com}"

if [ "${POST_REAL:-0}" = "1" ]; then
  if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "FAIL: POST_REAL=1 requires a real GITHUB_TOKEN." >&2
    exit 1
  fi
  echo ">> POST_REAL=1 — a REAL comment will be posted to $GH_REPO#$PR_NUMBER"
else
  # Dry-run: a throwaway token guarantees a posting failure → degrade path.
  export GITHUB_TOKEN="dry-run-not-a-real-token"
  echo ">> DRY-RUN — posting will fail (bad token) and degrade to stdout + WARNING."
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STDOUT="$TMP/stdout.log"
STDERR="$TMP/stderr.log"

echo ">> running reviewer-target-o-meter (posting mode) against: $REPO_PATH"
cd "$PKG_DIR"
set +e
uv run reviewer-target-o-meter "$REPO_PATH" 1>"$STDOUT" 2>"$STDERR"
TOOL_EXIT=$?
set -e

echo ">> tool advisory exit code: $TOOL_EXIT"

fail=0
check() { if eval "$2"; then echo "   PASS: $1"; else echo "   FAIL: $1 ($2)"; fail=1; fi; }

echo ">> assertions:"
# The trace + preview are independent of post success/failure.
check "review-start breadcrumb on stderr"  "grep -qi 'review start' '$STDERR'"
check "review-complete breadcrumb on stderr" "grep -qi 'review complete' '$STDERR'"
check "post-attempt breadcrumb on stderr"   "grep -qi 'post attempt' '$STDERR'"
check "Markdown preview header on stderr"   "grep -q '^# reviewer-target-o-meter' '$STDERR'"
check "stdout has no Markdown preview"      "! grep -q '# reviewer-target-o-meter' '$STDOUT'"
check "stdout has no trace"                 "! grep -qi 'review start' '$STDOUT'"

if [ "${POST_REAL:-0}" = "1" ]; then
  # Real post → success breadcrumb; stdout empty (post path exits without emitting).
  check "post-success breadcrumb on stderr" "grep -qi 'post success' '$STDERR'"
else
  # Dry-run → degrade: post-failed breadcrumb + WARNING + stdout JSON fallback.
  check "post-failed/degrade breadcrumb on stderr" "grep -qi 'post failed' '$STDERR'"
  check "WARNING degrade token on stderr"          "grep -q 'WARNING' '$STDERR'"
  check "stdout is valid JSON (degrade fallback)"  "python3 -c \"import json; json.load(open('$STDOUT'))\""
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: PASS — posting-mode trace + preview + post breadcrumb all hold."
else
  echo "RESULT: FAIL — one or more assertions failed."
  echo "----- stderr (trace + preview) -----"; cat "$STDERR"
  echo "----- stdout -----"; head -20 "$STDOUT"
fi
exit "$fail"
