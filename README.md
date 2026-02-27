# Multi-Agent System

[![Tests](https://github.com/brooksmcmillin/agents/workflows/Tests/badge.svg)](https://github.com/brooksmcmillin/agents/actions/workflows/tests.yml)
[![Integration](https://github.com/brooksmcmillin/agents/workflows/Integration%20Tests/badge.svg)](https://github.com/brooksmcmillin/agents/actions/workflows/integration.yml)
[![Deploy](https://github.com/brooksmcmillin/agents/workflows/Deploy/badge.svg)](https://github.com/brooksmcmillin/agents/actions/workflows/deploy.yml)

A multi-agent system built with Claude (Anthropic SDK) and Model Context Protocol (MCP). This repository supports multiple specialized agents that share common infrastructure for content analysis, task management, and persistent memory.

## Overview

This project demonstrates production-ready patterns for building LLM-powered agents with external tool integrations. It includes:

- **Multiple Agents** - 8 interactive CLI agents (chatbot, PR, security, business, tasks, code analysis, events, red team) and 6 standalone services (code reviewer, email intake, notifier, orchestrator, PR shepherd, task queue)
- **Web UI** - Modern React interface for chatting with agents via persistent conversations
- **Shared MCP Tools** - 53 tools including web analysis, memory, RAG document search, email management, HTTP client, filesystem, Claude Code, and communication
- **Hot Reload** - Edit tools without restarting agents
- **OAuth Infrastructure** - Ready for real API integration
- **Remote MCP Support** - Deploy tools separately from agents

## Quick Start

### Prerequisites

- Python 3.12 or higher
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
uv run bin/run-agent chatbot

# PR Agent - Content strategy assistant
uv run bin/run-agent pr

# Security Researcher - AI security expert with RAG
uv run bin/run-agent security

# Business Advisor - Monetization and strategy expert
uv run bin/run-agent business

# Task Manager - Interactive task management
uv run bin/run-agent tasks

# REST API Server - HTTP access to agents
uv run python -m api

# Web UI - Modern React interface for agents
# (requires npm and built frontend)
cd webui/frontend && npm install && npm run build
cd ../.. && uv run python -m api
# Visit http://localhost:8080

# Notifier - Send Slack notifications about tasks
uv run python -m agents.notifier.main

# MCP server standalone
uv run python -m mcp_server.server
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

### Interactive CLI Agents

Run via `uv run bin/run-agent <name>`. These are registered in `shared/registry.py` and accessible through the REST API and Web UI.

| Agent | Run As | Description | Docs |
|-------|--------|-------------|------|
| **Chatbot** | `chatbot` | General-purpose assistant with all 53 MCP tools | [docs](agents/chatbot/README.md) |
| **PR Agent** | `pr` | Content strategy, SEO, social media, Claude Code editing | [docs](agents/pr_agent/README.md) |
| **Security Researcher** | `security` | AI/ML security research with RAG knowledge base | [docs](agents/security_researcher/README.md) |
| **Business Advisor** | `business` | Monetization strategy, market analysis, GitHub analysis | [docs](agents/business_advisor/README.md) |
| **Task Manager** | `tasks` | Task management via remote MCP server | [docs](agents/task_manager/README.md) |
| **Code Analysis** | `code-analysis` | Repository review for security, logic, performance | [docs](agents/code_analysis/README.md) |
| **Events** | `events` | Local events discovery with preference learning | [docs](agents/events/README.md) |
| **Red Team** | `red-team` | Authorized penetration testing via HTTP tools | [docs](agents/red_team/README.md) |

### Standalone Services

Run directly — these are not in the agent registry and don't use `bin/run-agent`.

| Service | Invocation | Description | Docs |
|---------|-----------|-------------|------|
| **Code Reviewer** | `uv run python -m agents.code_reviewer.main <path>` | Batch review with 5 parallel agents, email reports | [docs](agents/code_reviewer/README.md) |
| **Email Intake** | `uv run python -m agents.email_intake.main` | Monitors inbox, routes tasks to agents | [docs](agents/email_intake/README.md) |
| **Notifier** | `uv run python -m agents.notifier.main` | Slack notifications about open tasks | [docs](agents/notifier/README.md) |
| **Orchestrator** | `uv run python -m agents.orchestrator.main "task"` | Task decomposition and Claude Code workers | [docs](agents/orchestrator/README.md) |
| **PR Shepherd** | `PRShepherd(config).run()` | Polls PRs, fixes CI, auto-merges | [docs](agents/pr_shepherd/README.md) |
| **Task Queue** | `TaskQueueRunner(config).run()` | Batch task triage and orchestrator dispatch | [docs](agents/task_queue/README.md) |

### REST API Server

HTTP/REST interface for accessing all 8 interactive agents:
- Stateless single-shot requests and stateful multi-turn sessions
- Automatic session management with TTL
- Token usage tracking per request

**Run:** `uv run python -m api` | **[Documentation](api/README.md)**

## Web UI

A modern React web interface for interacting with agents via persistent conversations.

**Features:**
- Choose from 8 interactive agents (chatbot, PR, tasks, security, business, code analysis, events, red team)
- Database-backed conversations that survive server restarts
- Create, rename, delete, and switch between conversations
- Real-time chat with token usage tracking
- Dark mode support
- Responsive design for desktop and mobile

**Setup:**
```bash
# Install Node.js dependencies
cd webui/frontend
npm install

# Development mode (hot reload)
# Terminal 1: Backend
uv run python -m api

# Terminal 2: Frontend
npm run dev
# Visit http://localhost:5173

# Production build
npm run build
uv run python -m api
# Visit http://localhost:8080
```

**Requirements:**
- Node.js 18+
- PostgreSQL database (set `DATABASE_URL` environment variable)

See [webui/README.md](webui/README.md) for detailed documentation.

## MCP Tools

The MCP server exposes **53 tools** across 14 categories to agents:

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

### Email Management - FastMail (9 tools)
*Requires FastMail API token and account ID*

- `list_mailboxes` - List all mailboxes
- `get_emails` - Get emails from a mailbox with limit
- `get_email` - Get single email by ID
- `search_emails` - Search emails by query
- `send_email` - Send an email with to/cc/bcc/subject/body
- `send_agent_report` - Send report/notification from agent to admin
- `move_email` - Move email to different mailbox
- `update_email_flags` - Update email flags (seen, flagged)
- `delete_email` - Delete an email permanently

### Communication (1 tool)
- `send_slack_message` - Send Slack notification via webhook

### Social Media (1 tool)
- `get_social_media_stats` - Get Twitter/LinkedIn stats (currently mock data, ready for OAuth integration)

### Content Suggestions (1 tool)
- `suggest_content_topics` - Generate content topic ideas (currently mock data)

**Plus:** HTTP Client (7 tools), Markdown Files (4 tools), Filesystem (6 tools), Claude Code (5 tools), Twilio SMS (5 tools). **Total: 53 tools** available to agents via MCP. See [docs/tools.md](docs/tools.md) for complete reference and [GUIDES.md](docs/GUIDES.md) for usage guides.

## Project Structure

```
agents/                    # Agent implementations
├── chatbot/               # General-purpose assistant (interactive)
├── pr_agent/              # Content strategy assistant (interactive)
├── security_researcher/   # AI security research (interactive)
├── business_advisor/      # Business strategy (interactive)
├── task_manager/          # Task management (interactive)
├── code_analysis/         # Repository analysis (interactive)
├── events/                # Local events discovery (interactive)
├── red_team/              # Penetration testing (interactive)
├── code_reviewer/         # Batch code review (standalone)
├── email_intake/          # Email inbox monitor (standalone)
├── notifier/              # Slack notifications (standalone)
├── orchestrator/          # Task decomposition + workers (standalone)
├── pr_shepherd/           # CI fix + auto-merge daemon (standalone)
└── task_queue/            # Batch task triage pipeline (standalone)
api/                       # REST API server (FastAPI)
webui/                     # React frontend
mcp_server/                # Shared MCP server and tools
infra/                     # Infrastructure configs (Grafana, Loki, Promtail)
docs/                      # Documentation
packages/                  # Internal libraries (monorepo)
├── agent-framework/       # Base agent classes, MCP client, and tools
└── chasm/                 # Voice interface library
shared/                    # Common utilities
bin/                       # Executable scripts
tests/                     # Test suite
scripts/                   # Utility scripts
```

## Development Workflow

### Hot Reload - Edit Tools Without Restarting

1. Start agent: `uv run bin/run-agent pr`
2. Edit tool code in `packages/agent-framework/agent_framework/tools/*.py`
3. Save changes
4. Next tool call automatically picks up changes
5. Type `reload` to force reconnection if needed

The agent reconnects to MCP server for each tool call instead of maintaining a persistent connection. This enables editing tools while the agent is running without losing conversation context.

### Adding a New Tool

See [docs/tools.md](docs/tools.md#adding-a-new-tool) for the complete guide on creating and registering MCP tools.

### Adding a New Agent

1. Create agent directory: `mkdir -p agents/your_agent`
2. Create `main.py` extending `Agent` class from `agent-framework`
3. Create `prompts.py` with system prompt and greeting
4. Create `__init__.py` with version info
5. Register in `bin/run-agent` and run: `uv run bin/run-agent your-agent`

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
- Full agentic loop with Claude Sonnet 4.6
- 8 interactive agents + 6 standalone services
- 53 MCP tools (web, memory, RAG, email, HTTP client, filesystem, Claude Code, communication)
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
- **[GUIDES.md](docs/GUIDES.md)** - Feature guides (memory system, OAuth, deployment, voice interface)
- **[REMOTE_MCP.md](docs/REMOTE_MCP.md)** - Remote MCP server setup and configuration
- **[HOT_RELOAD.md](docs/HOT_RELOAD.md)** - Hot reload development workflow
- **Agent READMEs** - See `agents/*/README.md` for agent-specific docs
- **Code Comments** - Extensive inline documentation

## Troubleshooting

### Agent Issues

```bash
# Check logs
tail -f pr_agent.log

# Enable debug logging
# In .env: LOG_LEVEL=DEBUG

# Test MCP server starts
uv run python -m mcp_server.server
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

- **Python 3.12+**
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

## CI/CD

Automated testing and deployment with GitHub Actions.

### Workflows

**Tests (`tests.yml`)** - Runs on every push and PR
- ✅ Backend tests (pytest with PostgreSQL)
- ✅ Frontend tests (vitest)
- ✅ Linting (ruff, eslint)
- ✅ Type checking (TypeScript)
- ✅ Build verification

**Integration (`integration.yml`)** - Full integration tests
- ✅ Database integration tests
- ✅ API endpoint testing
- 🚧 E2E tests (placeholder for Playwright)

**Deploy (`deploy.yml`)** - Build and publish on tags
- ✅ Production frontend build
- ✅ Artifact upload
- ✅ GitHub releases

### Running Checks Locally

```bash
# Run all CI checks locally
.github/workflows/test-local.sh

# Or run individually:
uv run pytest api/test_server.py -v --cov
cd webui/frontend && npm test -- --run
uv run ruff check . && uv run ruff format --check .
```

See [.github/workflows/README.md](.github/workflows/README.md) for detailed documentation.

## Contributing

To extend this project:
1. Follow existing code patterns
2. Add type hints to all functions
3. Write docstrings (Google style)
4. **Run tests locally** before pushing: `.github/workflows/test-local.sh`
5. Ensure CI passes on your PR
6. Update documentation

## License

This is a demonstration project for educational purposes.

---

**Built with Claude Sonnet 4.6 and Model Context Protocol**
