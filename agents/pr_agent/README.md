# PR Agent

Content strategy assistant that analyzes web content, provides SEO and engagement recommendations, manages brand voice consistency, and can modify website source code via Claude Code integration.

## Features

- **Content analysis** — review blog posts, websites, and social media for tone, SEO, and engagement
- **Strategy recommendations** — content calendars, topic suggestions, audience analysis
- **Brand consistency** — ensure voice and style align across all content
- **Email management** — draft and send content via FastMail
- **Code editing** — modify website source code directly via Claude Code workspaces
- **Persistent memory** — remember user preferences, brand guidelines, and past analyses

## Quick Start

```bash
uv run bin/run-agent pr
```

## MCP Tools

- `fetch_web_content`, `analyze_website` — web content analysis
- `suggest_content_topics`, `get_social_media_stats` — content strategy
- `save_memory`, `get_memories`, `search_memories` — persist brand context
- `send_email`, `search_emails` (+ other FastMail tools) — email management
- `send_slack_message` — notifications
- Claude Code tools — create/manage workspaces, run code edits

## Usage Examples

```
You: Analyze https://myblog.com for SEO issues
Agent: [fetches site, analyzes content, provides actionable recommendations]

You: Create a 2-week content calendar for my AI security blog
Agent: [checks saved brand preferences, generates calendar with topics and timing]

You: Update the hero section copy on my landing page
Agent: [creates Claude Code workspace, edits source files, reports changes]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — email integration
FASTMAIL_API_TOKEN=...
FASTMAIL_ACCOUNT_ID=...

# Optional — notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Architecture

Uses `create_simple_agent()` with content, memory, communication, email, and Claude Code tools. The agent maintains brand context across conversations via persistent memory.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
- [docs/CLAUDE_CODE_TOOLS.md](../../docs/CLAUDE_CODE_TOOLS.md) — Claude Code integration
