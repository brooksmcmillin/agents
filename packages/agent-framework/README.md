# Agent Framework

A production-ready framework for building LLM agents with the Model Context Protocol (MCP). Build powerful, tool-enabled agents with persistent memory, RAG (Retrieval-Augmented Generation), OAuth integration, and extensible architecture.

## Why This Framework?

- **Battle-tested**: Extracted from production agent implementations
- **MCP-native**: Built on the Model Context Protocol for clean tool separation
- **Batteries included**: Web scraping, memory storage, RAG with semantic search, Slack integration, OAuth handling
- **Type-safe**: Full typing with Pydantic validation throughout
- **Extensible**: Clean abstractions for building domain-specific agents
- **Multi-agent ready**: Route messages to multiple specialized agents via Slack

## Quick Install

```bash
# Using uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

**Requirements:** Python 3.11 or higher

## Quick Example

```python
from agent_framework import Agent

class MyAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You are a helpful assistant that can read web content and remember information."

# Run it
import asyncio
asyncio.run(MyAgent(mcp_server_path="server.py").start())
```

## Web Search Agent

Enable Claude's built-in web search for up-to-date information:

```python
from agent_framework import Agent

class WebSearchAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You are a research assistant with web search capabilities."

# Enable web search with optional configuration
agent = WebSearchAgent(
    mcp_server_path="server.py",
    enable_web_search=True,
    web_search_config={
        "max_uses": 5,  # Max searches per response (1-10)
        "allowed_domains": ["docs.python.org"],  # Optional: restrict to domains
        "blocked_domains": ["spam.com"],  # Optional: exclude domains
        "user_location": {  # Optional: for localized results
            "type": "approximate",
            "city": "San Francisco",
            "country": "US",
        },
    },
)

asyncio.run(agent.start())
```

## Core Features

**Agent System**
- Agentic conversation loop with CLI interface
- Local MCP client for stdio-based tool servers
- Remote MCP client for HTTPS-based servers with OAuth
- Claude's built-in web search capability
- Token usage tracking
- Automatic context management (trimming with memory injection)
- Automatic file logging to `~/.agents/logs/`

**Remote MCP & OAuth**
- Connect to remote MCP servers over HTTPS
- Full OAuth 2.0 with PKCE support
- Device Authorization Grant (RFC 8628) for headless environments
- Automatic OAuth discovery via .well-known endpoints
- Dynamic client registration
- Automatic token refresh
- Auto-reauthentication on 401/403 errors with seamless retry

**Storage & Memory**
- Persistent memory with categories, tags, and search
- File-based storage (default) or PostgreSQL database backend
- Encrypted OAuth token storage with auto-refresh

**RAG (Retrieval-Augmented Generation)**
- Semantic document search using vector embeddings
- PostgreSQL with pgvector for storage
- OpenAI embeddings (text-embedding-3-small)
- PDF file support with automatic text extraction
- Metadata filtering and categorization

**Multi-Agent Slack Integration**
- Route messages to multiple specialized agents
- Keyword-based, explicit, channel-based, or hybrid routing
- Per-agent conversation isolation
- Device flow OAuth notifications via Slack

**Built-in Tools**
- Web search (Claude's native web search)
- Web content reader (HTML to markdown)
- Slack webhooks integration
- Memory management (save, retrieve, search, delete, stats)
- RAG tools (add, search, get, delete, list documents)

**MCP Server Infrastructure**
- Simple tool registration
- Structured error handling
- JSON schema validation

## Documentation

- **[Getting Started](GETTING_STARTED.md)** - Installation, configuration, and first agent
- **[Architecture](ARCHITECTURE.md)** - Design decisions, extension patterns, and advanced topics

## Project Structure

```
agent_framework/
├── adapters/      # Integration adapters (Multi-Agent Slack)
├── core/          # Agent base class, local and remote MCP clients
├── oauth/         # OAuth 2.0 discovery, device flow, and token management
├── tools/         # Reusable tools (web, slack, memory, RAG)
├── storage/       # Memory, RAG, and token storage backends
├── server/        # MCP server infrastructure
└── utils/         # Errors, config, logging
```

## License

MIT
