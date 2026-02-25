.PHONY: install dev test lint format build publish clean doctor

install:
	uv pip install .

dev:
	uv pip install -e ".[dev,all]"

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

build:
	uv build

publish: build
	uv publish

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache

doctor:
	uv run physical-mcp doctor
