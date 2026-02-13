# Hot Reload Development Workflow

This guide explains how the hot reload feature works in this agent framework, enabling you to edit MCP tools while agents are running without losing conversation context.

## What is Hot Reload?

**Hot reload** allows you to modify tool code and have changes picked up automatically on the next tool call, without restarting the agent or losing conversation history.

**Traditional workflow** (without hot reload):
```
1. Edit tool code
2. Stop agent (loses conversation context)
3. Restart agent
4. Re-establish conversation context
5. Test changes
```

**Hot reload workflow**:
```
1. Edit tool code
2. Save file
3. Type 'reload' or wait for next tool call
4. Changes immediately available
5. Conversation context preserved
```

## How It Works

### The Reconnection Pattern

Instead of maintaining a persistent connection to the MCP server, agents reconnect for **each tool call**:

```python
# In agent_framework/core/agent.py

async def process_message(self, user_message: str) -> str:
    while not done:
        # 1. Call Claude with conversation history + tools
        response = await self.client.messages.create(
            messages=self.messages,
            tools=self.tools,
            ...
        )

        # 2. If Claude wants to use tools
        if response.stop_reason == "tool_use":
            # Fresh connection for each tool call batch
            async with self.mcp_client.connect() as connection:
                # Execute tools
                results = await self._execute_tools(tool_uses, connection)

            # Connection automatically closed
            # Next tool call gets fresh connection

        # 3. Claude provides final response
        else:
            return response.content[0].text
```

**Key insight**: By opening a fresh connection for each tool call, the agent:
1. Reloads tool module code on import
2. Discovers updated tool schemas
3. Picks up any code changes
4. Preserves conversation history in `self.messages`

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent Process (keeps running)                                   │
│                                                                  │
│  ┌──────────────────────┐                                       │
│  │ Conversation History │  ← Preserved across tool calls       │
│  │ self.messages[]      │                                       │
│  └──────────────────────┘                                       │
│                                                                  │
│  Tool Call 1:                                                    │
│  ┌─────────┐                                                    │
│  │ Connect │ → MCP Server (stdio) → Import tools → Execute      │
│  └─────────┘                                                    │
│       ↓                                                          │
│  ┌────────────┐                                                 │
│  │ Disconnect │                                                 │
│  └────────────┘                                                 │
│                                                                  │
│  [You edit tool code here - changes saved to disk]              │
│                                                                  │
│  Tool Call 2:                                                    │
│  ┌─────────┐                                                    │
│  │ Connect │ → MCP Server (stdio) → Import tools (UPDATED)      │
│  └─────────┘                          ↑                         │
│                                        └─ Fresh import picks    │
│                                           up changes!           │
└─────────────────────────────────────────────────────────────────┘
```

## Developer Workflow

### Basic Workflow

1. **Start your agent**
   ```bash
   uv run python -m agents.chatbot.main
   ```

2. **Have a conversation**
   ```
   You: Fetch the content from https://example.com

   Agent: I'll fetch that content for you.
   [Calls fetch_web_content]
   Here's the content...
   ```

3. **Edit tool code** (in another terminal or editor)
   ```bash
   # Edit the tool file
   vim packages/agent-framework/agent_framework/tools/web_reader.py

   # Make your changes
   # Add logging, fix bugs, enhance functionality
   # Save the file
   ```

4. **Test changes immediately**
   ```
   You: Fetch content from https://another-site.com

   Agent: I'll fetch that content for you.
   [Calls fetch_web_content - UPDATED VERSION]
   Here's the content with your changes...
   ```

The conversation context is preserved, but the tool code is fresh!

### Using the `reload` Command

Force reconnection without waiting for next tool call:

```
You: reload

Agent: Reconnecting to MCP server...
✓ Reconnected successfully
Tools refreshed: 29 tools available
```

**When to use `reload`**:
- After editing tool code to verify changes immediately
- To discover newly added tools
- To refresh tool schemas after modification
- When troubleshooting tool issues

### Example: Adding Logging to a Tool

Let's walk through a real example of adding debug logging to a tool:

**Initial tool code** (`tools/web_reader.py`):
```python
async def fetch_web_content(url: str, max_length: int = 50000) -> dict[str, Any]:
    """Fetch web content as markdown."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        # ... process content
        return {"url": url, "content": content}
```

**Agent conversation**:
```
You: Fetch https://example.com

Agent: [Calls fetch_web_content]
Here's the content...
```

**Edit tool** (add logging):
```python
import logging
logger = logging.getLogger(__name__)

async def fetch_web_content(url: str, max_length: int = 50000) -> dict[str, Any]:
    """Fetch web content as markdown."""
    logger.info(f"Fetching content from {url}")  # ← NEW
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        logger.info(f"Response status: {response.status_code}")  # ← NEW
        # ... process content
        logger.info(f"Content length: {len(content)}")  # ← NEW
        return {"url": url, "content": content}
```

**Test immediately** (no agent restart needed):
```
You: Fetch https://another-site.com

Agent: [Calls fetch_web_content - NOW WITH LOGGING]
Here's the content...

# Check logs (in another terminal)
$ tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log
INFO:agent_framework.tools.web_reader:Fetching content from https://another-site.com
INFO:agent_framework.tools.web_reader:Response status: 200
INFO:agent_framework.tools.web_reader:Content length: 15432
```

Changes are live! No restart required!

### Example: Fixing a Bug

**Scenario**: Tool crashes on invalid URLs

**Step 1**: Encounter the bug
```
You: Fetch content from not-a-url

Agent: [Calls fetch_web_content]
Error: Invalid URL format
```

**Step 2**: Fix the bug (add validation)
```python
async def fetch_web_content(url: str, max_length: int = 50000) -> dict[str, Any]:
    """Fetch web content as markdown."""
    # Add URL validation
    if not url.startswith(("http://", "https://")):
        return {
            "error": "Invalid URL - must start with http:// or https://",
            "url": url
        }

    async with httpx.AsyncClient() as client:
        # ... rest of code
```

**Step 3**: Test immediately (same conversation)
```
You: Fetch content from not-a-url

Agent: [Calls fetch_web_content - FIXED VERSION]
I encountered an error: Invalid URL - must start with http:// or https://

You: Fetch content from https://example.com

Agent: [Works correctly now]
Here's the content...
```

Bug fixed without restarting agent or losing context!

### Example: Adding a New Tool

**Step 1**: Create new tool file
```bash
# packages/agent-framework/agent_framework/tools/new_tool.py
async def my_new_tool(param: str) -> dict[str, Any]:
    """Description of new tool."""
    return {"result": f"Processed {param}"}

TOOL_SCHEMAS = [
    {
        "name": "my_new_tool",
        "description": "Description of new tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "param": {"type": "string"}
            },
            "required": ["param"]
        },
        "handler": my_new_tool,
    }
]
```

**Step 2**: Export from `__init__.py`
```python
# packages/agent-framework/agent_framework/tools/__init__.py
from .new_tool import my_new_tool, TOOL_SCHEMAS as _new_tool_schemas

ALL_TOOL_SCHEMAS: list[dict] = [
    # ... existing schemas
    *_new_tool_schemas,  # ← Add your new tool
]

__all__ = [
    # ... existing exports
    "my_new_tool",  # ← Add your new tool
]
```

**Step 3**: Register in MCP server (if needed)
```python
# config/mcp_server/server.py
from agent_framework.tools import my_new_tool

# Register tool
server.register_tool(
    name="my_new_tool",
    description="Description of new tool",
    handler=my_new_tool,
    input_schema={...}
)
```

**Step 4**: Reload in agent
```
You: reload

Agent: Reconnecting to MCP server...
✓ Reconnected successfully
Tools refreshed: 30 tools available  ← New count!

You: Use my_new_tool with param "test"

Agent: [Calls my_new_tool]
Result: Processed test
```

New tool available without restarting!

## What Hot Reloads and What Doesn't

### ✅ Hot Reloads (Changes Picked Up Automatically)

**Tool implementation code**:
```python
# Changes to tool logic are picked up immediately
async def my_tool(param: str) -> dict[str, Any]:
    # This code is reloaded on next call
    return {"result": process(param)}
```

**Tool input schemas**:
```python
# Schema changes are discovered on reconnection
TOOL_SCHEMAS = [{
    "input_schema": {
        "properties": {
            "new_param": {"type": "string"}  # ← Added parameter
        }
    }
}]
```

**Tool dependencies**:
```python
# Updated imports and dependencies
from new_library import new_function  # ← New import

async def my_tool():
    result = new_function()  # ← Uses new code
```

**MCP server tool registration**:
```python
# New tools registered in server.py
server.register_tool(new_tool)  # ← Discovered on reload
```

### ❌ Does NOT Hot Reload (Requires Agent Restart)

**Agent system prompts**:
```python
# agents/chatbot/prompts.py
SYSTEM_PROMPT = "You are a helpful assistant..."  # ← Changes require restart
```

**Agent configuration**:
```python
# agents/chatbot/main.py
ChatbotAgent = create_simple_agent(
    name="ChatbotAgent",
    system_prompt=SYSTEM_PROMPT,  # ← Changes require restart
    allowed_tools=["tool1", "tool2"],  # ← Changes require restart
)
```

**Agent class code**:
```python
# agent_framework/core/agent.py
class Agent:
    def process_message(self, message: str):  # ← Changes require restart
        # Agent logic
```

**Environment variables**:
```bash
# .env
ANTHROPIC_API_KEY=...  # ← Changes require restart
```

**Python dependencies**:
```bash
# pyproject.toml
dependencies = ["new-package"]  # ← Requires uv sync + restart
```

## Limitations and Edge Cases

### Module-Level State

Module-level variables are reset on reconnection:

```python
# tools/my_tool.py

# This cache is reset on each reconnection
_cache = {}  # ← Lost on reconnect

async def my_tool(key: str) -> dict[str, Any]:
    if key in _cache:
        return _cache[key]  # ← Won't work across tool calls
    result = expensive_operation(key)
    _cache[key] = result
    return result
```

**Solution**: Use external cache (Redis, database) or agent memory:

```python
from agent_framework.tools import save_memory, get_memories

async def my_tool(key: str) -> dict[str, Any]:
    # Check memory for cached result
    memories = await get_memories(category="cache", tags=[key])
    if memories:
        return {"cached": True, "result": memories[0]["value"]}

    # Compute and cache
    result = expensive_operation(key)
    await save_memory(
        key=f"cache_{key}",
        value=result,
        category="cache",
        tags=[key]
    )
    return {"cached": False, "result": result}
```

### Import Side Effects

Code that runs at import time runs on every reconnection:

```python
# tools/my_tool.py

# This runs on EVERY import (every reconnection)
print("Initializing tool...")  # ← Runs repeatedly
EXPENSIVE_CONSTANT = load_large_file()  # ← Slow!

async def my_tool():
    # ...
```

**Solution**: Lazy initialization:

```python
# tools/my_tool.py

_expensive_constant = None

def _get_expensive_constant():
    global _expensive_constant
    if _expensive_constant is None:
        _expensive_constant = load_large_file()  # ← Only once
    return _expensive_constant

async def my_tool():
    constant = _get_expensive_constant()
    # ...
```

### Syntax Errors

Syntax errors in tool code break the MCP server:

```python
# tools/my_tool.py

async def my_tool():
    return "result"  # ← Forgot return statement syntax
    # This breaks the entire MCP server!
```

**Recovery**:
```
# Agent shows error message
Error: MCP server connection failed

# Fix syntax error
# Type 'reload' to reconnect
You: reload

Agent: Reconnecting to MCP server...
✓ Reconnected successfully
```

## Performance Considerations

### Connection Overhead

Each tool call incurs connection overhead:

```
Without hot reload (persistent connection):
- Tool call: 1-5ms

With hot reload (reconnect per call):
- Tool call: 10-50ms
- Overhead: 9-45ms per call
```

**Impact**: Minimal for typical conversational agents (human latency >> connection overhead)

**When it matters**:
- High-frequency tool calls (>100/second)
- Performance-critical applications
- Batch processing

**Mitigation**: Disable hot reload for production if needed (see next section)

### Import Time

Python imports are cached after first load:

```
First tool call:  Import time + execution time
Second tool call: Execution time only (import cached)
After edit:       Import time + execution time (re-import)
```

**Typical import times**:
- Simple tool: <1ms
- Tool with heavy dependencies: 10-100ms

## Disabling Hot Reload

For production deployments where hot reload is not needed:

```python
# agents/your_agent/main.py

class YourAgent(Agent):
    def __init__(self):
        super().__init__(
            mcp_stdio_command="python config/mcp_server/server.py",
            # Maintain persistent connection (no hot reload)
            # This is faster but requires restart for tool changes
        )

    async def process_message(self, message: str) -> str:
        # Option 1: Connect once at start
        if not self._connection:
            self._connection = await self.mcp_client.connect()

        # Use persistent connection for all tool calls
        # No hot reload, but faster tool execution
```

Note: This is not currently implemented but shows how you could modify the architecture to disable hot reload.

## Best Practices

### 1. Test changes incrementally

```
# Good: Small, testable changes
Edit tool → Save → Type 'reload' → Test → Iterate

# Bad: Many changes at once
Edit 5 tools → Save all → Test → Figure out which broke
```

### 2. Use logging for debugging

```python
import logging
logger = logging.getLogger(__name__)

async def my_tool():
    logger.debug("Tool called with ...")
    logger.info("Processing ...")
    logger.error("Error: ...")
```

Watch logs in another terminal:
```bash
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log
```

### 3. Handle errors gracefully

```python
async def my_tool() -> dict[str, Any]:
    try:
        result = risky_operation()
        return {"result": result}
    except Exception as e:
        logger.exception("Tool failed")
        return {"error": str(e)}  # ← Return error, don't crash
```

### 4. Test in conversation context

```
# Good: Test with realistic conversation
You: Save this to memory
Agent: Done
You: Now use that information for...  ← Tests with context

# Bad: Test tool in isolation only
You: Call tool with test data
Agent: Done
[Restart and test again]  ← Loses context
```

### 5. Use `reload` liberally

```
# After editing tools
You: reload

# After adding new tools
You: reload

# When troubleshooting
You: reload
```

## Troubleshooting

### Changes Not Picked Up

**Problem**: Edited tool code, but changes not reflected

**Solutions**:
1. **Type `reload`** to force reconnection
2. **Check file saved** - ensure editor actually saved the file
3. **Check Python caching** - delete `__pycache__` directories
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} +
   ```
4. **Check import path** - ensure editing correct file
   ```bash
   # Find which file is being imported
   python -c "import agent_framework.tools.my_tool; print(agent_framework.tools.my_tool.__file__)"
   ```

### MCP Server Won't Start After Edit

**Problem**: Made changes, now MCP server crashes on connect

**Cause**: Syntax error or import error in tool code

**Solution**:
1. Check agent error message for details
2. Fix syntax error in tool file
3. Type `reload` to reconnect

**Prevention**:
```bash
# Test tool file syntax before reloading
python -m py_compile packages/agent-framework/agent_framework/tools/my_tool.py
```

### Tools Disappearing

**Problem**: Some tools no longer available after reload

**Cause**: Tool not properly exported or registered

**Solution**:
1. Check tool is exported in `tools/__init__.py`
2. Check tool is registered in MCP server
3. Type `reload` and check tool count
4. List tools: Agent shows available tools in error messages

### Slow Reconnection

**Problem**: `reload` command takes a long time

**Cause**: Heavy imports at module level or slow MCP server startup

**Solution**:
1. Profile import time:
   ```bash
   python -X importtime -c "from agent_framework.tools import my_tool" 2>&1 | grep my_tool
   ```
2. Move heavy initialization to lazy loading
3. Optimize MCP server startup

---

## Related Documentation

- [CLAUDE.md](CLAUDE.md) - Project overview and development guide
- [agent-framework/ARCHITECTURE.md](packages/agent-framework/ARCHITECTURE.md) - Technical details
- [Testing Guide](docs/TESTING.md) - Testing strategies
- [Tool Development](packages/agent-framework/) - Creating new tools
