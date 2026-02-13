# Remote MCP Setup Guide

This guide explains how to set up and use remote MCP (Model Context Protocol) servers, enabling multiple agents to share tools hosted on a central server via HTTP/SSE transport.

## What is Remote MCP?

**Local MCP** (default): Agent connects to MCP server via stdio (same machine)
```
Agent → Local MCP Server (stdio) → Tools
```

**Remote MCP**: Agent connects to MCP server over HTTP/SSE (network)
```
Agent → Remote MCP Server (HTTP/SSE) → Tools
                ↓
          OAuth Authentication
```

## When to Use Remote MCP

### Use Remote MCP When:

✅ **Multiple agents need the same tools**
- Share one MCP server across PR agent, task manager, chatbot
- Avoid duplicating tool infrastructure

✅ **Tools require centralized resources**
- Database connections (single connection pool)
- API keys and secrets (managed in one location)
- Shared state (caches, rate limiters)

✅ **Scaling agent deployment**
- Run agents on different machines
- Distribute tool execution load
- Horizontal scaling of agents

✅ **Enhanced security**
- Tools run in isolated environment
- Secrets never leave MCP server
- OAuth authentication for tool access

### Use Local MCP When:

❌ **Single agent on one machine**
- Simpler setup, no network overhead

❌ **File system operations**
- Local MCP has faster file access

❌ **Development and testing**
- Easier debugging with stdio transport

## Architecture Patterns

### Pattern 1: Hub and Spoke

Single remote MCP server serves multiple agents:

```
┌────────────┐
│  Agent 1   │────┐
│ (PR Agent) │    │
└────────────┘    │
                  │
┌────────────┐    ├───> Remote MCP Server ──┬──> External APIs
│  Agent 2   │────┤          (OAuth)        ├──> Databases
│ (Chatbot)  │    │                         └──> Shared Tools
└────────────┘    │
                  │
┌────────────┐    │
│  Agent 3   │────┘
│ (Security) │
└────────────┘
```

**Benefits**:
- Centralized tool management
- Shared resource pooling
- Consistent authentication

**Use case**: Small team with multiple agents sharing tools

---

### Pattern 2: Specialized Servers

Different remote MCP servers for different tool categories:

```
┌────────┐
│ Agent  │──┬──> Auth MCP Server ──> User management, OAuth
│        │  │
│        │  ├──> Data MCP Server ──> Database, storage tools
│        │  │
│        │  └──> API MCP Server  ──> External APIs, webhooks
└────────┘
```

**Benefits**:
- Isolated failure domains
- Scale independently
- Security boundaries per tool category

**Use case**: Large deployment with diverse tool requirements

---

### Pattern 3: Hybrid (Local + Remote)

Local MCP for fast tools, remote MCP for secure/shared tools:

```
┌────────┐
│ Agent  │──┬──> Local MCP Server (stdio) ──> File tools, CLI
│        │  │
│        │  └──> Remote MCP Server (HTTP) ──> API keys, secrets, shared DB
└────────┘
```

**Benefits**:
- Performance where needed (local)
- Security where needed (remote)
- Best of both worlds

**Use case**: Production agents needing both speed and security

---

## Setup Guide

### Server Setup

#### Option 1: Using agent-framework MCP Server

```bash
# 1. Create server configuration
# File: config/mcp_server/server_http.py

from agent_framework.server import create_mcp_server
from agent_framework.tools import (
    fetch_web_content,
    save_memory,
    get_memories,
    send_slack_message,
)

# Create server
server = create_mcp_server("my-tools")

# Register tools
server.register_tool(
    name="fetch_web_content",
    description="Fetch web content as markdown",
    handler=fetch_web_content,
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_length": {"type": "integer", "default": 50000},
        },
        "required": ["url"],
    },
)

# Register additional tools...
# (memory, slack, etc.)

# 2. Run with HTTP transport
# Start server on port 8080
uvicorn config.mcp_server.server_http:server --host 0.0.0.0 --port 8080
```

#### Option 2: Using Existing MCP Server

If you have an existing MCP server (like the task management server):

```bash
# Deploy your MCP server
cd your-mcp-server/
python -m server --host 0.0.0.0 --port 8000

# Note the URL for agent configuration
# Example: https://mcp.brooksmcmillin.com/mcp
```

---

### Client Setup (Agent Side)

#### Environment Configuration

```bash
# .env file
ANTHROPIC_API_KEY=sk-ant-...

# Remote MCP Server URL
MCP_SERVER_URL=https://mcp.example.com/mcp

# Optional: Authentication token (if server requires it)
MCP_AUTH_TOKEN=your_token_here

# Optional: OAuth device flow (alternative to token)
# Leave MCP_AUTH_TOKEN empty to trigger device flow
```

#### Agent Configuration

Agents can connect to remote MCP servers in two ways:

**Method 1: Automatic (via environment variable)**

Task manager and notifier agents automatically use `MCP_SERVER_URL`:

```python
# agents/task_manager/main.py (already configured)
from shared import DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL

TaskManagerAgent = create_simple_agent(
    name="TaskManagerAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=TASK_MANAGER_TOOLS,
    mcp_urls=[os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)],
    mcp_client_config={"prefer_device_flow": True},
)
```

**Method 2: Manual configuration**

For custom agents:

```python
from agent_framework import Agent

class MyAgent(Agent):
    def __init__(self):
        super().__init__(
            mcp_urls=["https://mcp.example.com/mcp"],
            mcp_client_config={
                "prefer_device_flow": True,  # Use OAuth device flow
                # OR
                "auth_token": os.getenv("MCP_AUTH_TOKEN"),  # Use bearer token
            }
        )
```

---

## Authentication

Remote MCP servers require authentication to protect tools.

### Option 1: OAuth Device Flow (Recommended)

**How it works:**
1. Agent requests device authorization from server
2. Server returns URL and user code
3. User opens URL and enters code
4. Agent polls server until user authorizes
5. Agent receives access token
6. Token automatically refreshed when expired

**Configuration:**

```python
# Agent code
mcp_client_config={"prefer_device_flow": True}
```

**User experience:**

```bash
$ uv run python -m agents.task_manager.main

🔐 OAuth Device Authorization Required

Please visit: https://mcp.example.com/device
Enter code: ABCD-1234

Waiting for authorization...
✓ Authorization successful!

# Agent now has access token and can call tools
```

**Pros**:
- No manual token management
- Automatic refresh
- Works across devices
- User-friendly

**Cons**:
- Requires interactive authorization
- Not suitable for fully automated scripts

---

### Option 2: Bearer Token

**How it works:**
1. Obtain token from MCP server admin
2. Set MCP_AUTH_TOKEN environment variable
3. Agent includes token in all requests

**Configuration:**

```bash
# .env
MCP_AUTH_TOKEN=your_long_token_here
```

```python
# Agent code
mcp_client_config={"auth_token": os.getenv("MCP_AUTH_TOKEN")}
```

**Obtaining a token:**

```bash
# Example script (server-specific)
uv run python scripts/mcp_auth.py

# Output
Your MCP auth token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
Add to .env: MCP_AUTH_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Pros**:
- Works for automated scripts
- No interactive flow
- Simple setup

**Cons**:
- Manual token rotation
- Token could leak if not secured
- No automatic refresh

---

## Running Agents with Remote MCP

### Task Manager Agent

Connects to remote MCP server for task management tools:

```bash
# Default remote MCP URL
uv run python -m agents.task_manager.main

# Custom remote MCP URL
MCP_SERVER_URL=https://your-mcp.com/mcp uv run python -m agents.task_manager.main

# With authentication token
MCP_AUTH_TOKEN=your_token uv run python -m agents.task_manager.main

# With OAuth device flow (default)
# Agent will prompt for authorization
uv run python -m agents.task_manager.main
```

### Task Notifier

Connects to remote MCP for retrieving overdue tasks and sending Slack notifications:

```bash
# Uses MCP_SERVER_URL from environment
MCP_SERVER_URL=https://mcp.example.com/mcp uv run python -m agents.notifier.main
```

### Custom Agent with Remote MCP

```python
# agents/my_agent/main.py
import asyncio
import os
from agent_framework import Agent

class MyRemoteAgent(Agent):
    def __init__(self):
        super().__init__(
            mcp_urls=[os.getenv("MCP_SERVER_URL", "https://mcp.example.com/mcp")],
            mcp_client_config={"prefer_device_flow": True}
        )

    def get_system_prompt(self) -> str:
        return "You are a helpful assistant with remote tool access."

    def get_greeting(self) -> str:
        return "Hello! I can access remote MCP tools."

async def main():
    agent = MyRemoteAgent()
    await agent.start()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Configuration Reference

### MCP Server Configuration

```python
# Server environment variables
HOST="0.0.0.0"
PORT=8080

# OAuth configuration (if using device flow)
OAUTH_CLIENT_ID="your_client_id"
OAUTH_CLIENT_SECRET="your_client_secret"
OAUTH_AUTHORIZATION_URL="https://auth.example.com/authorize"
OAUTH_TOKEN_URL="https://auth.example.com/token"
OAUTH_DEVICE_AUTHORIZATION_URL="https://auth.example.com/device"

# Token signing (if using bearer tokens)
TOKEN_SECRET_KEY="your_secret_key"  # Keep secret!
```

### Agent (Client) Configuration

```bash
# .env file

# Remote MCP server URL (required)
MCP_SERVER_URL=https://mcp.example.com/mcp

# Authentication option 1: Bearer token
MCP_AUTH_TOKEN=your_token_here

# Authentication option 2: OAuth device flow
# Leave MCP_AUTH_TOKEN empty, agent will use device flow
```

### agent-framework Configuration

```python
# In agent code
mcp_client_config = {
    # Authentication
    "prefer_device_flow": True,  # Use OAuth device flow
    "auth_token": "...",         # Or use bearer token

    # Connection
    "timeout": 30.0,             # Request timeout in seconds
    "max_retries": 3,            # Connection retry attempts

    # OAuth token storage
    "token_storage_dir": "~/.mcp_tokens",  # Where to save tokens
}
```

---

## Troubleshooting

### Connection Refused

```bash
# Test server connectivity
curl https://mcp.example.com/mcp/health

# Check if server is running
# Check firewall rules
# Verify URL in MCP_SERVER_URL
```

### Authentication Failed

```bash
# Device flow: Check URL and user code
# Bearer token: Verify MCP_AUTH_TOKEN is set and valid

# Test authentication
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  https://mcp.example.com/mcp/tools

# Expected: List of tools
# If 401/403: Token is invalid or expired
```

### Tools Not Available

```bash
# List available tools
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  https://mcp.example.com/mcp/tools | jq '.tools[].name'

# If empty: Server may not have registered tools
# Check server logs for errors
```

### Token Expired

Device flow tokens are automatically refreshed. For bearer tokens:

```bash
# Obtain new token
uv run python scripts/mcp_auth.py

# Update .env
MCP_AUTH_TOKEN=new_token_here

# Restart agent
```

### Network Timeouts

```python
# Increase timeout in agent configuration
mcp_client_config={
    "timeout": 60.0,  # 60 seconds instead of 30
    "max_retries": 5,  # More retry attempts
}
```

### CORS Errors (Browser-based clients)

```python
# Server side: Add CORS middleware
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## Security Best Practices

### Server Security

1. **Use HTTPS in production**
   ```bash
   # Don't use http:// for remote MCP
   # Use https:// with valid TLS certificate
   ```

2. **Implement authentication**
   ```python
   # Always require OAuth or bearer token
   # Never expose unauthenticated MCP server to internet
   ```

3. **Rate limiting**
   ```python
   # Add rate limiting per client
   # Prevent abuse and DoS
   ```

4. **Audit logging**
   ```python
   # Log all tool calls with:
   # - User/client identifier
   # - Tool name and arguments
   # - Timestamp
   # - Result (success/failure)
   ```

5. **Network security**
   ```bash
   # Use firewall to restrict access
   # Only allow trusted IP ranges
   # Consider VPN for additional security
   ```

### Client Security

1. **Protect auth tokens**
   ```bash
   # Never commit .env with MCP_AUTH_TOKEN
   # Use environment variables, not hardcoded
   # Rotate tokens regularly
   ```

2. **Token storage**
   ```bash
   # OAuth tokens stored in ~/.mcp_tokens/
   # Ensure proper file permissions (600)
   chmod 600 ~/.mcp_tokens/*
   ```

3. **Validate server certificates**
   ```python
   # Don't disable SSL verification in production
   # Ensure HTTPS connections validate certificates
   ```

---

## Performance Considerations

### Network Latency

Remote MCP adds network latency to tool calls:

```
Local MCP:  1-10ms per tool call
Remote MCP: 50-500ms per tool call (depends on network)
```

**Mitigation**:
- Use local MCP for performance-critical tools
- Batch tool calls when possible
- Cache results when appropriate

### Connection Pooling

Remote MCP client reuses connections:

```python
# Agent maintains persistent connection
async with RemoteMCPClient(url) as client:
    # Multiple calls use same connection
    await client.call_tool("tool1", {})
    await client.call_tool("tool2", {})
    # Connection closed on exit
```

### Concurrent Tool Calls

```python
# Agents can make concurrent tool calls
import asyncio

results = await asyncio.gather(
    client.call_tool("tool1", {}),
    client.call_tool("tool2", {}),
    client.call_tool("tool3", {}),
)
```

---

## Migration from Local to Remote MCP

### Step 1: Deploy Remote MCP Server

```bash
# Package your MCP server
# Deploy to production environment
# Configure OAuth or token authentication
# Test connectivity and authentication
```

### Step 2: Update Agent Configuration

```bash
# Add to .env
MCP_SERVER_URL=https://your-mcp.com/mcp

# Choose authentication method
# Option A: Device flow (no additional config)
# Option B: Bearer token
MCP_AUTH_TOKEN=your_token
```

### Step 3: Test Agent

```bash
# Test with new remote MCP
uv run python -m agents.your_agent.main

# Verify tools are available
# Run test conversations
# Check for errors
```

### Step 4: Monitor and Iterate

```bash
# Monitor server logs
tail -f /var/log/mcp-server.log

# Monitor agent logs
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log

# Check for authentication failures
# Monitor latency and performance
# Adjust timeouts if needed
```

---

## Examples

### Example 1: Shared Task Management Server

```bash
# Server (deployed at mcp.company.com)
# Exposes task management tools

# Agent 1: Task Manager (interactive)
MCP_SERVER_URL=https://mcp.company.com/mcp \
uv run python -m agents.task_manager.main

# Agent 2: Task Notifier (automated)
MCP_AUTH_TOKEN=automated_token \
MCP_SERVER_URL=https://mcp.company.com/mcp \
uv run python -m agents.notifier.main

# Both agents access same task database via remote MCP
```

### Example 2: Hybrid Local + Remote

```python
# Agent with both local and remote MCP
class HybridAgent(Agent):
    def __init__(self):
        super().__init__(
            # Local MCP for file operations (fast)
            mcp_stdio_command="python config/mcp_server/server.py",

            # Remote MCP for API keys (secure)
            mcp_urls=["https://secure-mcp.com/mcp"],
            mcp_client_config={"auth_token": os.getenv("MCP_AUTH_TOKEN")}
        )

# Agent gets tools from both local and remote MCP servers
```

### Example 3: Multi-Region Deployment

```bash
# US region agents
MCP_SERVER_URL=https://mcp-us.company.com/mcp

# EU region agents
MCP_SERVER_URL=https://mcp-eu.company.com/mcp

# Same tools, different regions for latency optimization
```

---

## Related Documentation

- [CLAUDE.md](CLAUDE.md) - Project overview and agent architecture
- [HOT_RELOAD.md](HOT_RELOAD.md) - Development workflow with hot reload
- [agent-framework/ARCHITECTURE.md](packages/agent-framework/ARCHITECTURE.md) - Technical deep dive
- [Task Manager Agent](agents/task_manager/README.md) - Example agent using remote MCP
- [Testing Guide](docs/TESTING.md) - Testing remote MCP connections
