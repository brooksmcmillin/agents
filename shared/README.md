# Shared Utilities

This directory contains common code that can be reused across all agents.

## Purpose

As you build more agents, you'll likely find common patterns and utilities that multiple agents need. Extract those here to avoid duplication.

## What to Put Here

Examples of code that belongs in `shared/`:
- Custom base agent classes that extend `agent-framework`'s `Agent`
- Common prompt templates or prompt utilities
- Shared configuration helpers
- Utility functions used by multiple agents
- Custom MCP client wrappers (if needed)
- Shared data models or types

## What NOT to Put Here

- Agent-specific logic (belongs in `agents/*/`)
- MCP tools (belongs in `mcp_server/tools/`)
- Configuration specific to one agent

## Current Contents

### RemoteMCPClient

Client for connecting to remote MCP servers via HTTP/SSE transport.

**Usage:**
```python
from shared import RemoteMCPClient

# Connect to remote MCP server
client = RemoteMCPClient("http://localhost:8000")

async with client:
    # List available tools
    tools = await client.list_tools()

    # Call a tool
    result = await client.call_tool(
        "analyze_website",
        {"url": "https://example.com", "analysis_type": "seo"}
    )
```

**See:** [REMOTE_MCP.md](../REMOTE_MCP.md) for full documentation on remote MCP setup.
