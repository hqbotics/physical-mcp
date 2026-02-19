# Contributing to physical-mcp

Thanks for helping improve physical-mcp.

## Development setup
```bash
git clone https://github.com/idnaaa/physical-mcp.git
cd physical-mcp
uv sync
make test
```

## Workflow
1. Create a branch: `feat/<name>` or `fix/<name>`.
2. Make focused changes with tests.
3. Run checks locally:
```bash
make format
make lint
make test
```
4. Open a PR with clear summary + screenshots/logs when relevant.

## PR expectations
- One logical change per PR
- Include/adjust tests for behavior changes
- Update docs when commands or UX change
- Avoid unrelated refactors

## Commit style
Use concise, imperative messages, e.g.:
- `fix: handle camera reconnect in perception loop`
- `docs: add chatgpt quickstart`

## Reporting bugs
Use the bug template and include:
- OS, Python version
- physical-mcp version
- exact command run
- logs/error text

## Feature requests
Use the feature template with:
- user story
- expected behavior
- alternatives considered

## Code of conduct
Be respectful, specific, and constructive in issues and PRs.
