# Hot Reload Guide - Edit MCP Tools Without Losing Context

The agent now supports hot-reloading MCP tools! You can edit tool code and use the updated version without restarting the agent or losing your conversation history.

## How It Works

The agent now **reconnects to the MCP server for each tool call** instead of holding a persistent connection. This means:

1. You can restart the MCP server between requests
2. Tool changes are picked up automatically on the next tool call
3. Your conversation context is preserved in the agent

## Workflow

### Terminal 1: Run the Agent
```bash
uv run python -m agent.main
```

### Terminal 2: Edit MCP Tools
While the agent is running, edit any tool in `mcp_server/tools/`:

```bash
# Edit a tool
vim mcp_server/tools/web_analyzer.py

# Make your changes, save the file
```

The MCP server will automatically restart when you make the next tool call from the agent!

## Example Session

```
You: Analyze https://example.com for tone
Assistant: [Uses analyze_website tool, shows results]

# Now edit mcp_server/tools/web_analyzer.py
# Add a new field or change the mock data
# Save the file

You: Analyze another page for SEO
Assistant: [Reconnects to MCP server, uses updated tool code!]
```

Your conversation history is preserved - only the MCP server reconnects.

## New Commands

### `reload` Command
Force a reconnection to discover updated tools:

```
You: reload
🔄 Reconnecting to MCP server...
✓ Connected! Available tools: analyze_website, get_social_media_stats, suggest_content_topics
```

Use this if you:
- Added a new tool
- Changed tool names or descriptions
- Want to verify the server is running

## What Gets Reloaded

✅ **Tool implementation code** - Changes to `mcp_server/tools/*.py`
✅ **Tool schemas** - Updated parameters, descriptions
✅ **New tools** - Add new tools and type `reload`
✅ **OAuth handler changes** - Updates to `mcp_server/auth/`
✅ **Server configuration** - Changes to `mcp_server/server.py`

❌ **Conversation history** - Stays in agent memory
❌ **Environment variables** - Requires agent restart
❌ **Anthropic API key** - Requires agent restart

## Technical Details

### Before (Single Connection)
```python
# Old approach - connection held for entire session
async with mcp_client.connect():
    while True:
        # Process messages
        # Call tools
```

### After (Reconnect Per Tool Call)
```python
# New approach - reconnect for each tool call
while True:
    # Process messages

    # Reconnect for tool call
    async with mcp_client.connect():
        result = await mcp_client.call_tool(...)
```

This adds minimal overhead (~50-100ms per tool call) but enables:
- Hot reloading
- More resilient error handling
- Independent MCP server restarts

## Tips

1. **Keep conversations short while developing** - Makes it easier to test changes
2. **Use the `reload` command** - Verify new tools are discovered
3. **Check logs** - `tail -f pr_agent.log` to see reconnection events
4. **Test in isolation** - Use `demo.py` to test tool changes before using with agent

## Common Issues

**Q: My changes aren't showing up**
- Type `reload` to force tool discovery
- Check that your Python file has no syntax errors
- Verify the MCP server can start: `uv run python -m mcp_server.server`

**Q: Getting connection errors**
- The MCP server might have crashed - check syntax errors
- Make sure the server path is correct in your code

**Q: Lost my conversation context**
- Don't restart the agent! The reload happens automatically
- If you did restart, that's expected - conversation history is in memory

## Benefits

- **Faster iteration** - No need to restart and rebuild context
- **Better debugging** - Test changes immediately
- **Preserve state** - Keep your conversation going
- **Real development workflow** - Edit code like you normally would

Happy developing! 🚀
