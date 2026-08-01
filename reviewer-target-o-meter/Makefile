# reviewer-target-o-meter — developer entry points.
# All targets invoke `uv run` from this dir (where pyproject.toml lives).
# make.sh is a thin wrapper that lets `./make.sh run <dir>` take a positional dir.

.PHONY: check test llm-test run help

check:          ## linters + static type verification
	uv run ruff check
	uv run mypy src

test:           ## unit tests (excludes the live LLM smoke set)
	uv run pytest -m "not smoke"

llm-test:       ## live OpenRouter smoke set (needs OPENROUTER_API_KEY; run on the system)
	SMOKE=1 uv run pytest -m smoke

run:            ## run the app: make run DIR=/path/to/checkout
	@test -n "$(DIR)" || { echo "Usage: make run DIR=/path/to/checkout"; exit 2; }
	uv run reviewer-target-o-meter "$(DIR)"

help:           ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/ :.*##/:/' | column -t -s ':'
