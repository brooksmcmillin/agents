# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a multi-agent system built with Claude (Anthropic SDK) and Model Context Protocol (MCP). The repository is structured to support multiple specialized agents that share common infrastructure:

**Architecture:**
1. **Agents** (`agents/`) - Individual agent implementations, each in its own subdirectory
   - `pr_agent/` - PR and content strategy assistant
   - `task_manager/` - Interactive task management agent
   - `business_advisor/` - Business strategy and monetization advisor
   - `notifier/` - Lightweight task notification script (Slack)
2. **MCP Server** (`mcp_server/`) - Shared tools for content analysis, social media analytics, and persistent memory
3. **Shared Utilities** (`shared/`) - Common code reusable across all agents

## Development Setup

This project uses `uv` for dependency management:

```bash
# Install dependencies
uv sync

# Run the PR agent
uv run python -m agents.pr_agent.main

# Run the task manager agent (requires remote MCP server)
uv run python -m agents.task_manager.main

# Run the business advisor agent
uv run python -m agents.business_advisor.main

# Send Slack notification about open tasks
uv run python -m agents.notifier.main

# Run the MCP server standalone (for testing)
uv run python -m mcp_server.server

# Run the demo (tests MCP tools without agent)
uv run python demo.py
```

**Environment Configuration:**
- Copy `.env.example` to `.env`
- Add `ANTHROPIC_API_KEY=your_key_here`

## Architecture

### Component Communication Flow

**Local Setup (Default):**
```
User Input → Agent (agents/*/main.py) → Claude API (Sonnet 4.5) → agent-framework (MCP Client)
                ↑                                                          ↓
                │                                                  MCP Server (stdio)
                │                                                          ↓
                └─────────────── Tool Results ←───────────────── Tools (mcp_server/tools/)
```

**Remote Setup (Optional):**
```
User Input → Agent → Claude API → RemoteMCPClient (HTTP/SSE) → Remote MCP Server (HTTP)
                ↑                                                      ↓
                │                                                 Tools (remote)
                └─────────────────── Tool Results ←──────────────────────┘
```

**Critical Design Pattern: Hot Reload via Reconnection**
- The agent reconnects to the MCP server for **each tool call** instead of maintaining a persistent connection
- This enables editing MCP tools while the agent is running without losing conversation context
- When tool code is modified, changes are picked up on the next tool call
- Type `reload` in the agent to force reconnection and discover updated tools

**Remote MCP Option:**
- MCP servers can be hosted remotely via HTTP/SSE transport
- Multiple agents can share one remote MCP server
- See [REMOTE_MCP.md](REMOTE_MCP.md) for setup guide

### Agentic Loop Pattern

Each agent extends the `Agent` class from `agent-framework` which implements a multi-turn conversation loop:

```python
while not done:
    # 1. Call Claude with conversation history + available tools
    response = await client.messages.create(messages=history, tools=tools)

    # 2. If Claude wants to use tools, execute them via MCP
    if response.stop_reason == "tool_use":
        async with mcp_client.connect():  # Fresh connection each time
            results = await mcp_client.call_tool(name, args)
        history.append(tool_results)
        # Loop continues - Claude analyzes results

    # 3. Claude provides final text response
    else:
        return response.content
```

**Key Details:**
- Max 10 iterations to prevent infinite loops
- Each MCP tool call reconnects to the server (enables hot reload)
- Tool execution errors are returned to Claude as `is_error` results
- Conversation history preserved in `self.messages` list

## MCP Tools

The MCP server exposes 7 tools (defined in `mcp_server/server.py`):

### Content Analysis Tools
- `analyze_website` - Web content analysis (tone, SEO, engagement) - uses real web scraping
- `fetch_web_content` - Fetch web content as clean markdown for LLM reading and analysis
- `get_social_media_stats` - Social media metrics (Twitter, LinkedIn) - currently uses mock data
- `suggest_content_topics` - Content idea generation - currently uses mock data

### Memory Tools
- `save_memory` - Save information with key/value/category/tags/importance
- `get_memories` - Retrieve memories with filtering by category/tags/importance
- `search_memories` - Search memories by keyword

### Tool Usage Examples

**Fetch and Read Web Content:**
```python
# Get clean markdown content from any webpage
result = await fetch_web_content(
    url="https://example.com/article",
    max_length=50000  # optional, defaults to 50000
)

# Returns:
# {
#     "url": "https://example.com/article",
#     "title": "Article Title",
#     "content": "# Heading\n\nParagraph text...",  # Clean markdown
#     "word_count": 1250,
#     "char_count": 7543,
#     "has_images": True,
#     "has_links": True
# }
```

This tool is perfect for:
- Reading blog posts or articles to provide feedback
- Extracting documentation for analysis
- Getting content to answer questions about specific pages
- Preparing content for further processing by Claude

**Adding a New Tool:**

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

## Memory System

**Storage:** JSON file at `memories/memories.json` (file-based, easily migrated to database)

**Structure:**
```python
{
    "key": {
        "value": "the stored information",
        "category": "user_preference",  # fact, goal, insight
        "tags": ["seo", "twitter"],
        "importance": 8,  # 1-10
        "created_at": "2024-...",
        "updated_at": "2024-..."
    }
}
```

**Agent Behavior:**
- The system prompt (`agent/prompts.py`) instructs Claude to check memories at conversation start
- Save important details with descriptive keys (e.g., `user_blog_url` not `url`)
- Set appropriate importance levels (7-10 for critical info)
- Update existing memories when information changes

## Agent Self-Improvement

The agent is configured to provide **meta-feedback** about tools and capabilities. This helps identify missing features and improvement opportunities.

**How it works:**
- Agent is instructed to reflect on tool limitations while working
- When relevant, includes a "💡 Tool Improvement Ideas" section at the end of responses
- Feedback is structured: [Missing Tool], [Enhancement], [Data Need], [Workflow]
- Only provided when genuinely helpful, not on every response

**Example feedback:**
```
💡 Tool Improvement Ideas

[Missing Tool] A compare_websites tool for competitive analysis would enable
side-by-side comparisons instead of manual comparison.

[Enhancement] analyze_website could include keyword density analysis for
better SEO recommendations.
```

**Using this feedback:**
- Review agent responses for tool suggestions
- Prioritize commonly requested features
- Implement high-value tools identified by actual usage
- Iterate based on real user needs

This creates a feedback loop where the agent helps improve itself based on real-world usage patterns.

## OAuth Infrastructure (Ready for Production)

**Current State:** Complete OAuth 2.0 implementation with mock data for testing

**Components:**
- `mcp_server/auth/oauth_handler.py` - Authorization Code Flow & Client Credentials Flow
- `mcp_server/auth/token_store.py` - Encrypted token storage using Fernet

**To Enable Real APIs:**

1. Register OAuth apps with Twitter/LinkedIn
2. Add credentials to `.env`:
   ```
   TWITTER_CLIENT_ID=...
   TWITTER_CLIENT_SECRET=...
   LINKEDIN_CLIENT_ID=...
   LINKEDIN_CLIENT_SECRET=...
   ```
3. Uncomment OAuth check in `mcp_server/server.py` `call_tool()`:
   ```python
   token = await oauth_handler.get_valid_token(platform)
   if not token:
       raise PermissionError("Authentication required")
   ```
4. Implement authorization flow UI
5. Replace mock data in tools with real API calls using `token.access_token`

**Token Storage Migration:**
- File-based storage interface makes migration to database/vault straightforward
- Same interface: `get_token()`, `save_token()`, `delete_token()`
- SQL schema examples included in `mcp_server/memory_store.py` comments

## Key Files and Responsibilities

**Agents:**
- `agents/pr_agent/main.py` - PR agent implementation extending agent-framework
- `agents/pr_agent/prompts.py` - System prompt defining agent behavior and memory usage
- `agents/*/` - Additional agents can be added as siblings to pr_agent

**Shared Infrastructure:**
- `shared/` - Common utilities and base classes for all agents
- `agent-framework` - External package providing base Agent class, MCP client, and OAuth utilities

**MCP Server (Shared Tools):**
- `mcp_server/server.py` - MCP server (stdio transport) for local use
- `mcp_server/server_http.py` - MCP server (HTTP/SSE transport) for remote use
- `mcp_server/tools/` - Tool implementations (all async functions)
- `mcp_server/memory_store.py` - Persistent memory storage
- `mcp_server/auth/` - OAuth handler and token storage
- `mcp_server/config.py` - Configuration via pydantic-settings

## Development Workflow

**Editing Tools Without Restarting:**

1. Start agent: `uv run python -m agents.pr_agent.main`
2. Edit tool code in `mcp_server/tools/*.py`
3. Save changes
4. Next tool call automatically picks up changes
5. Type `reload` to force reconnection if needed

See `HOT_RELOAD.md` for details.

**Testing and Debugging:**

See [TESTING.md](TESTING.md) for comprehensive testing and debugging guide, including:
- Memory system testing with `scripts/test_memory.py`
- Backend configuration (file vs database)
- Log file locations and common error patterns
- Database connectivity testing
- Common issues and solutions

**Quick Debugging:**

```bash
# Test memory system
uv run python scripts/test_memory.py stats

# View agent logs
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log

# Test MCP server standalone
uv run python -m mcp_server.server
```

**Interactive Commands:**
- `exit` or `quit` - End session
- `stats` - Show token usage statistics
- `reload` - Reconnect to MCP server and discover updated tools

## Code Style

- Use modern Python typing (dict/list not typing.Dict/List, `str | None` not Optional[str])
- All functions have type hints including return types
- All async I/O operations use async/await
- Comprehensive docstrings (Google style)
- Errors logged before returning to user
- JSON for all tool results

## Current State vs Production

**Working Now:**
- Full agentic loop with Claude Sonnet 4.5
- 7 MCP tools (4 content analysis + 3 memory)
- Real web scraping and content analysis (analyze_website, fetch_web_content)
- Persistent memory across conversations
- Hot reload for tool development
- OAuth infrastructure (not connected to real APIs)
- Token usage tracking
- Comprehensive error handling

**Production Readiness:**
- Social media tools use mock data - integrate Twitter/LinkedIn APIs
- File-based storage - migrate to PostgreSQL/Redis for memory and tokens
- No rate limiting - add for production
- No multi-user support - add user_id to memory/auth
- Stdio transport - consider HTTP/SSE for remote deployment

## Adding New Agents

To create a new agent:

1. **Create agent directory:**
   ```bash
   mkdir -p agents/your_agent
   ```

2. **Create main.py extending Agent:**
   ```python
   # agents/your_agent/main.py
   import asyncio
   from agent_framework import Agent
   from dotenv import load_dotenv
   from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

   load_dotenv()

   class YourAgent(Agent):
       def get_system_prompt(self) -> str:
           return SYSTEM_PROMPT

       def get_greeting(self) -> str:
           return USER_GREETING_PROMPT

   async def main():
       agent = YourAgent()
       await agent.start()

   if __name__ == "__main__":
       asyncio.run(main())
   ```

3. **Create prompts.py:**
   ```python
   # agents/your_agent/prompts.py
   SYSTEM_PROMPT = """Your agent's system prompt..."""
   USER_GREETING_PROMPT = """Your agent's greeting..."""
   ```

4. **Create __init__.py:**
   ```python
   # agents/your_agent/__init__.py
   """Your agent description."""
   __version__ = "0.1.0"
   ```

5. **Run your new agent:**
   ```bash
   uv run python -m agents.your_agent.main
   ```

All agents automatically have access to the shared MCP tools. You can add agent-specific tools to the MCP server as needed.

## Common Tasks

**Read and analyze web content:**
```python
# Use fetch_web_content to get clean markdown
content = await fetch_web_content("https://blog.example.com/post")

# Claude can now read and comment on the content
# The analyze_website tool provides SEO/tone/engagement scores
analysis = await analyze_website("https://blog.example.com/post", "seo")
```

**Integrate Twitter API:**
```python
# In mcp_server/tools/social_media.py
token = await oauth_handler.get_valid_token("twitter")
headers = {"Authorization": f"Bearer {token.access_token}"}
async with httpx.AsyncClient() as client:
    response = await client.get(
        "https://api.twitter.com/2/users/me/tweets",
        headers=headers
    )
    # Process real data
```

**Change Claude model:**
```python
# In agents/pr_agent/main.py PRAgent class
# Pass model parameter to agent-framework's Agent.__init__()
# See agent-framework documentation for details
```

**Migrate memory to PostgreSQL:**
```python
# Replace MemoryStore in mcp_server/memory_store.py
# SQL schema examples in comments
# Keep same interface: get_memory(), save_memory(), search_memories()
```
