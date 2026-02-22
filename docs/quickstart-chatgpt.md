# Quickstart: ChatGPT + physical-mcp

Use physical-mcp as a GPT Action backend so ChatGPT can see camera events.

## 1) Install and run

```bash
pip install physical-mcp
physical-mcp
```

## 2) Start Vision API

In another terminal, start the HTTP server:

```bash
physical-mcp --transport streamable-http --port 8090
```

Or run as background service:
```bash
physical-mcp install --port 8090
```

## 3) Expose endpoint via tunnel

```bash
physical-mcp tunnel --provider cloudflare
```

Copy the HTTPS URL (e.g., `https://xxxx.trycloudflare.com`).

## 4) Configure GPT Action

In ChatGPT Actions:
- Download [openapi-simple.yaml](https://raw.githubusercontent.com/idnaaa/physical-mcp/main/gpt-action/openapi-simple.yaml)
- Import the OpenAPI spec into ChatGPT
- Set server URL to your HTTPS endpoint
- Save and test

## 5) Test prompt

`Check the latest frame and tell me if the pantry shelf looks low.`

## Why this matters

Most camera apps stop at a push alert. physical-mcp enables event -> reasoning -> action workflows from ChatGPT.

## Troubleshooting

- Action can't call endpoint: verify HTTPS tunnel is live.
- Empty camera response: run `physical-mcp doctor` and validate camera access.
