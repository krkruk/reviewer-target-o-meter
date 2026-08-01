#!/usr/bin/env bash
# Thin wrapper around `make` so `./make.sh run <dir>` takes a positional dir.
# The Makefile is the single source of truth; this script only translates args:
#   ./make.sh run <dir>     ->  make run DIR=<dir>
#   ./make.sh {check|test|llm-test|help}  ->  passed straight through.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./make.sh check                 ruff + mypy
  ./make.sh test                  unit tests (smoke excluded)
  ./make.sh llm-test              live OpenRouter smoke (needs OPENROUTER_API_KEY)
  ./make.sh run <dir>             run the app against <dir>
  ./make.sh help                  show make targets
EOF
}

case "${1:-help}" in
  run)
    if [[ $# -lt 2 || -z "$2" ]]; then
      echo "Usage: ./make.sh run <dir>" >&2
      exit 2
    fi
    exec make run DIR="$2"
    ;;
  check|test|llm-test|help)
    exec make "$1"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
