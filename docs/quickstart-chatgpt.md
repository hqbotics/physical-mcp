# Quickstart: ChatGPT + physical-mcp

Use physical-mcp as a GPT Action backend so ChatGPT can see camera events.

## 1) Install and run
```bash
pip install physical-mcp
physical-mcp
```

## 2) Start Vision API
```bash
physical-mcp serve --vision-api --host 0.0.0.0 --port 8000
```

## 3) Expose endpoint (if needed)
Use your preferred tunnel (Cloudflare/ngrok) and copy the HTTPS URL.

## 4) Configure GPT Action
In ChatGPT Actions:
- Import physical-mcp OpenAPI spec
- Set server URL to your HTTPS endpoint
- Save and test

## 5) Test prompt
`Check the latest frame and tell me if the pantry shelf looks low.`

## Why this matters
Most camera apps stop at a push alert. physical-mcp enables event -> reasoning -> action workflows from ChatGPT.

## Troubleshooting
- Action can’t call endpoint: verify HTTPS tunnel is live.
- Empty camera response: run `physical-mcp doctor` and validate camera access.