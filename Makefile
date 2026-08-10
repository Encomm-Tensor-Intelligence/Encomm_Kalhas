# KALHAS convenience targets.
# All targets delegate to `uv run`, so they work without activating the venv
# and without GNU make (see README for the make-free equivalents).

.PHONY: setup run test lint format format-check typecheck check

setup:
	uv sync --python 3.12

run:
	uv run uvicorn kalhas.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy kalhas tests

check: lint format-check typecheck test
