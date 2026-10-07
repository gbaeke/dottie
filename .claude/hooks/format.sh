#!/usr/bin/env bash
# After Claude edits a file: ruff fixes and formats Python, prettier formats the frontend, so style never needs
# a review.
# Reads the hook's JSON on stdin; never blocks the edit.
file=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')
case "$file" in
  *.py)
    cd "$CLAUDE_PROJECT_DIR" || exit 0
    uv run --quiet ruff check --fix --quiet "$file" >/dev/null 2>&1
    uv run --quiet ruff format --quiet "$file" >/dev/null 2>&1
    ;;
  */frontend/src/*)
    cd "$CLAUDE_PROJECT_DIR/frontend" && npx --no-install prettier --write --log-level silent "$file" >/dev/null 2>&1
    ;;
esac
exit 0
