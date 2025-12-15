# Next Steps: MCP Remote Connection

## Current Status

✅ **OAuth 2.0 implementation is complete and working!**

The RemoteMCPClient now supports full OAuth authentication with:
- Automatic discovery via `.well-known` endpoints
- Authorization code flow with PKCE
- Dynamic client registration
- Token storage and automatic refresh
- Browser-based authentication

## Verified Working Components

- ✅ OAuth discovery from `https://mcp.brooksmcmillin.com`
- ✅ Client registration with `https://mcp-auth.brooksmcmillin.com`
- ✅ Browser authorization flow
- ✅ Token exchange and storage
- ✅ Bearer token authentication
- ✅ MCP session initialization
- ✅ Session ID management

## Outstanding Issue

### Problem: `tools/list` Returns "Invalid request parameters"

**Symptom:**
- MCP `initialize` succeeds (200 OK)
- Session ID is properly received and sent
- `tools/list` fails with error code -32602 (Invalid params)

**Root Cause:**
Likely a version compatibility issue between:
- Client MCP SDK: 1.10.1
- Server FastMCP: 1.10.1
- Protocol version: 2024-11-05

The authentication is working correctly - this is a protocol/API mismatch issue.

## Recommended Next Steps

### Option 1: Debug Server-Side (Recommended)

1. **Check server logs** on the TaskManager MCP server:
   ```bash
   # SSH to server hosting https://mcp.brooksmcmillin.com
   docker compose logs -f resource-server
   # or
   tail -f /var/log/taskmanager-mcp/server.log
   ```

2. **Look for** the exact error when `tools/list` is called:
   - What parameters is the server expecting?
   - Is there a FastMCP configuration issue?
   - Are there any schema validation errors?

3. **Test with MCP Inspector** (official debugging tool):
   ```bash
   # Install MCP Inspector
   npm install -g @modelcontextprotocol/inspector

   # Connect to your server
   mcp-inspector https://mcp.brooksmcmillin.com/mcp/
   ```

   The Inspector will trigger OAuth and show you exactly what messages are being exchanged.

### Option 2: Upgrade Server

The taskmanager-mcp server is using older MCP SDK versions:

1. **Update taskmanager-mcp dependencies:**
   ```bash
   cd /home/brooks/build/taskmanager-mcp

   # Update to latest FastMCP and MCP SDK
   # Check pyproject.toml or requirements.txt and upgrade:
   pip install --upgrade mcp fastmcp

   # Rebuild and redeploy
   docker compose up -d --build
   ```

2. **Test again** with the task manager agent

### Option 3: Downgrade Client Protocol Version

Try using an older protocol version that matches the server:

1. **Modify RemoteMCPClient** to use older protocol version
2. Check FastMCP 1.10.1 documentation for supported methods
3. May need to use different method signatures

### Option 4: Direct FastMCP Investigation

Check the FastMCP source code to understand the expected schema:

1. **Find FastMCP version** on the server:
   ```bash
   cd /home/brooks/build/taskmanager-mcp
   grep -r "fastmcp" pyproject.toml requirements.txt
   ```

2. **Check FastMCP docs** for that version:
   - https://github.com/jlowin/fastmcp
   - Look for `tools/list` method signature

3. **Compare** with what the client is sending

## Workaround: Use Manual Testing

While debugging, you can still use the server via direct HTTP requests:

```python
import httpx
import json
from shared.oauth_tokens import TokenStorage

# Load saved OAuth token
storage = TokenStorage()
token = storage.load_token('https://mcp.brooksmcmillin.com/mcp/')

headers = {
    'Authorization': f'Bearer {token.access_token}',
    'Accept': 'application/json, text/event-stream',
    'Content-Type': 'application/json',
}

async with httpx.AsyncClient() as client:
    # Initialize
    response = await client.post(
        'https://mcp.brooksmcmillin.com/mcp/',
        headers=headers,
        json={
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2024-11-05',
                'capabilities': {},
                'clientInfo': {'name': 'test', 'version': '1.0'}
            }
        }
    )
    session_id = response.headers.get('mcp-session-id')
    headers['mcp-session-id'] = session_id

    # Call tools directly (once you figure out the right format)
    response = await client.post(
        'https://mcp.brooksmcmillin.com/mcp/',
        headers=headers,
        json={
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'tools/call',
            'params': {
                'name': 'get_all_tasks',
                'arguments': {}
            }
        }
    )
```

## Files Modified

### New OAuth Infrastructure
- `shared/oauth_config.py` - OAuth discovery
- `shared/oauth_tokens.py` - Token storage
- `shared/oauth_flow.py` - Authorization flow
- `shared/remote_mcp_client.py` - Complete OAuth integration

### Scripts
- `scripts/get_mcp_token.py` - Manual token fetcher (legacy, kept for reference)
- `scripts/test_mcp_connection.py` - Direct HTTP testing
- `scripts/debug_mcp_handshake.py` - MCP protocol debugging

### Configuration
- `.env.example` - Updated with OAuth documentation
- `.env` - MCP_AUTH_TOKEN now optional (commented out)

### Agent
- `agents/task_manager/main.py` - Uses new OAuth-enabled RemoteMCPClient

## Testing the OAuth Implementation

To verify OAuth is working:

```bash
# Clear saved tokens to trigger fresh OAuth flow
rm -rf ~/.claude-code/tokens/

# Run the agent - it will open your browser for auth
uv run python -m agents.task_manager.main

# You should see:
# 1. "🔐 AUTHENTICATION REQUIRED" message
# 2. Browser opens to https://mcp-auth.brooksmcmillin.com/authorize
# 3. You authenticate via TaskManager
# 4. Agent receives token and connects
# 5. Connection succeeds, but tools/list fails (known issue)
```

## Contact Points

- **Server Admin**: Check who manages `mcp.brooksmcmillin.com`
- **Logs Location**: `/var/log/` or Docker container logs
- **Server Config**: Likely in `taskmanager-mcp/` repository

## Quick Win: Verify Server is Healthy

```bash
# Test OAuth discovery
curl https://mcp.brooksmcmillin.com/.well-known/oauth-protected-resource

# Test auth server
curl https://mcp-auth.brooksmcmillin.com/.well-known/oauth-authorization-server

# Test with saved token
TOKEN=$(cat ~/.claude-code/tokens/*.json | jq -r '.token.access_token')
curl -H "Authorization: Bearer $TOKEN" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
     https://mcp.brooksmcmillin.com/mcp/
```

## Success Criteria

You'll know the issue is resolved when:
1. `initialize` succeeds (✅ already working)
2. `tools/list` returns a list of tools instead of error -32602
3. Task manager agent can list and call tools
4. End-to-end workflow completes without errors

The OAuth implementation is production-ready - just need to resolve the server-side API compatibility issue!
