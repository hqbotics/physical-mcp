.PHONY: install dev test lint format build publish clean doctor debug-app debug-app-clean run-app release-app

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

# ── Flutter App ──────────────────────────────────────

debug-app:
	./scripts/dev.sh

debug-app-clean:
	./scripts/dev.sh --clean --rebuild-backend

run-app:
	open "app/build/macos/Build/Products/Debug/Physical MCP.app"

release-app:
	./scripts/build-release.sh
