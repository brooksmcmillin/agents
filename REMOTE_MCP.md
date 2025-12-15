# Remote MCP Server Setup

This guide explains how to use remote MCP servers with your agents, allowing tools to be hosted on a different machine or service.

## Overview

**Local (stdio) vs Remote (HTTP/SSE):**

```
LOCAL SETUP (current):
Agent → stdio → MCP Server (subprocess)

REMOTE SETUP:
Agent → HTTP/SSE → Remote MCP Server (different host/port)
```

## Why Use Remote MCP?

- **Scalability**: Multiple agents can share one MCP server
- **Resource isolation**: Run heavy tools on a dedicated server
- **Cloud deployment**: Host agents and tools separately
- **Multi-tenancy**: Different users/agents share tool infrastructure
- **Language flexibility**: MCP server can be in any language with HTTP

## Quick Start

### 1. Start Remote MCP Server

```bash
# Terminal 1: Start the HTTP/SSE server
uv run python -m mcp_server.server_http

# Server starts on http://localhost:8000
# SSE endpoint: http://localhost:8000/sse
# Health check: http://localhost:8000/health
```

### 2. Use Remote Client

```python
from shared.remote_mcp_client import RemoteMCPClient

# Connect to remote server
client = RemoteMCPClient("http://localhost:8000")

async with client:
    # List tools
    tools = await client.list_tools()

    # Call a tool
    result = await client.call_tool(
        "analyze_website",
        {"url": "https://example.com", "analysis_type": "seo"}
    )
```

### 3. Run Example

```bash
# Terminal 1: Start server
uv run python -m mcp_server.server_http

# Terminal 2: Run example client
uv run python agents/remote_example.py
```

## Integration with agent-framework

The `agent-framework` package currently only supports stdio transport. To use remote MCP:

### Option A: Custom Agent Implementation

Create a custom agent that uses `RemoteMCPClient` instead of the built-in client:

```python
# agents/my_remote_agent/main.py
import asyncio
from anthropic import AsyncAnthropic
from shared.remote_mcp_client import RemoteMCPClient
from dotenv import load_dotenv
import os

load_dotenv()


class RemoteAgent:
    """Agent that uses remote MCP server."""

    def __init__(self, mcp_url: str = "http://localhost:8000"):
        self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.mcp_url = mcp_url
        self.messages = []

    async def run(self):
        """Run the agent with remote MCP."""
        async with RemoteMCPClient(self.mcp_url) as mcp:
            # Get available tools
            tools = await mcp.list_tools()

            # Your agent loop here
            # Call Claude API with tools
            # Execute tool calls via mcp.call_tool()
            pass


async def main():
    agent = RemoteAgent("http://localhost:8000")
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
```

### Option B: Extend agent-framework (Advanced)

Fork or extend `agent-framework` to support remote transports. You could:

1. Add a `mcp_url` parameter to `Agent.__init__()`
2. Check if URL is provided, use `RemoteMCPClient` instead of `MCPClient`
3. Keep the same interface for tool calls

This would allow:

```python
class MyAgent(Agent):
    def __init__(self):
        # Use remote MCP instead of local
        super().__init__(mcp_url="http://localhost:8000")
```

## Production Deployment

### Server Configuration

1. **Environment Variables**:
   ```bash
   export MCP_SERVER_HOST=0.0.0.0
   export MCP_SERVER_PORT=8000
   export LOG_LEVEL=INFO
   ```

2. **Run with Systemd**:
   ```ini
   [Unit]
   Description=MCP Server
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/app
   ExecStart=/usr/local/bin/uv run python -m mcp_server.server_http
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

3. **Run with Docker**:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY . .
   RUN pip install uv && uv sync
   EXPOSE 8000
   CMD ["uv", "run", "python", "-m", "mcp_server.server_http"]
   ```

### Security Considerations

1. **Authentication**: Add API key validation
   ```python
   # In server_http.py
   async def auth_middleware(app, handler):
       async def middleware(request):
           api_key = request.headers.get("X-API-Key")
           if api_key != os.getenv("MCP_API_KEY"):
               return web.Response(status=401, text="Unauthorized")
           return await handler(request)
       return middleware

   app.middlewares.append(auth_middleware)
   ```

2. **HTTPS**: Use reverse proxy (nginx/caddy) for TLS
   ```nginx
   server {
       listen 443 ssl;
       server_name mcp.example.com;

       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
       }
   }
   ```

3. **Rate Limiting**: Prevent abuse
   ```python
   from aiohttp_ratelimit import setup as setup_ratelimit

   setup_ratelimit(app, max_requests=100, time_window=60)
   ```

## Cloud Hosting Options

### Railway/Render

```bash
# railway.toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uv run python -m mcp_server.server_http"

[[envVars]]
name = "PORT"
value = "8000"
```

### Fly.io

```toml
# fly.toml
app = "pr-agent-mcp"

[build]
  builder = "paketobuildpacks/builder:base"

[env]
  PORT = "8000"

[[services]]
  http_checks = []
  internal_port = 8000
  protocol = "tcp"
```

### AWS Lambda (with adapter)

Use Mangum to adapt aiohttp for Lambda:

```python
from mangum import Mangum
from mcp_server.server_http import create_app

app = create_app()
handler = Mangum(app)
```

## Monitoring

### Health Checks

```bash
# Check server status
curl http://localhost:8000/health

# Expected response:
{"status": "healthy", "service": "pr-agent-mcp"}
```

### Logging

The server logs all tool calls:

```
INFO - Calling tool: analyze_website with args: {'url': '...', 'analysis_type': 'seo'}
INFO - Tool analyze_website completed successfully
```

### Metrics (Optional)

Add Prometheus metrics:

```python
from prometheus_client import Counter, Histogram

tool_calls = Counter('mcp_tool_calls_total', 'Total tool calls', ['tool_name'])
tool_duration = Histogram('mcp_tool_duration_seconds', 'Tool execution time', ['tool_name'])
```

## Troubleshooting

### Connection Refused

```bash
# Check if server is running
curl http://localhost:8000/health

# Start server if not running
uv run python -m mcp_server.server_http
```

### CORS Issues

Server has CORS middleware enabled. If still having issues:

```python
# Update allowed origins in server_http.py
response.headers["Access-Control-Allow-Origin"] = "https://your-domain.com"
```

### Tool Execution Errors

Check server logs for detailed error messages. Common issues:
- Missing environment variables (API keys)
- Network timeouts for web scraping
- File permissions for memory/token storage

## Architecture Comparison

### Local (stdio)

**Pros:**
- Simple setup
- No network latency
- Automatic process management
- Hot reload support

**Cons:**
- Can't share tools between agents
- Same machine requirement
- Resource contention

### Remote (HTTP/SSE)

**Pros:**
- Scalable (multiple agents → one server)
- Language-agnostic
- Cloud-ready
- Resource isolation

**Cons:**
- Network latency
- More complex deployment
- Need server management
- Authentication required

## Next Steps

1. **Try the example**: Run `agents/remote_example.py`
2. **Deploy remotely**: Host on Railway/Render/Fly.io
3. **Add authentication**: Implement API key validation
4. **Monitor performance**: Add metrics and logging
5. **Extend agent-framework**: Submit PR to add native remote support

## Related Files

- `mcp_server/server_http.py` - Remote MCP server implementation
- `shared/remote_mcp_client.py` - Client for connecting to remote servers
- `agents/remote_example.py` - Example usage
- `mcp_server/server.py` - Original stdio server
