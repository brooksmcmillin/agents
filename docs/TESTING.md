# Testing and Debugging Guide

This guide covers tools and techniques for testing and debugging the agents system.

## Memory System Testing

### Memory Backend Configuration

The memory system supports two backends configured via `.env`:

```bash
# File-based storage (default, recommended for local development)
MEMORY_BACKEND=file

# Database storage (PostgreSQL, for cross-machine portability)
MEMORY_BACKEND=database
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

**Common Issues:**
- **60+ second timeouts on memory operations** → Database backend configured but database unreachable
- **Fix:** Change `MEMORY_BACKEND=file` in `.env`

### Direct Memory Testing

Use `scripts/testing/test_memory.py` to test memory operations without running the full agent:

```bash
# Get memory statistics
uv run python scripts/testing/test_memory.py stats

# Get all memories
uv run python scripts/testing/test_memory.py get

# Get memories with filters
uv run python scripts/testing/test_memory.py get --category user_preference --min-importance 7 --limit 10

# Search memories by keyword
uv run python scripts/testing/test_memory.py search "user"

# Save a new memory
uv run python scripts/testing/test_memory.py save my_key "my value" --category fact --importance 7

# Save with tags
uv run python scripts/testing/test_memory.py save blog_url "https://example.com" \
  --category user_preference \
  --tags seo content \
  --importance 8

# Delete a memory
uv run python scripts/testing/test_memory.py delete my_key
```

**Example Output:**

```bash
$ uv run python scripts/testing/test_memory.py stats
{
  "status": "success",
  "backend": "file",
  "total_memories": 2,
  "categories": {
    "fact": 1,
    "user_preference": 1
  },
  "oldest_memory": "2026-01-15 23:54:53.616526",
  "newest_memory": "2026-01-15 23:54:54.580607"
}
```

### Memory Storage Location

**File Backend:**
- Location: `./memories/memories.json`
- Format: JSON with timestamps and metadata
- Can be manually edited (but preserve structure)

**Database Backend:**
- Table: `memories` in configured PostgreSQL database
- Includes local caching (5-minute TTL for individual items, 1-minute for queries)
- See `agent_framework/storage/database_memory_store.py` for schema

## MCP Tool Testing

### Testing MCP Tools (Experimental)

`scripts/testing/test_mcp_tool.py` attempts to call MCP tools directly via stdio transport:

```bash
# List available MCP tools
uv run python scripts/testing/test_mcp_tool.py --list

# Call a tool
uv run python scripts/testing/test_mcp_tool.py get_memories --args '{"limit": 5}' --pretty

# Call with verbose logging
uv run python scripts/testing/test_mcp_tool.py get_memories -v --pretty
```

**Status:** Currently has subprocess initialization issues with Python 3.13. Use `test_memory.py` instead for memory-related debugging.

### Testing Remote MCP Connections

For testing remote MCP servers (HTTP/SSE transport):

```bash
uv run python scripts/mcp_scripts/debug_mcp_handshake.py
```

This script:
- Loads OAuth tokens from token storage
- Tests HTTP connection to remote MCP server
- Shows detailed request/response logging
- Lists available tools if connection succeeds

## Agent Testing

### Quick Agent Tests

```bash
# Run an agent with a one-line test
echo "test message" | uv run python run_agent.py chatbot

# Run with timeout to avoid hanging
timeout 30s uv run python run_agent.py chatbot <<< "test"

# Run and check logs
uv run python run_agent.py chatbot
# Then check: ~/.agents/logs/agent_YYYY-MM-DD.log
```

### Log Files

All agents log to `~/.agents/logs/`:

```bash
# View today's agent log
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log

# Search for errors
grep ERROR ~/.agents/logs/agent_$(date +%Y-%m-%d).log

# Search for memory operations
grep "memory" ~/.agents/logs/agent_$(date +%Y-%m-%d).log -i
```

**Common log patterns:**
- `Failed to get memories:` → Database connection issue
- `MEMORY_BACKEND` → Shows which backend is active
- `MCP server running on stdio` → MCP server started successfully
- `Calling tool: get_memories` → Agent is using memory tools

## Database Connectivity Testing

### Test PostgreSQL Connection

```bash
# Quick connection test
uv run python -c "
import asyncio
import asyncpg

async def test():
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect('postgresql://user:pass@host:5432/db'),
            timeout=5
        )
        print('✅ Connected')
        await conn.close()
    except asyncio.TimeoutError:
        print('❌ Timeout')
    except Exception as e:
        print(f'❌ Error: {e}')

asyncio.run(test())
"
```

### Test Database Reachability

```bash
# Ping the host
ping -c 2 your-db-host.com

# Test port connectivity (requires nc/netcat)
nc -zv your-db-host.com 5432

# Using psql directly
psql postgresql://user:pass@host:5432/db -c "SELECT 1"
```

## Debugging Workflow

### Memory Not Working

1. **Check backend configuration:**
   ```bash
   grep MEMORY_BACKEND .env
   ```

2. **If using database backend, test connection:**
   ```bash
   # Use the connection test above
   ```

3. **Switch to file backend temporarily:**
   ```bash
   sed -i 's/MEMORY_BACKEND=database/MEMORY_BACKEND=file/' .env
   ```

4. **Test directly:**
   ```bash
   uv run python scripts/testing/test_memory.py stats
   ```

5. **Check agent logs:**
   ```bash
   tail -50 ~/.agents/logs/agent_$(date +%Y-%m-%d).log
   ```

### Agent Hangs or Times Out

1. **Check if it's a memory operation:**
   - Look for 60-second timeouts → Database backend issue
   - Fix: Switch to file backend

2. **Check MCP server startup:**
   ```bash
   # Run MCP server standalone
   uv run python -m mcp_server.server
   # Should print "MCP server running on stdio" and wait for input
   ```

3. **Check for environment variable issues:**
   ```bash
   # Verify .env is loaded
   grep -v '^#' .env | grep -v '^$'
   ```

### Tool Not Found Errors

1. **Check which tools are registered:**
   ```bash
   uv run python -m mcp_server.server 2>&1 | grep "Registered tool:"
   ```

2. **Verify tool is in allowed_tools list:**
   ```python
   # In agent code (e.g., agents/chatbot/main.py)
   # If allowed_tools is set, tool must be in the list
   ```

## Testing Checklist

Before committing changes or reporting issues:

- [ ] Memory operations work: `uv run python scripts/testing/test_memory.py stats`
- [ ] MCP server starts: `uv run python -m mcp_server.server` (Ctrl+C to stop)
- [ ] Agent starts: `timeout 10s uv run python run_agent.py chatbot <<< "test"`
- [ ] Check logs for errors: `tail ~/.agents/logs/agent_$(date +%Y-%m-%d).log`
- [ ] Environment variables set: `grep -E "(ANTHROPIC|MEMORY)_" .env`

## Performance Testing

### Memory Operation Benchmarks

```bash
# Time a memory operation
time uv run python scripts/testing/test_memory.py stats

# Should be < 0.1s for file backend
# > 60s indicates database timeout issue
```

### Agent Response Time

```bash
# Time a simple agent interaction
time echo "hello" | uv run python run_agent.py chatbot

# First message includes tool discovery overhead
# Subsequent messages in same session are faster
```

## Common Issues and Solutions

### Issue: "Failed to get memories" with no error message

**Cause:** Database connection timeout (default 60s)

**Solution:**
```bash
# Switch to file backend
echo "MEMORY_BACKEND=file" >> .env
```

### Issue: "Relative module names not supported"

**Cause:** Python trying to run MCP server as relative import

**Solution:** Ensure running from project root:
```bash
cd /home/brooks/build/agents
uv run python run_agent.py chatbot
```

### Issue: Package name collision (e.g., `mcp` module not found)

**Cause:** Local directory named `mcp` conflicts with PyPI package

**Solution:** Rename the directory:
```bash
mv scripts/mcp scripts/mcp_scripts
```

### Issue: Memory file permission errors

**Cause:** Memory file created by different user/process

**Solution:**
```bash
# Check permissions
ls -la memories/memories.json

# Fix permissions
chmod 644 memories/memories.json
```

## Advanced Testing

### Testing with Different Memory Backends

```bash
# Test file backend
MEMORY_BACKEND=file uv run python scripts/testing/test_memory.py stats

# Test database backend (requires valid DATABASE_URL)
MEMORY_BACKEND=database DATABASE_URL=postgresql://... uv run python scripts/testing/test_memory.py stats
```

### Testing Memory Across Sessions

```bash
# Save a memory
uv run python scripts/testing/test_memory.py save session_test "Value from script" --importance 9

# Start agent and check if it can retrieve it
uv run python run_agent.py chatbot
> "Do you remember the session_test memory?"
```

### Manually Inspecting Memory Storage

**File Backend:**
```bash
# Pretty-print the JSON
cat memories/memories.json | python -m json.tool

# Search for specific key
cat memories/memories.json | python -m json.tool | grep -A 5 "my_key"
```

**Database Backend:**
```bash
# Connect to database
psql $DATABASE_URL

# Query memories
SELECT key, value, category, importance FROM memories ORDER BY updated_at DESC LIMIT 10;
```

## Related Documentation

- [VOICE_AGENTS.md](VOICE_AGENTS.md) - Voice-enabled agent testing
- [CLAUDE.md](CLAUDE.md) - Main project documentation
- [agent-framework](../agent-framework/) - Core framework testing
- [HOT_RELOAD.md](HOT_RELOAD.md) - Development workflow with hot reload

## Getting Help

If you encounter issues:

1. Check the logs: `~/.agents/logs/agent_$(date +%Y-%m-%d).log`
2. Test memory directly: `uv run python scripts/testing/test_memory.py stats`
3. Verify environment: `grep -v '^#' .env | grep -v '^$'`
4. Check this guide for common issues
5. Report with log excerpts and test script output
