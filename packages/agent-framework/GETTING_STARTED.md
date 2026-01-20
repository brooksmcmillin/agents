# Getting Started

This guide will walk you through installing the Agent Framework and building your first agent.

## Prerequisites

- Python 3.11 or higher
- An Anthropic API key ([get one here](https://console.anthropic.com/))
- **Optional:** PostgreSQL with pgvector extension (for RAG features)
- **Optional:** OpenAI API key (for RAG embeddings)

## Installation

### 1. Install the Framework

```bash
# Clone or navigate to the framework
cd agent-framework

# Using uv (recommended)
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .

# Or using pip
pip install -e .
```

### 2. Configure Environment

Create a `.env` file in your project root:

```bash
# Copy the example
cp .env.example .env
```

Edit `.env` and add your API key:

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Optional: For token encryption (generate with the command below)
# TOKEN_ENCRYPTION_KEY=...

# Optional: For Slack webhook integration
# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Optional: For Multi-Agent Slack Bot (Socket Mode)
# SLACK_BOT_TOKEN=xoxb-...
# SLACK_APP_TOKEN=xapp-...

# Optional: For RAG (semantic search)
# DATABASE_URL=postgresql://user:password@localhost:5432/dbname
# OPENAI_API_KEY=sk-...

# Optional: For PostgreSQL-backed memory storage
# MEMORY_BACKEND=database
# DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

Generate an encryption key if needed:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Building Your First Agent

### Step 1: Create Your Agent Class

Create `my_agent.py`:

```python
from agent_framework import Agent


class MyAgent(Agent):
    """A simple agent that can read web content and remember information."""

    def get_system_prompt(self) -> str:
        """Define your agent's behavior and capabilities."""
        return """You are a helpful research assistant. You can:
        - Read and summarize web content
        - Remember important information for later
        - Help organize and retrieve saved information

        When users ask you to remember something, use the save_memory tool.
        When they ask about past information, use get_memories or search_memories."""

    def get_agent_name(self) -> str:
        """Display name for your agent."""
        return "Research Assistant"

    def get_greeting(self) -> str:
        """Greeting shown when the agent starts."""
        return "Hello! I'm your research assistant. I can read web pages and remember important information. How can I help?"
```

### Step 2: Create Your MCP Server

Create `my_server.py` to register available tools:

```python
import asyncio
import logging
from agent_framework.server import create_mcp_server
from agent_framework.tools import (
    fetch_web_content,
    save_memory,
    get_memories,
    search_memories,
)

# Note: The Agent class automatically sets up file logging to ~/.agents/logs/
# Console output is kept clean (warnings/errors only), with full logs in the file


async def main():
    # Create the server
    server = create_mcp_server("research-assistant")

    # Register web reading tool
    server.register_tool(
        name="fetch_web_content",
        description="Fetch and convert web content to clean markdown. Returns the page content, word count, and extracted links.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                }
            },
            "required": ["url"]
        },
        handler=fetch_web_content,
    )

    # Register memory tools
    server.register_tool(
        name="save_memory",
        description="Save information to persistent memory for later retrieval",
        input_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Unique identifier for this memory"
                },
                "value": {
                    "type": "string",
                    "description": "The information to remember"
                },
                "category": {
                    "type": "string",
                    "description": "Optional category to organize memories"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for filtering"
                },
                "importance": {
                    "type": "integer",
                    "description": "Importance level 1-10 (default: 5)"
                }
            },
            "required": ["key", "value"]
        },
        handler=save_memory,
    )

    server.register_tool(
        name="get_memories",
        description="Retrieve saved memories with optional filtering",
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags"
                },
                "min_importance": {
                    "type": "integer",
                    "description": "Minimum importance level"
                }
            }
        },
        handler=get_memories,
    )

    server.register_tool(
        name="search_memories",
        description="Search memories by keyword in keys or values",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                }
            },
            "required": ["query"]
        },
        handler=search_memories,
    )

    # Start the server
    server.setup_handlers()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 3: Create a Runner Script

Create `run_agent.py`:

```python
import asyncio
from my_agent import MyAgent


async def main():
    agent = MyAgent(mcp_server_path="my_server.py")
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
```

### Step 4: Run Your Agent

```bash
python run_agent.py
```

You should see:

```
Hello! I'm your research assistant. I can read web pages and remember important information. How can I help?

You:
```

Try these commands:
- "Read https://example.com and summarize it"
- "Remember that I prefer Python for scripting"
- "What have you remembered about me?"

## Adding Custom Tools

### Create a Custom Tool

Let's add a text analysis tool. Create `my_tools.py`:

```python
async def analyze_text(text: str) -> dict:
    """Analyze text and return statistics."""
    words = text.split()
    sentences = text.split('.')

    return {
        "status": "success",
        "word_count": len(words),
        "sentence_count": len([s for s in sentences if s.strip()]),
        "character_count": len(text),
        "average_word_length": sum(len(w) for w in words) / len(words) if words else 0
    }
```

### Register Your Tool

Add to `my_server.py`:

```python
from my_tools import analyze_text

# In the main() function, add:
server.register_tool(
    name="analyze_text",
    description="Analyze text and return word count, sentence count, and other statistics",
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to analyze"
            }
        },
        "required": ["text"]
    },
    handler=analyze_text,
)
```

### Update System Prompt

Update your agent's system prompt to mention the new tool:

```python
def get_system_prompt(self) -> str:
    return """You are a helpful research assistant. You can:
    - Read and summarize web content
    - Remember important information for later
    - Analyze text for statistics and insights

    Use the analyze_text tool when users want word counts or text statistics."""
```

## Using Built-in Features

### Memory System

The framework's memory system supports rich querying:

```python
# Save with metadata
save_memory(
    key="user_preference",
    value="Prefers Python over JavaScript",
    category="preferences",
    tags=["python", "languages"],
    importance=8
)

# Filter by category
get_memories(category="preferences")

# Filter by tags
get_memories(tags=["python"])

# Filter by importance
get_memories(min_importance=7)

# Search by keyword
search_memories(query="python")
```

### Slack Integration

To add Slack notifications:

1. **Set up webhook**: Get a webhook URL from Slack ([instructions](https://api.slack.com/messaging/webhooks))

2. **Add to `.env`**:
```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

3. **Register the tool**:
```python
from agent_framework.tools import send_slack_message

server.register_tool(
    name="send_slack_message",
    description="Send a message to Slack",
    input_schema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Message to send"
            },
            "username": {
                "type": "string",
                "description": "Optional bot username"
            }
        },
        "required": ["text"]
    },
    handler=send_slack_message,
)
```

### Token Storage (OAuth)

For tools that need OAuth tokens:

```python
from agent_framework.storage import TokenStore, TokenData
from datetime import datetime, timedelta
from pathlib import Path
import os

# Initialize store
token_store = TokenStore(
    storage_path=Path("./tokens"),
    encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
)

# Save a token
token_data = TokenData(
    access_token="ya29.a0AfH6...",
    refresh_token="1//0eH...",
    expires_at=datetime.utcnow() + timedelta(hours=1),
    token_type="Bearer"
)
token_store.save_token("google_calendar", token_data)

# Retrieve and use
token = token_store.get_token("google_calendar")
if token and not token.is_expired():
    # Use token.access_token
    pass
elif token and token.refresh_token:
    # Refresh the token
    pass
```

## Using Remote MCP Servers

The framework supports connecting to remote MCP servers over HTTPS with automatic OAuth authentication.

### Connecting to a Remote Server

```python
from agent_framework.core.remote_mcp_client import RemoteMCPClient

# Automatic OAuth (will open browser if needed)
async def main():
    client = RemoteMCPClient("https://mcp.example.com/mcp/")

    async with client:
        # List available tools
        tools = await client.list_tools()
        print(f"Available tools: {[t['name'] for t in tools]}")

        # Call a tool
        result = await client.call_tool("tool_name", {"arg": "value"})
        print(result)

asyncio.run(main())
```

### OAuth Authentication

The remote client automatically handles OAuth:

1. **Discovery**: Fetches OAuth configuration from `.well-known` endpoints
2. **Registration**: Dynamically registers as an OAuth client
3. **Authorization**: Opens browser for user login
4. **Token Storage**: Saves tokens to `~/.agents/tokens`
5. **Auto-Refresh**: Refreshes expired tokens automatically

**First connection:**
```
🔐 AUTHENTICATION REQUIRED
============================================================
Server: https://mcp.example.com/mcp/
Your browser will open for authentication.
Please complete the login process in your browser.
============================================================

[Browser opens for login]
✅ OAuth authentication successful, token saved
✅ Connected to remote MCP server
```

**Subsequent connections:**
```
✅ Connected to remote MCP server
```

### Configuration Options

```python
# Manual token (bypasses OAuth)
client = RemoteMCPClient(
    "https://mcp.example.com/mcp/",
    auth_token="your-manual-token"
)

# Custom OAuth settings
client = RemoteMCPClient(
    "https://mcp.example.com/mcp/",
    enable_oauth=True,
    oauth_redirect_port=8889,  # Local callback port
    oauth_scopes="read write admin",  # Custom scopes
    token_storage_dir="/custom/path/tokens"
)

# Disable OAuth (requires manual token)
client = RemoteMCPClient(
    "https://mcp.example.com/mcp/",
    enable_oauth=False,
    auth_token=os.getenv("MCP_AUTH_TOKEN")
)
```

### Using Remote Servers with Agents

You can use remote MCP servers with your agents:

```python
from agent_framework import Agent
from agent_framework.core.remote_mcp_client import RemoteMCPClient

class MyAgent(Agent):
    def __init__(self, remote_server_url: str, **kwargs):
        super().__init__(**kwargs)
        self.remote_client = RemoteMCPClient(remote_server_url)

    async def start(self):
        async with self.remote_client:
            # Now you can use remote_client.list_tools() and call_tool()
            await super().start()
```

### Token Management

```python
# Clear saved tokens (useful for logout or debugging)
client.clear_tokens()

# Check server health
is_healthy = await client.health_check()
```

### Environment Variables

```bash
# Use manual token from environment
export MCP_AUTH_TOKEN="your-token-here"

# Then in code (auth_token will be read from environment)
client = RemoteMCPClient("https://mcp.example.com/mcp/")
```

### Device Flow for Headless Environments

For environments without browser access (containers, SSH sessions, servers), use Device Flow:

```python
from agent_framework import Agent

class MyAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You are a helpful assistant."

# Create with device flow enabled
agent = MyAgent(
    mcp_server_path="server.py",
    mcp_urls=["https://mcp.example.com/mcp/"],
    mcp_client_config={
        "prefer_device_flow": True,
        # Optional: get notified via callback when auth is needed
        "device_authorization_callback": my_callback,
    },
)
```

When authentication is required, you'll see:
```
🔐 DEVICE AUTHORIZATION REQUIRED
============================================================
To authorize this device, please:
  1. Visit: https://auth.example.com/device
  2. Enter code: ABCD-1234

This code expires in 15 minutes.
============================================================
```

## Using RAG (Semantic Search)

The framework includes RAG (Retrieval-Augmented Generation) for semantic document search.

### Prerequisites

1. PostgreSQL with pgvector extension
2. OpenAI API key for embeddings

```bash
# Install pgvector (on Ubuntu/Debian)
sudo apt install postgresql-16-pgvector

# Or via psql
CREATE EXTENSION vector;
```

### Configuration

Add to `.env`:
```bash
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
OPENAI_API_KEY=sk-...
```

### Using RAG Tools

```python
from agent_framework.tools import (
    add_document,
    search_documents,
    get_document,
    delete_document,
    list_documents,
)

# Add a document
result = await add_document(
    content="Your document text here...",
    metadata={"category": "blog", "author": "John"},
)

# Add from PDF file
result = await add_document(
    file_path="/path/to/document.pdf",
    metadata={"category": "reports"},
)

# Search semantically
results = await search_documents(
    query="What are the benefits of async programming?",
    top_k=5,
    min_score=0.5,  # Only return results with 50%+ similarity
)

# Filter by metadata
results = await search_documents(
    query="project updates",
    metadata_filter={"category": "reports"},
)
```

### Register RAG Tools in MCP Server

```python
from agent_framework.tools import add_document, search_documents

server.register_tool(
    name="add_document",
    description="Add a document to the knowledge base for semantic search",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Document text"},
            "file_path": {"type": "string", "description": "Path to PDF file"},
            "metadata": {"type": "object", "description": "Optional metadata"},
        },
    },
    handler=add_document,
)

server.register_tool(
    name="search_documents",
    description="Search the knowledge base using semantic similarity",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "top_k": {"type": "integer", "description": "Max results"},
        },
        "required": ["query"],
    },
    handler=search_documents,
)
```

## Multi-Agent Slack Bot

Route Slack messages to multiple specialized agents with the MultiAgentSlackAdapter.

### Prerequisites

1. Create a Slack app at https://api.slack.com/apps
2. Enable Socket Mode
3. Add bot scopes: `chat:write`, `app_mentions:read`, `im:history`, `im:read`, `im:write`
4. Install the app to your workspace

### Configuration

Add to `.env`:
```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
```

### Basic Usage

```python
from agent_framework import Agent, MultiAgentSlackAdapter, RoutingStrategy

# Define your agents
class TaskAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You help manage tasks and schedules."

class PRAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You help review pull requests."

# Create adapter
adapter = MultiAgentSlackAdapter(
    routing_strategy=RoutingStrategy.HYBRID,  # Try all routing methods
)

# Register agents with keywords
adapter.register_agent(
    name="tasks",
    agent=TaskAgent(mcp_server_path="task_server.py"),
    keywords=["task", "todo", "schedule", "deadline"],
    description="Task and schedule management",
)

adapter.register_agent(
    name="pr",
    agent=PRAgent(mcp_server_path="pr_server.py"),
    keywords=["pr", "pull request", "review", "code"],
    description="Pull request reviews",
)

# Set default and start
adapter.set_default_agent("tasks")
adapter.start()  # Blocks - runs the Slack bot
```

### Routing Strategies

- **KEYWORD**: Routes based on keywords in the message
- **EXPLICIT**: Routes when user says `@tasks` or `ask pr: review this`
- **CHANNEL**: Routes based on which Slack channel
- **HYBRID** (default): Tries explicit → keywords → last agent in thread → default

### Device Flow OAuth via Slack

When agents need OAuth for remote MCP servers, post auth URLs to Slack:

```python
# Create callback that posts to Slack
auth_callback = adapter.create_device_auth_callback(
    channel="#bot-auth",
    mention_user="U1234567890",  # Optional: @mention someone
)

adapter.register_agent(
    name="tasks",
    agent=TaskAgent(
        mcp_urls=["https://mcp.example.com/mcp/"],
        mcp_client_config={
            "prefer_device_flow": True,
            "device_authorization_callback": auth_callback,
        },
    ),
    keywords=["task"],
)
```

## Project Organization

For larger projects, organize your code like this:

```
my-agent/
├── my_agent/
│   ├── __init__.py
│   ├── agent.py              # Your Agent subclass
│   ├── server.py             # MCP server setup
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── custom_tool1.py
│   │   └── custom_tool2.py
│   └── prompts.py            # System prompts
├── run_agent.py              # Entry point
├── .env                      # Configuration
├── pyproject.toml            # Dependencies
└── README.md
```

## Next Steps

Now that you have a working agent:

1. **Customize the system prompt** to define specific behaviors
2. **Add domain-specific tools** for your use case
3. **Integrate with external APIs** using token storage
4. **Deploy as a service** or package as a CLI tool

For deeper understanding of the framework architecture and design patterns, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Logging

The framework automatically logs to `~/.agents/logs/` with date-stamped files:

```
~/.agents/logs/
├── myagent_2024-01-15.log      # Agent logs
└── mcp_server_2024-01-15.log   # MCP server logs
```

- **Console**: Only warnings and errors (clean user experience)
- **File**: Full DEBUG/INFO logs (for debugging)

The log file path is shown when the agent starts:

```
Logs: /home/user/.agents/logs/myagent_2024-01-15.log
```

You can customize the log directory:

```python
from pathlib import Path

agent = MyAgent(
    mcp_server_path="server.py",
    log_dir=Path("/custom/log/path"),
)
```

Or via environment variable:

```bash
LOG_DIR=/var/log/myagent python run_agent.py
```

## Troubleshooting

### Agent won't start
- Check that your `.env` file has `ANTHROPIC_API_KEY` set
- Verify the MCP server path is correct
- Check for Python syntax errors in your agent/server files

### Tools not working
- Ensure tools are registered before `server.setup_handlers()`
- Check the input schema matches your tool's parameters
- Check the log file for detailed error messages

### Memory not persisting
- Check that the storage directory exists and is writable
- Verify you're using the same storage path between runs
- Look for file permissions issues

## Getting Help

- Check the source code - it's well-documented
- See [ARCHITECTURE.md](ARCHITECTURE.md) for design patterns
- Open an issue on GitHub for bugs or questions
