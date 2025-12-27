# Multi-Agent System

A multi-agent system built with Claude (Anthropic SDK) and Model Context Protocol (MCP). This repository supports multiple specialized agents that share common infrastructure for content analysis, task management, and persistent memory.

## Overview

This project demonstrates production-ready patterns for building LLM-powered agents with external tool integrations. It includes:

- **Multiple Agents** - PR assistant, task manager, and notification system
- **Shared MCP Tools** - Content analysis, social media stats, persistent memory
- **Hot Reload** - Edit tools without restarting agents
- **OAuth Infrastructure** - Ready for real API integration
- **Remote MCP Support** - Deploy tools separately from agents

## Quick Start

### Prerequisites

- Python 3.11 or higher
- `uv` package manager
- Anthropic API key

### Installation

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=your_key_here
```

### Run an Agent

```bash
# PR Agent - Content strategy assistant
uv run python -m agents.pr_agent.main

# Task Manager - Interactive task management
uv run python -m agents.task_manager.main

# Notifier - Send Slack notifications about tasks
uv run python -m agents.notifier.main

# Demo - Test MCP tools without agent
uv run python demo.py
```

### Interactive Commands

Once an agent is running:
- `exit` or `quit` - End session
- `stats` - Show token usage statistics
- `reload` - Reconnect to MCP server and discover updated tools

## Architecture

### System Overview

```
User Input → Agent → Claude API → MCP Client → MCP Server → Tools
                ↑                                               ↓
                └────────────── Tool Results ←──────────────────┘
```

### Components

**1. Agents** (`agents/`)
- Individual agent implementations extending `agent-framework`
- Each agent has its own system prompt and behavior
- Share common MCP tools and infrastructure

**2. MCP Server** (`mcp_server/`)
- Exposes tools via Model Context Protocol
- Handles authentication and tool execution
- Can run locally (stdio) or remotely (HTTP/SSE)

**3. Shared Utilities** (`shared/`)
- Common code reusable across agents
- Remote MCP client implementation
- OAuth helpers and utilities

### Agentic Loop

```python
while not done:
    # 1. Call Claude with conversation history + available tools
    response = await client.messages.create(messages=history, tools=tools)

    # 2. If Claude wants to use tools, execute them via MCP
    if response.stop_reason == "tool_use":
        async with mcp_client.connect():  # Fresh connection (hot reload)
            results = await mcp_client.call_tool(name, args)
        history.append(tool_results)
        # Loop continues - Claude analyzes results

    # 3. Claude provides final text response
    else:
        return response.content
```

**Key Feature:** The agent reconnects to MCP server for each tool call, enabling hot reload of tools without losing conversation context.

## Available Agents

### PR Agent
Content strategy assistant that helps with:
- Blog post analysis and optimization
- Social media strategy and engagement
- SEO recommendations
- Brand voice consistency

**Run:** `uv run python -m agents.pr_agent.main`

### Task Manager
Intelligent task management assistant:
- Reschedule overdue tasks
- Pre-research upcoming tasks
- Prioritize based on urgency and dependencies
- Connect to remote task management server

**Run:** `uv run python -m agents.task_manager.main`

### Task Notifier
Lightweight notification script (not a full agent):
- Sends Slack updates about open tasks
- Categorizes overdue, due today, and upcoming
- Can be run via cron for automated notifications

**Run:** `uv run python -m agents.notifier.main`

See individual agent directories for detailed documentation.

## MCP Tools

The MCP server exposes these tools to all agents:

### Content Analysis Tools
- `analyze_website` - Web content analysis (tone, SEO, engagement) with real web scraping
- `fetch_web_content` - Fetch and read web content as clean markdown
- `get_social_media_stats` - Social media metrics (currently mock data)
- `suggest_content_topics` - Content idea generation (currently mock data)

### Memory Tools
- `save_memory` - Save information with key/value/category/tags/importance
- `get_memories` - Retrieve memories with filtering
- `search_memories` - Search memories by keyword

Memory persists across conversations in `memories/memories.json`.

## Project Structure

```
agents/
├── agents/              # Agent implementations
│   ├── pr_agent/        # PR and content strategy assistant
│   ├── task_manager/    # Interactive task management
│   └── notifier/        # Slack notification script
├── mcp_server/          # Shared MCP server and tools
│   ├── server.py        # MCP server (stdio transport)
│   ├── server_http.py   # MCP server (HTTP/SSE transport)
│   ├── tools/           # Tool implementations
│   ├── auth/            # OAuth handler and token storage
│   └── memory_store.py  # Persistent memory system
├── shared/              # Common utilities
│   └── remote_mcp_client.py  # Remote MCP client
├── scripts/             # Utility scripts
├── demo.py              # MCP tools demo
├── CLAUDE.md            # Project instructions for Claude Code
├── GUIDES.md            # Feature guides (hot reload, memory, remote MCP)
└── README.md            # This file
```

## Development Workflow

### Hot Reload - Edit Tools Without Restarting

1. Start agent: `uv run python -m agents.pr_agent.main`
2. Edit tool code in `mcp_server/tools/*.py`
3. Save changes
4. Next tool call automatically picks up changes
5. Type `reload` to force reconnection if needed

The agent reconnects to MCP server for each tool call instead of maintaining a persistent connection. This enables editing tools while the agent is running without losing conversation context.

### Adding a New Tool

1. Create implementation in `mcp_server/tools/your_tool.py`:
```python
async def your_tool(param: str) -> dict[str, Any]:
    # Implementation
    return {"result": "data"}
```

2. Export from `mcp_server/tools/__init__.py`:
```python
from .your_tool import your_tool
```

3. Register in `mcp_server/server.py`:
   - Add to `list_tools()` function with schema
   - Add handler in `call_tool()` function
   - Tool automatically available to Claude on next reconnection

### Adding a New Agent

1. Create agent directory: `mkdir -p agents/your_agent`
2. Create `main.py` extending `Agent` class from `agent-framework`
3. Create `prompts.py` with system prompt and greeting
4. Create `__init__.py` with version info
5. Run: `uv run python -m agents.your_agent.main`

All agents automatically have access to the shared MCP tools.

See [CLAUDE.md](CLAUDE.md#adding-new-agents) for detailed instructions.

## Features

### Persistent Memory
- Agents can save and recall information across conversations
- Category-based organization (preferences, facts, goals, insights)
- Importance-based prioritization (1-10 scale)
- Tag-based filtering
- Easily migrated from file storage to database

### OAuth Support
- Complete OAuth 2.0 implementation (Authorization Code Flow + Client Credentials)
- Automatic token refresh
- Encrypted token storage (Fernet)
- Ready for Twitter, LinkedIn, and other social media APIs
- File-based storage with easy migration path to database/vault

### Remote MCP
- Host MCP server separately from agents
- Multiple agents can share one server
- HTTP/SSE transport for cloud deployment
- Local (stdio) and remote (HTTP) modes supported

### Error Handling
- Comprehensive error logging
- Graceful failure handling
- Tool errors returned to Claude as `is_error` results
- Max iteration limits to prevent infinite loops

## Current Status vs Production

**Working Now:**
- Full agentic loop with Claude Sonnet 4.5
- 7 MCP tools (content analysis + memory)
- Real web scraping and content analysis
- Persistent memory across conversations
- Hot reload for tool development
- OAuth infrastructure (not connected to real APIs)
- Token usage tracking
- Remote MCP support

**For Production:**
- Integrate real social media APIs (Twitter, LinkedIn)
- Migrate to PostgreSQL/Redis for memory and tokens
- Add rate limiting
- Add multi-user support (user_id to memory/auth)
- Deploy MCP server remotely
- Add monitoring and metrics

## Configuration

### Environment Variables

See `.env.example` for all available options. Key variables:

```bash
# Required
ANTHROPIC_API_KEY=your_api_key_here

# Optional - MCP Server
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp  # For remote MCP

# Optional - Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR

# Optional - Social Media OAuth (when ready)
TWITTER_CLIENT_ID=...
TWITTER_CLIENT_SECRET=...
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
```

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Comprehensive project documentation for Claude Code
- **[GUIDES.md](GUIDES.md)** - Feature guides (hot reload, memory, remote MCP)
- **Agent READMEs** - See `agents/*/README.md` for agent-specific docs
- **Code Comments** - Extensive inline documentation

## Troubleshooting

### Agent Issues

```bash
# Check logs
tail -f pr_agent.log

# Enable debug logging
# In .env: LOG_LEVEL=DEBUG

# Test MCP tools in isolation
uv run python demo.py
```

### MCP Connection Issues

```bash
# Test MCP server starts
uv run python -m mcp_server.server

# Test remote MCP connection
curl https://mcp.brooksmcmillin.com/mcp/health
```

### Memory Issues

```bash
# View memories
cat memories/memories.json | python -m json.tool

# Clear all memories
rm memories/memories.json
```

## Technology Stack

- **Python 3.11+**
- **anthropic** - Official Anthropic SDK for Claude
- **agent-framework** - Base agent class and MCP client
- **mcp** - Model Context Protocol SDK
- **httpx** - Async HTTP client
- **authlib** - OAuth 2.0 implementation
- **cryptography** - Token encryption (Fernet)
- **pydantic** - Data validation and settings
- **python-dotenv** - Environment management

## Code Style

- Modern Python typing (dict/list not typing.Dict/List, `str | None` not Optional[str])
- All functions have type hints including return types
- All async I/O operations use async/await
- Comprehensive docstrings (Google style)
- Errors logged before returning to user
- JSON for all tool results

## Contributing

To extend this project:
1. Follow existing code patterns
2. Add type hints to all functions
3. Write docstrings (Google style)
4. Test with demo script
5. Update documentation

## License

This is a demonstration project for educational purposes.

---

**Built with Claude Sonnet 4.5 and Model Context Protocol**
