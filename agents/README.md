# Agents

This directory contains all agent implementations. Each agent is a standalone application that extends the `Agent` class from `agent-framework`.

## Available Agents

### PR Agent (`pr_agent/`)
PR and content strategy assistant that helps with:
- Content analysis and optimization
- Social media strategy and engagement
- SEO and content marketing
- Brand voice consistency

**Run:** `uv run python -m agents.pr_agent.main`

## Adding New Agents

See the main [CLAUDE.md](../CLAUDE.md#adding-new-agents) for instructions on creating new agents.

## Shared Resources

All agents have access to:
- **MCP Server** (`../mcp_server/`) - Shared tools for content analysis, memory, etc.
- **Shared utilities** (`../shared/`) - Common code reusable across agents
