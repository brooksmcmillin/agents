# Red Team Agent

Authorized penetration testing agent that performs dynamic security testing against web applications using HTTP client tools, with memory for persisting findings and email for sending reports.

## Features

- **Dynamic testing** — probe API endpoints for vulnerabilities using HTTP client tools
- **OWASP coverage** — tests for injection, auth bypass, IDOR, SSRF, rate limiting gaps
- **Finding persistence** — saves discovered vulnerabilities to memory for tracking
- **Report delivery** — sends findings via email and Slack notifications
- **Configurable target** — test any authorized web application

## Quick Start

```bash
# Set target URL (defaults to https://your-app.example.com)
export REDTEAM_TARGET_URL=https://your-authorized-target.com

uv run bin/run-agent red-team
```

**Important:** Only use against applications you have explicit authorization to test.

## MCP Tools

- HTTP client tools (`http_get`, `http_post`, `http_put`, `http_delete`, `http_patch`, `http_head`, `http_options`) — probe endpoints
- `fetch_web_content` — analyze web responses
- `save_memory`, `get_memories`, `search_memories` — persist findings
- `send_email` (+ other FastMail tools) — deliver reports
- `send_slack_message` — alert on critical findings

## Usage Examples

```
You: Test the authentication endpoints for vulnerabilities
Agent: [probes login, register, logout for common auth weaknesses]

You: Check for IDOR on the tasks API
Agent: [creates test accounts, attempts cross-account task access]

You: Generate a report of all findings
Agent: [compiles findings from memory, sends via email]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — target URL (default: https://your-app.example.com)
REDTEAM_TARGET_URL=https://your-target.com

# Optional — report delivery
FASTMAIL_API_TOKEN=...
FASTMAIL_ACCOUNT_ID=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Architecture

Uses `create_simple_agent()` with HTTP client, memory, communication, email, and web fetching tools. The system prompt includes known API routes for the configured target to guide testing.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
