# Multi-Agent System

A multi-agent system built with Claude (Anthropic SDK) and Model Context Protocol (MCP). This repository supports multiple specialized agents that share common infrastructure for content analysis, task management, and persistent memory.

## Overview

This project demonstrates production-ready patterns for building LLM-powered agents with external tool integrations. It includes:

- **Multiple Agents** - 7 specialized agents including PR assistant, chatbot, security researcher, business advisor, task manager, REST API server, and notification system
- **Shared MCP Tools** - 29 tools including web analysis, memory, RAG document search, email management, and communication
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

# Optional: Install voice interface dependencies
# Requires PortAudio system library (sudo apt-get install portaudio19-dev on Ubuntu)
uv sync --group voice

# Configure environment
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=your_key_here
```

### Run an Agent

```bash
# Chatbot - General-purpose assistant with all tools
uv run python -m agents.chatbot.main

# PR Agent - Content strategy assistant
uv run python -m agents.pr_agent.main

# Security Researcher - AI security expert with RAG
uv run python -m agents.security_researcher.main

# Business Advisor - Monetization and strategy expert
uv run python -m agents.business_advisor.main

# Task Manager - Interactive task management
uv run python -m agents.task_manager.main

# REST API Server - HTTP access to agents
uv run python -m agents.api

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

**2. Configuration** (`config/`)
- `mcp_server/` - Exposes tools via Model Context Protocol
- Handles authentication and tool execution
- Can run locally (stdio) or remotely (HTTP/SSE)

**3. Shared Utilities** (`shared/`)
- Common code reusable across agents
- Remote MCP client implementation
- OAuth helpers and utilities

**4. Packages** (`packages/`)
- `agent-framework/` - Shared library with MCP tools, base agent classes, and security utilities
- `chasm/` - Voice interface library (Deepgram STT + Cartesia TTS) - optional dependency

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

### Chatbot
General-purpose AI assistant with access to all 29 MCP tools:
- Web content analysis and research
- Persistent memory across conversations
- RAG document search (requires PostgreSQL + OpenAI)
- Email management via FastMail
- Slack notifications
- Multi-domain task support

**Run:** `uv run python -m agents.chatbot.main` | **[Documentation](agents/chatbot/README.md)**

### PR Agent
Content strategy assistant that helps with:
- Blog post analysis and optimization
- Social media strategy and engagement
- SEO recommendations
- Brand voice consistency

**Run:** `uv run python -m agents.pr_agent.main` | **[Documentation](agents/pr_agent/README.md)**

### Security Researcher
AI/ML security expert with RAG-backed knowledge base:
- Security research questions and vulnerability analysis
- Blog post fact-checking for technical accuracy
- Threat modeling and security reviews
- Research paper search and synthesis
- Requires PostgreSQL + OpenAI for RAG functionality

**Run:** `uv run python -m agents.security_researcher.main` | **[Documentation](agents/security_researcher/README.md)**

### Business Advisor
Business strategy and monetization advisor:
- Analyze GitHub repos and websites for opportunities
- Generate business ideas with honest risk assessments
- Develop comprehensive business plans
- Market research and competitive analysis
- Optional GitHub MCP integration

**Run:** `uv run python -m agents.business_advisor.main` | **[Documentation](agents/business_advisor/README.md)**

### Task Manager
Intelligent task management assistant:
- Reschedule overdue tasks evenly across calendar
- Pre-research upcoming tasks with context
- Prioritize based on urgency and dependencies
- Connect to remote task management server (requires remote MCP)

**Run:** `uv run python -m agents.task_manager.main` | **[Documentation](agents/task_manager/README.md)**

### REST API Server
HTTP/REST interface for accessing agents via API:
- Stateless single-shot requests
- Stateful multi-turn sessions with conversation history
- Access to all 5 interactive agents (chatbot, pr, security, business, tasks)
- Automatic session management with TTL
- Token usage tracking per request

**Run:** `uv run python -m agents.api` | **[Documentation](agents/api/README.md)**

### Task Notifier
Lightweight notification script (not a full interactive agent):
- Sends Slack updates about open tasks
- Categorizes overdue, due today, and upcoming
- Can be run via cron for automated notifications
- Requires remote MCP for task data

**Run:** `uv run python -m agents.notifier.main` | **[Documentation](agents/notifier/README.md)**

See individual agent directories for detailed documentation and usage examples.

## MCP Tools

The MCP server exposes **29 tools** across 8 categories to agents:

### Web Analysis (2 tools)
- `fetch_web_content` - Fetch and read web content as clean markdown for analysis
- `analyze_website` - Analyze website for SEO, tone, and engagement metrics

### Memory (6 tools)
- `save_memory` - Save information with key/value/category/tags/importance (1-10 scale)
- `get_memories` - Retrieve memories with filtering by category/tags/importance
- `search_memories` - Search memories by keyword
- `delete_memory` - Delete a memory by key
- `get_memory_stats` - Get memory system statistics (total, categories, avg importance)
- `configure_memory_store` - Configure memory backend (file or database)

Memory persists across conversations (default: `memories/memories.json`, optional: PostgreSQL).

### RAG Document Search (6 tools)
*Requires PostgreSQL database and OpenAI API key for embeddings*

- `add_document` - Add document to knowledge base for semantic search
- `search_documents` - Search documents by query with similarity threshold
- `get_document` - Retrieve full document by ID
- `list_documents` - List all documents in knowledge base
- `delete_document` - Delete document by ID
- `get_rag_stats` - Get RAG system statistics (total docs, chunks, DB size)

### Email Management - FastMail (8 tools)
*Requires FastMail API token and account ID*

- `list_mailboxes` - List all mailboxes
- `get_emails` - Get emails from a mailbox with limit
- `get_email` - Get single email by ID
- `search_emails` - Search emails by query
- `send_email` - Send an email with to/cc/bcc/subject/body
- `move_email` - Move email to different mailbox
- `update_email_flags` - Update email flags (seen, flagged)
- `delete_email` - Delete an email permanently

### Communication (1 tool)
- `send_slack_message` - Send Slack notification via webhook

### Social Media (1 tool)
- `get_social_media_stats` - Get Twitter/LinkedIn stats (currently mock data, ready for OAuth integration)

### Content Suggestions (1 tool)
- `suggest_content_topics` - Generate content topic ideas (currently mock data)

**Total: 29 tools** available to agents via MCP. See [GUIDES.md](GUIDES.md) for detailed usage guides and [agent-framework documentation](packages/agent-framework/) for technical details.

## Project Structure

```
agents/
├── agents/              # Agent implementations
│   ├── chatbot/         # General-purpose assistant with all tools
│   ├── pr_agent/        # PR and content strategy assistant
│   ├── security_researcher/  # AI security research expert
│   ├── business_advisor/     # Business strategy and monetization
│   ├── task_manager/    # Interactive task management
│   ├── api/             # REST API server for agent access
│   └── notifier/        # Slack notification script
├── bin/                 # Executable scripts
│   ├── run-agent        # Main agent entry point
│   ├── run-voice-agent  # Voice-enabled agent entry
│   └── slack-adapter    # Slack integration adapter
├── config/              # Server configuration
│   └── mcp_server/      # Shared MCP server and tools
│       ├── server.py        # MCP server (stdio transport)
│       ├── server_http.py   # MCP server (HTTP/SSE transport)
│       ├── auth/            # OAuth handler and token storage
│       └── config.py        # Server configuration
├── docs/                # Documentation
│   ├── TESTING.md       # Testing and debugging guide
│   ├── VOICE_AGENTS.md  # Voice interface documentation
│   └── development/     # Development documentation
├── packages/            # Internal libraries (monorepo)
│   ├── agent-framework/ # Base agent classes, MCP client, and tools
│   │   ├── agent_framework/
│   │   │   ├── tools/   # MCP tools (web, social, memory, RAG, Slack)
│   │   │   ├── security/  # SSRF protection
│   │   │   ├── core/    # Agent base class
│   │   │   └── server.py  # MCP server base classes
│   │   └── tests/       # Framework tests
│   └── chasm/           # Voice interface library
│       └── src/chasm/   # Deepgram + Cartesia voice pipeline
├── shared/              # Common utilities
├── scripts/             # Utility scripts
│   ├── oauth/           # OAuth setup scripts
│   ├── mcp/             # MCP server management
│   └── testing/         # Test scripts
├── tests/               # Test suite
│   ├── integration/     # Integration tests
│   └── unit/            # Unit tests
├── .data/               # Runtime data (logs, memories, tokens)
├── CLAUDE.md            # Project instructions for Claude Code
├── GUIDES.md            # Feature guides (hot reload, memory, remote MCP)
└── README.md            # This file
```

## Development Workflow

### Hot Reload - Edit Tools Without Restarting

1. Start agent: `uv run python -m agents.pr_agent.main`
2. Edit tool code in `packages/agent-framework/agent_framework/tools/*.py`
3. Save changes
4. Next tool call automatically picks up changes
5. Type `reload` to force reconnection if needed

The agent reconnects to MCP server for each tool call instead of maintaining a persistent connection. This enables editing tools while the agent is running without losing conversation context.

### Adding a New Tool

1. Create implementation in `packages/agent-framework/agent_framework/tools/your_tool.py`:
```python
async def your_tool(param: str) -> dict[str, Any]:
    # Implementation
    return {"result": "data"}
```

2. Export from `packages/agent-framework/agent_framework/tools/__init__.py`:
```python
from .your_tool import your_tool

__all__ = [..., "your_tool"]
```

3. Register in `config/mcp_server/server.py`:
   - Import the tool from `agent_framework.tools`
   - Register with `server.register_tool()` in `setup_custom_tools()`
   - Tool automatically available to all agents that use this MCP server

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
- 7 agents with specialized capabilities
- 29 MCP tools (web, memory, RAG, email, communication)
- Real web scraping and content analysis
- RAG document search with semantic similarity
- FastMail email integration
- Persistent memory across conversations (file or database backend)
- Hot reload for tool development
- OAuth infrastructure (ready for production integration)
- Token usage tracking
- Remote MCP support for distributed deployments
- REST API server for HTTP access to agents

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
- **[docs/TESTING.md](docs/TESTING.md)** - Testing and debugging guide (memory tools, logs, common issues)
- **[docs/VOICE_AGENTS.md](docs/VOICE_AGENTS.md)** - Voice-enabled agents with chasm audio pipeline
- **[GUIDES.md](GUIDES.md)** - Feature guides (memory system, OAuth, deployment, voice interface)
- **[REMOTE_MCP.md](REMOTE_MCP.md)** - Remote MCP server setup and configuration
- **[HOT_RELOAD.md](HOT_RELOAD.md)** - Hot reload development workflow
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
uv run python -m config.mcp_server.server

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
- **agent-framework** - Base agent class and MCP client (local package)
- **chasm** - Voice interface library (local package, optional)
- **mcp** - Model Context Protocol SDK
- **httpx** - Async HTTP client
- **authlib** - OAuth 2.0 implementation
- **cryptography** - Token encryption (Fernet)
- **pydantic** - Data validation and settings
- **python-dotenv** - Environment management

### Optional Dependencies

- **voice** - Voice interface support via `chasm` (requires PortAudio system library)
  - Install with: `uv sync --group voice`
  - System requirements: `sudo apt-get install portaudio19-dev` (Ubuntu/Debian)

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
