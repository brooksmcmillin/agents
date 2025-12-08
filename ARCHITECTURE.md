# PR Agent Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           USER                                       │
│                    (Interactive CLI)                                 │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                │ User Input
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AGENT APPLICATION                               │
│                    (agent/main.py)                                   │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              PR Agent Orchestrator                           │   │
│  │                                                               │   │
│  │  • Manages conversation history                              │   │
│  │  • Tracks token usage                                        │   │
│  │  • Implements agentic loop                                   │   │
│  └───────────────────┬─────────────────────────────────────────┘   │
│                      │                                               │
│                      │ Messages + Available Tools                    │
│                      ▼                                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │         ANTHROPIC CLAUDE API                                 │   │
│  │         (Claude Sonnet 4.5)                                  │   │
│  │                                                               │   │
│  │  • Understands user intent                                   │   │
│  │  • Decides which tools to use                                │   │
│  │  • Analyzes tool results                                     │   │
│  │  • Provides recommendations                                  │   │
│  └───────────────────┬─────────────────────────────────────────┘   │
│                      │                                               │
│                      │ Tool Calls / Text Responses                   │
│                      ▼                                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │          MCP Client (agent/mcp_client.py)                    │   │
│  │                                                               │   │
│  │  • Connects to MCP server                                    │   │
│  │  • Discovers available tools                                 │   │
│  │  • Executes tool calls                                       │   │
│  │  • Returns results to agent                                  │   │
│  └───────────────────┬─────────────────────────────────────────┘   │
└────────────────────────┼─────────────────────────────────────────────┘
                         │
                         │ MCP Protocol (stdio)
                         │
┌────────────────────────┼─────────────────────────────────────────────┐
│                        ▼                                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │          MCP Server (mcp_server/server.py)                   │   │
│  │                                                               │   │
│  │  • Exposes tools via MCP protocol                            │   │
│  │  • Validates tool inputs                                     │   │
│  │  • Routes to appropriate tool                                │   │
│  │  • Handles errors gracefully                                 │   │
│  └───────────────────┬─────────────────────────────────────────┘   │
│                      │                                               │
│                      │ Tool Execution                                │
│                      ▼                                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                   TOOLS                                       │  │
│  │                                                                │  │
│  │  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐ │  │
│  │  │ Web Analyzer   │  │ Social Media │  │ Content Suggest. │ │  │
│  │  │                │  │    Stats     │  │                  │ │  │
│  │  │ • Tone         │  │ • Twitter    │  │ • Blog topics    │ │  │
│  │  │ • SEO          │  │ • LinkedIn   │  │ • Tweet ideas    │ │  │
│  │  │ • Engagement   │  │ • Metrics    │  │ • LinkedIn posts │ │  │
│  │  └────────────────┘  └──────────────┘  └──────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                      │                                               │
│                      │ (Future: Real API calls)                      │
│                      ▼                                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              OAUTH HANDLER                                    │  │
│  │          (auth/oauth_handler.py)                              │  │
│  │                                                                │  │
│  │  • Authorization Code Flow                                    │  │
│  │  • Client Credentials Flow                                    │  │
│  │  • Automatic token refresh                                    │  │
│  └───────────────────┬──────────────────────────────────────────┘  │
│                      │                                               │
│                      │ Store/Retrieve Tokens                         │
│                      ▼                                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              TOKEN STORE                                      │  │
│  │           (auth/token_store.py)                               │  │
│  │                                                                │  │
│  │  • Encrypted storage (Fernet)                                 │  │
│  │  • File-based (easily migrated)                               │  │
│  │  • Token expiry management                                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                       │
│                      MCP SERVER COMPONENT                            │
└───────────────────────────────────────────────────────────────────────┘
                                │
                                │ (Future Integration)
                                ▼
                    ┌───────────────────────────┐
                    │   EXTERNAL APIs            │
                    │                            │
                    │  • Twitter/X API v2        │
                    │  • LinkedIn API            │
                    │  • Web Scraping            │
                    │  • NLP Services            │
                    │  • SEO Tools               │
                    └───────────────────────────┘
```

## Data Flow - Example Conversation

### User Request: "Analyze my blog for SEO"

```
1. User Input
   ↓
2. Agent (agent/main.py)
   • Adds message to conversation history
   • Calls Claude with available tools
   ↓
3. Claude API
   • Understands: User wants SEO analysis
   • Decides: Use analyze_website tool
   • Returns: Tool call request
   ↓
4. Agent
   • Receives tool call from Claude
   • Calls MCP Client
   ↓
5. MCP Client (agent/mcp_client.py)
   • Prepares tool call
   • Sends to MCP Server via stdio
   ↓
6. MCP Server (mcp_server/server.py)
   • Receives tool call: analyze_website
   • Validates parameters
   • Routes to web_analyzer.py
   ↓
7. Web Analyzer (mcp_server/tools/web_analyzer.py)
   • Analyzes content (currently mock data)
   • Returns SEO analysis with:
     - SEO score
     - Title optimization
     - Content quality
     - Recommendations
   ↓
8. MCP Server
   • Packages results as JSON
   • Returns via stdio
   ↓
9. MCP Client
   • Receives results
   • Returns to Agent
   ↓
10. Agent
    • Adds tool result to conversation
    • Calls Claude again with results
    ↓
11. Claude API
    • Analyzes the SEO data
    • Formulates recommendations
    • Returns text response
    ↓
12. Agent
    • Receives final response
    • Displays to user
    ↓
13. User sees actionable SEO recommendations!
```

## Key Design Patterns

### 1. Agentic Loop Pattern

```python
while not done:
    response = claude.messages.create(
        messages=history,
        tools=available_tools
    )

    if response.stop_reason == "tool_use":
        # Execute tools
        results = execute_tools(response.tool_calls)
        # Add results to history
        history.append({"role": "user", "content": results})
        # Loop continues
    else:
        # Final response
        return response.content
```

### 2. MCP Tool Pattern

```python
# Server side (mcp_server/server.py)
@app.list_tools()
async def list_tools():
    return [Tool(name="...", description="...", inputSchema={...})]

@app.call_tool()
async def call_tool(name, arguments):
    result = await execute_tool(name, arguments)
    return [TextContent(text=json.dumps(result))]

# Client side (agent/mcp_client.py)
async with client.connect():
    result = await client.call_tool("tool_name", {...})
```

### 3. OAuth Token Refresh Pattern

```python
async def get_valid_token(platform):
    token = token_store.get_token(platform)

    if not token:
        return None  # Need to authenticate

    if token.is_expired():
        token = await refresh_token(platform)

    return token
```

## Component Responsibilities

### Agent Application (agent/)
- **Owns**: User interaction, conversation state, Claude integration
- **Responsibilities**:
  - Manage multi-turn conversations
  - Orchestrate tool usage
  - Track token usage
  - Format responses for user

### MCP Server (mcp_server/)
- **Owns**: Tool implementations, OAuth, external API integration
- **Responsibilities**:
  - Expose tools via MCP protocol
  - Manage authentication
  - Execute API calls
  - Return structured data

### OAuth Handler (mcp_server/auth/)
- **Owns**: OAuth flows, token lifecycle
- **Responsibilities**:
  - Generate authorization URLs
  - Exchange codes for tokens
  - Auto-refresh expired tokens
  - Secure token storage

## Extensibility Points

### Add New Tool
1. Create in `mcp_server/tools/your_tool.py`
2. Register in `mcp_server/server.py`
3. Automatically available to Claude!

### Change LLM
Replace `AsyncAnthropic` in `agent/main.py` with:
- OpenAI GPT-4
- Google Gemini
- Any LLM that supports tool calling

### Change Transport
MCP supports multiple transports:
- **stdio** (current) - Simple, local
- **HTTP/SSE** - For remote servers
- **WebSocket** - For bidirectional streaming

### Migrate Token Storage
Implement same interface:
```python
class DatabaseTokenStore:
    def get_token(platform, user_id): ...
    def save_token(platform, token_data, user_id): ...
    def delete_token(platform, user_id): ...
```

## Security Considerations

### Current Security
- ✅ Encrypted token storage (Fernet)
- ✅ File permissions (600)
- ✅ Env var for secrets
- ✅ Input validation on tools
- ✅ Error handling (don't leak sensitive data)

### Production Additions
- Add request rate limiting
- Implement request signing
- Use secret management service
- Add audit logging
- Validate OAuth redirect URIs
- Implement CSRF protection
- Use HTTPS for all external calls

## Performance Characteristics

### Token Usage (Typical Conversation)
- Initial message: ~1,500 input tokens (system prompt + tools)
- Each tool call: ~500-1,000 tokens
- Average conversation: 3,000-5,000 total tokens

### Latency
- Claude API call: 1-3 seconds
- MCP tool call: <100ms (mock data)
- Total response: 2-5 seconds

### Scalability
- **Current**: Single-user, local
- **Future**:
  - Deploy MCP server separately
  - Add caching layer
  - Use connection pooling
  - Implement request queuing

## Error Handling Strategy

```
User Request
    ↓
Try: Call Claude
    ↓
    ├─ Success → Process tool calls
    │     ↓
    │     ├─ Try: Execute MCP tool
    │     │     ↓
    │     │     ├─ Success → Continue
    │     │     ├─ Auth Error → Prompt re-auth
    │     │     └─ Other Error → Return error, continue
    │     │
    │     └─ All tools executed
    │
    └─ Failure → Return error message

All errors are logged and user sees helpful message
```

## Future Enhancements

1. **Streaming Responses** - Stream Claude's response as it's generated
2. **Conversation Persistence** - Save/load conversation history
3. **Multi-User Support** - Support multiple users with separate auth
4. **Web UI** - Build React/Gradio interface
5. **Tool Chaining** - Let tools call other tools
6. **Caching** - Cache API responses to reduce costs
7. **Monitoring** - Add metrics, alerting, and dashboards

---

This architecture provides a solid foundation for building production LLM applications with external tool integrations!
