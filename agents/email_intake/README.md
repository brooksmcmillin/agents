# Email Intake

Daemon that monitors an email inbox for task requests from the admin and routes them to appropriate agents for processing.

**This is a standalone service, not an interactive CLI agent.** It does not use the agent registry or `bin/run-agent`.

## Features

- **Email monitoring** — checks an inbox for unread emails from the admin
- **Agent routing** — matches email content to the best agent using keyword scoring
- **Task creation** — "Add task:" subject prefix creates tasks directly via the task manager
- **Security** — requires a shared secret in the email body to prevent spoofing
- **Permission model** — delegated agents run with restricted permissions (read + send by default)
- **Reply and archive** — sends results back via email and archives the original

## Quick Start

```bash
# Run once (check and process emails)
uv run python -m agents.email_intake.main

# Interactive mode
uv run python -m agents.email_intake.main --interactive

# Dry run (preview without sending replies)
uv run python -m agents.email_intake.main --dry-run

# Show configuration status
uv run python -m agents.email_intake.main --status

# Grant write permissions to delegated agents
uv run python -m agents.email_intake.main --allow-writes

# Full access for delegated agents
uv run python -m agents.email_intake.main --full-access
```

## Agent Routing

Emails are routed based on keyword matching:

| Agent | Keywords |
|-------|----------|
| `pr` | content, seo, website, blog, social media, marketing |
| `security` | security, vulnerability, cve, exploit, penetration |
| `business` | business, monetization, revenue, pricing, strategy |
| `tasks` | task, remind, schedule, todo, deadline |
| `events` | event, concert, show, festival, local |
| `chatbot` | default fallback |

Emails with subject starting with "Add task:" bypass routing and go directly to the task manager.

## Configuration

```bash
# Required
INTAKE_EMAIL_ADDRESS=intake@example.com    # inbox to monitor
ADMIN_EMAIL_ADDRESS=admin@example.com      # only process emails from this sender
INTAKE_SHARED_SECRET=your-random-secret    # must appear in email body
FASTMAIL_API_TOKEN=...
FASTMAIL_ACCOUNT_ID=...

# Required for task creation via "Add task:" emails
MCP_SERVER_URL=https://your-mcp-server.example.com/mcp
```

## Security Model

- **Sender validation** — only processes emails from `ADMIN_EMAIL_ADDRESS`
- **Shared secret** — email body must contain `INTAKE_SHARED_SECRET` (timing-safe comparison)
- **Permission restriction** — delegated agents get read + send only by default
- **Rate limiting** — max 5 "Add task" emails per run

## Architecture

Standalone script using FastMail JMAP API directly (via `agent_framework.tools.fastmail`). Routes emails to agents from `shared.registry`, running each in a restricted `ExecutionContext`. Not an MCP-based agent — it calls agent classes programmatically.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
