# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Multi-agent system built with Claude (Anthropic SDK) and Model Context Protocol (MCP).

**Architecture:**
1. **Agents** (`agents/`) - Individual agent implementations (chatbot, pr_agent, security_researcher, business_advisor, task_manager, code_reviewer, email_intake, notifier, orchestrator, red_team, events, code_analysis)
2. **API Server** (`api/`) - FastAPI REST server for HTTP access to agents
3. **Web UI** (`webui/`) - React web interface for agents
4. **MCP Server** (`mcp_server/`) - MCP server config and OAuth infrastructure
5. **Infrastructure** (`infra/`) - Grafana, Loki, Promtail configs
6. **Shared Utilities** (`shared/`) - Common code reusable across agents
7. **Packages** (`packages/`) - Internal libraries:
   - `agent-framework/` - Base Agent class, MCP tools, MCP client, security utilities
   - `chasm/` - Voice interface (optional, `uv sync --group voice`)
8. **Documentation** (`docs/`) - Project docs and guides
9. **Entry Points** (`bin/`) - Executable scripts
10. **Runtime Data** (`.data/`) - Logs, memories, tokens

## Development Setup

```bash
uv sync                                          # Install dependencies
uv run python bin/run-agent <name>                # Run any agent (chatbot, pr, security, etc.)
uv run python bin/run-agent <name> "message"      # One-off message
uv run python -m api                              # REST API server (localhost:8080)
cd webui/frontend && npm install && npm run dev    # Web UI dev server (localhost:5173)
uv run python -m mcp_server.server                # MCP server standalone
```

**Environment:** Copy `.env.example` to `.env`, add `ANTHROPIC_API_KEY`.

## Architecture

```
User Input -> Agent (agents/*/main.py) -> Claude API -> agent-framework (MCP Client)
                ^                                              |
                |                                       MCP Server (stdio)
                |                                              |
                +------------ Tool Results <------------- Tools (agent-framework/tools/)
```

**Key patterns:**
- Agent reconnects to MCP server for **each tool call** (enables hot reload of tools)
- Max 10 iterations per turn to prevent infinite loops
- Tool errors returned to Claude as `is_error` results
- Type `reload` in agent to force tool rediscovery

## Key Files

- `agents/*/main.py` - Agent implementations extending `Agent` base class
- `agents/*/prompts.py` - System prompts defining agent behavior
- `api/server.py` - REST API server
- `mcp_server/server.py` - MCP server (registers agent-framework tools)
- `mcp_server/auth/` - OAuth handler and token storage
- `shared/agent_factory.py` - Factory for creating simple agents
- `packages/agent-framework/agent_framework/tools/` - All MCP tools
- `packages/agent-framework/agent_framework/core/` - Base Agent class and MCP client
- `packages/agent-framework/agent_framework/security/` - SSRF protection

## Adding New Agents

**MANDATORY RULES:**
1. **Subclass `Agent`** from `agent_framework`, or use `create_simple_agent()` from `shared/agent_factory.py`
2. **Register in `bin/run-agent`** in the `AGENTS` dict
3. **Export agent class** from `main.py` at module level

**Steps:**

1. Create `agents/your_agent/` with `main.py`, `prompts.py`, `__init__.py`
2. Subclass `Agent` or use factory:
   ```python
   # Option A: Direct subclass
   from agent_framework import Agent
   class YourAgent(Agent):
       def get_system_prompt(self) -> str: return SYSTEM_PROMPT
       def get_greeting(self) -> str: return USER_GREETING_PROMPT

   # Option B: Factory
   from shared import create_simple_agent
   YourAgent = create_simple_agent(
       name="YourAgent", system_prompt=SYSTEM_PROMPT,
       greeting=USER_GREETING_PROMPT, allowed_tools=["fetch_web_content"],
   )
   ```
3. Register in `bin/run-agent`:
   ```python
   from agents.your_agent.main import YourAgent
   AGENTS = { ..., "your-agent": (YourAgent, None), }
   ```

## Development Workflow

**Hot reload:** Edit tools in `packages/agent-framework/agent_framework/tools/`, changes picked up on next tool call. Type `reload` to force reconnection.

**Testing:** See [docs/TESTING.md](docs/TESTING.md).

**Quick debugging:**
```bash
uv run python scripts/testing/test_memory.py stats
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log
uv run python -m mcp_server.server
```

## Code Style

- Modern Python typing: `dict`/`list` not `typing.Dict`/`List`, `str | None` not `Optional[str]`
- All functions have type hints including return types
- Async/await for all I/O
- Google-style docstrings
- JSON for all tool results

## Current State

**Working:** Full agentic loop (Claude Sonnet 4.5), 12 agents, 51 MCP tools, web scraping, RAG search, FastMail email, Twilio SMS, persistent memory, hot reload, OAuth infrastructure, REST API, Web UI, Langfuse observability.

**Needs work:** Social media tools use mock data, rate limiting, multi-user support, security hardening for public deployments.

## Extended Documentation

- [docs/tools.md](docs/tools.md) - MCP tools reference (all 51 tools + usage examples)
- [docs/api.md](docs/api.md) - REST API endpoints and database schema
- [docs/oauth.md](docs/oauth.md) - OAuth infrastructure setup
- [docs/observability.md](docs/observability.md) - Langfuse tracing and monitoring
- [docs/GUIDES.md](docs/GUIDES.md) - Feature guides (memory, OAuth, deployment)
- [docs/TESTING.md](docs/TESTING.md) - Testing and debugging guide
- [docs/HOT_RELOAD.md](docs/HOT_RELOAD.md) - Hot reload development workflow
- [docs/REMOTE_MCP.md](docs/REMOTE_MCP.md) - Remote MCP setup
- [docs/docker.md](docs/docker.md) - Docker deployment
- [docs/CLAUDE_CODE_TOOLS.md](docs/CLAUDE_CODE_TOOLS.md) - Claude Code automation tools
