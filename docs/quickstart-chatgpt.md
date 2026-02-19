# Quickstart: ChatGPT + physical-mcp

## Prerequisites
- ChatGPT account with custom connector/GPT Action capability
- Python 3.10+
- A USB/UVC camera connected

## Install
```bash
pip install 'physical-mcp[tunnel]'
physical-mcp
physical-mcp tunnel
```
Copy the HTTPS URL from `physical-mcp tunnel`.

## Verify
1. In ChatGPT, create/update your connector/GPT Action.
2. Set OpenAPI URL to your tunneled HTTPS endpoint.
3. Run a test action: list/get alerts or fetch a frame.

## First use
Try prompts:
- `Check my latest camera frame and summarize it.`
- `Create a watch rule for package delivery events.`

## Troubleshooting
- ChatGPT cannot use localhost directly; use HTTPS tunnel.
- If actions fail, keep tunnel process running and re-test.
