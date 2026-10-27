#!/usr/bin/env bash
# Roda tudo o que precisa estar verde antes de um commit: lint, formatação, tipos e testes.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --locked --quiet
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
