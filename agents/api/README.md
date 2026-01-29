# Agent REST API Server

A FastAPI-based REST server that exposes all agents as HTTP endpoints, supporting both stateless single-shot requests and stateful multi-turn conversations with persistent history.

## Features

### 🔄 Two Usage Patterns

**Stateless Mode**: Fire a single prompt at an agent and get a response
- Fresh agent created per request
- No conversation history
- Simple request/response pattern
- Perfect for one-off queries

**Stateful Sessions**: Multi-turn conversations with preserved context
- Persistent agent instance per session
- Conversation history maintained
- Session TTL with automatic cleanup
- Ideal for interactive conversations

### 🤖 Multi-Agent Support

Access all 5 agents via REST API:
- **chatbot**: General-purpose assistant with full tool access
- **pr**: PR and content strategy assistant
- **tasks**: Interactive task management (requires remote MCP)
- **security**: Security research assistant
- **business**: Business strategy and monetization advisor

### 📊 Token Tracking

- Per-request token usage (input + output)
- Session-level statistics
- Context window monitoring

### 🧹 Automatic Session Management

- In-memory session storage
- 1-hour TTL with automatic cleanup
- Background cleanup loop
- Manual session deletion available

## Quick Start

### Prerequisites

1. **Python 3.11 or higher**

2. **Anthropic API Key**:
   ```bash
   ANTHROPIC_API_KEY=your_key_here
   ```

3. **Optional**: Remote MCP server for task manager agent
   ```bash
   MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp
   ```

4. **Optional**: GitHub PAT for business advisor agent
   ```bash
   GITHUB_MCP_PAT=ghp_your_token
   ```

### Installation

```bash
# Install dependencies
uv sync
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional - Task Manager (requires remote MCP)
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp

# Optional - Business Advisor (GitHub analysis)
GITHUB_MCP_PAT=ghp_...

# Optional - For agents that use these
RAG_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_rag
OPENAI_API_KEY=sk-...
FASTMAIL_API_TOKEN=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Logging
LOG_LEVEL=INFO
```

### Running

```bash
# Start the REST API server
uv run python -m agents.api

# Server starts on http://localhost:8000
# API docs available at http://localhost:8000/docs
```

### Using uvicorn directly

```bash
# For production with more control
uv run uvicorn agents.api.server:app --host 0.0.0.0 --port 8000

# With auto-reload for development
uv run uvicorn agents.api.server:app --reload

# With multiple workers (production)
uv run uvicorn agents.api.server:app --workers 4
```

## API Endpoints

### Health & Discovery

#### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "ok",
  "agents_available": 5
}
```

**Example**:
```bash
curl http://localhost:8000/health
```

---

#### GET /agents

List all available agents.

**Response**:
```json
{
  "agents": [
    {
      "name": "chatbot",
      "description": "General-purpose chatbot with full MCP tool access"
    },
    {
      "name": "pr",
      "description": "PR and content strategy assistant"
    },
    {
      "name": "tasks",
      "description": "Interactive task management agent"
    },
    {
      "name": "security",
      "description": "Security research assistant"
    },
    {
      "name": "business",
      "description": "Business strategy and monetization advisor"
    }
  ]
}
```

**Example**:
```bash
curl http://localhost:8000/agents
```

---

### Stateless Mode

#### POST /agents/{agent_name}/message

Send a single message to an agent with no conversation history.

**Path Parameters**:
- `agent_name`: Agent to use (`chatbot`, `pr`, `tasks`, `security`, `business`)

**Request Body**:
```json
{
  "message": "Your message here"
}
```

**Response**:
```json
{
  "response": "Agent response text",
  "agent": "chatbot",
  "session_id": null,
  "usage": {
    "input_tokens": 150,
    "output_tokens": 75
  }
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/agents/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What is prompt injection?"}'
```

**Example Response**:
```json
{
  "response": "Prompt injection is a security vulnerability in LLM applications where an attacker crafts inputs that manipulate the model's behavior by overriding the system prompt or instructions. There are two main types:\n\n1. Direct prompt injection - User input directly overrides instructions\n2. Indirect prompt injection - Malicious instructions hidden in retrieved content\n\nCommon defenses include input validation, output filtering, and privilege separation.",
  "agent": "chatbot",
  "session_id": null,
  "usage": {
    "input_tokens": 1247,
    "output_tokens": 98
  }
}
```

---

### Stateful Sessions

#### POST /sessions

Create a new session with a persistent agent instance.

**Request Body**:
```json
{
  "agent": "chatbot"
}
```

**Response** (201 Created):
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "agent": "chatbot",
  "message_count": 0,
  "context_stats": {
    "message_count": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0
  }
}
```

**Example**:
```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent": "security"}'
```

---

#### POST /sessions/{session_id}/message

Send a message within an existing session.

**Path Parameters**:
- `session_id`: Session ID from session creation

**Request Body**:
```json
{
  "message": "Your message here"
}
```

**Response**:
```json
{
  "response": "Agent response with conversation context",
  "agent": "chatbot",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "usage": {
    "input_tokens": 250,
    "output_tokens": 120
  }
}
```

**Example Multi-Turn Conversation**:
```bash
# Create session
SESSION_ID=$(curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent": "chatbot"}' | jq -r '.session_id')

# First message
curl -X POST "http://localhost:8000/sessions/$SESSION_ID/message" \
  -H "Content-Type: application/json" \
  -d '{"message": "What are RAG systems?"}'

# Follow-up message (agent remembers previous context)
curl -X POST "http://localhost:8000/sessions/$SESSION_ID/message" \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the security risks?"}'

# Agent can reference "RAG systems" from earlier in conversation
```

---

#### GET /sessions/{session_id}

Get metadata about an active session.

**Path Parameters**:
- `session_id`: Session ID

**Response**:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "agent": "chatbot",
  "message_count": 5,
  "context_stats": {
    "message_count": 5,
    "total_input_tokens": 2430,
    "total_output_tokens": 890
  }
}
```

**Example**:
```bash
curl http://localhost:8000/sessions/$SESSION_ID
```

---

#### DELETE /sessions/{session_id}

End a session and free its resources.

**Path Parameters**:
- `session_id`: Session ID

**Response**: 204 No Content

**Example**:
```bash
curl -X DELETE http://localhost:8000/sessions/$SESSION_ID
```

---

## Available Agents

### chatbot
General-purpose AI assistant with access to all 29 MCP tools.

**Use for**:
- General questions and assistance
- Web content analysis
- Document search (RAG)
- Email management (FastMail)
- Memory across conversations
- Multi-domain tasks

**Example**:
```bash
curl -X POST http://localhost:8000/agents/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Fetch and summarize https://example.com/blog-post"}'
```

---

### pr
PR and content strategy assistant.

**Use for**:
- PR outreach strategy
- Content calendar planning
- Blog post ideas and drafts
- Social media content
- Audience analysis

**Example**:
```bash
curl -X POST http://localhost:8000/agents/pr/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Generate 5 tweet ideas about AI safety for security researchers"}'
```

---

### tasks
Interactive task management agent (requires remote MCP server).

**Use for**:
- Rescheduling overdue tasks
- Pre-researching upcoming tasks
- Task prioritization
- Task organization

**Requirements**: `MCP_SERVER_URL` environment variable set to remote MCP server with task management tools.

**Example**:
```bash
# Requires MCP_SERVER_URL configured
curl -X POST http://localhost:8000/agents/tasks/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What tasks do I have due this week?"}'
```

---

### security
AI security research assistant with RAG knowledge base.

**Use for**:
- Security research questions
- Blog post fact-checking
- Security reviews
- Vulnerability analysis
- Threat modeling

**Requirements**: RAG database (`RAG_DATABASE_URL`) and OpenAI API key for full functionality.

**Example**:
```bash
curl -X POST http://localhost:8000/agents/security/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain adversarial attacks on LLMs and common defenses"}'
```

---

### business
Business strategy and monetization advisor.

**Use for**:
- Business idea generation
- Monetization strategies
- Business plan development
- Market analysis

**Optional**: `GITHUB_MCP_PAT` for GitHub repository analysis.

**Example**:
```bash
curl -X POST http://localhost:8000/agents/business/message \
  -H "Content-Type: application/json" \
  -d '{"message": "I have a popular open-source CLI tool. How can I monetize it?"}'
```

---

## Session Management

### Session Lifecycle

1. **Creation**: POST /sessions creates new session with unique ID
2. **Active**: Session remains active with conversation history
3. **Touch**: Each message updates last_accessed timestamp
4. **TTL**: Sessions expire after 1 hour of inactivity
5. **Cleanup**: Background loop removes expired sessions every 10 minutes
6. **Manual deletion**: DELETE /sessions/{id} immediately removes session

### Session Storage

- In-memory storage (not persisted to disk)
- Server restart clears all sessions
- Each session contains:
  - Unique ID (UUID)
  - Agent instance with full conversation history
  - Creation timestamp
  - Last accessed timestamp

### Session Expiration

- **TTL**: 1 hour (3600 seconds)
- **Cleanup interval**: 10 minutes
- Expired sessions are automatically removed
- Accessing expired session returns 404

**Extending session lifetime**:
- Send any message to update last_accessed
- Create new session if expired

---

## Usage Examples

### Example 1: Simple Stateless Query

```bash
# Single question, no history needed
curl -X POST http://localhost:8000/agents/chatbot/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the OWASP Top 10 for LLMs?"}'
```

---

### Example 2: Multi-Turn Stateful Conversation

```python
import requests
import json

BASE_URL = "http://localhost:8000"

# Create session
session_response = requests.post(
    f"{BASE_URL}/sessions",
    json={"agent": "security"}
)
session_id = session_response.json()["session_id"]
print(f"Session created: {session_id}")

# First message
response1 = requests.post(
    f"{BASE_URL}/sessions/{session_id}/message",
    json={"message": "I'm building a RAG-based chatbot. What security risks should I consider?"}
)
print(response1.json()["response"])

# Follow-up (agent remembers we're discussing RAG chatbot)
response2 = requests.post(
    f"{BASE_URL}/sessions/{session_id}/message",
    json={"message": "How do I defend against prompt injection through retrieved documents?"}
)
print(response2.json()["response"])

# Check session stats
session_info = requests.get(f"{BASE_URL}/sessions/{session_id}")
print(f"Messages: {session_info.json()['message_count']}")
print(f"Tokens: {session_info.json()['context_stats']}")

# Clean up
requests.delete(f"{BASE_URL}/sessions/{session_id}")
```

---

### Example 3: Using Different Agents

```bash
# Business advice
curl -X POST http://localhost:8000/agents/business/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyze github.com/user/popular-repo for monetization opportunities"}'

# PR strategy
curl -X POST http://localhost:8000/agents/pr/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Create a 2-week content calendar for launching a new AI security product"}'

# Task management (requires remote MCP)
curl -X POST http://localhost:8000/agents/tasks/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Reschedule my overdue tasks evenly across next week"}'
```

---

### Example 4: JavaScript/Node.js Client

```javascript
const BASE_URL = 'http://localhost:8000';

async function chatWithAgent(agentName, messages) {
  // Create session
  const sessionRes = await fetch(`${BASE_URL}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent: agentName })
  });
  const { session_id } = await sessionRes.json();

  // Send messages
  const responses = [];
  for (const message of messages) {
    const msgRes = await fetch(`${BASE_URL}/sessions/${session_id}/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message })
    });
    const data = await msgRes.json();
    responses.push(data.response);
  }

  // Clean up
  await fetch(`${BASE_URL}/sessions/${session_id}`, { method: 'DELETE' });

  return responses;
}

// Usage
const responses = await chatWithAgent('chatbot', [
  'What is semantic search?',
  'How does it differ from keyword search?',
  'What are common use cases?'
]);

responses.forEach((r, i) => console.log(`Response ${i + 1}: ${r}`));
```

---

## Configuration

### Environment Variables

```bash
# Core (Required)
ANTHROPIC_API_KEY=sk-ant-...

# Task Manager Agent (requires remote MCP)
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp

# Business Advisor (optional GitHub analysis)
GITHUB_MCP_PAT=ghp_...

# Security Researcher (RAG functionality)
RAG_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_rag
OPENAI_API_KEY=sk-...

# Optional - Other agent features
MEMORY_BACKEND=file  # or "database"
MEMORY_DATABASE_URL=postgresql://...
FASTMAIL_API_TOKEN=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Logging
LOG_LEVEL=INFO
```

### Customizing Session TTL

Edit `agents/api/sessions.py`:

```python
SESSION_TTL = 7200  # 2 hours instead of 1
CLEANUP_INTERVAL = 600  # 10 minutes
```

### Adding New Agents

Edit `agents/api/server.py` in `_build_registry()`:

```python
def _build_registry():
    from agents.your_agent.main import YourAgent

    return {
        # Existing agents...
        "youragent": (
            YourAgent,
            None,  # or kwargs dict
            "Your agent description",
        ),
    }
```

Agent automatically available at `/agents/youragent/message`.

---

## Troubleshooting

### Server Won't Start

```bash
# Check if port 8000 is in use
lsof -i :8000

# Use different port
uv run uvicorn agents.api.server:app --port 8080

# Check environment variables
env | grep -E '(ANTHROPIC|MCP|RAG)'
```

### Agent Returns 404

```bash
# List available agents
curl http://localhost:8000/agents

# Check agent name spelling
# Valid: chatbot, pr, tasks, security, business
```

### Session Not Found

Possible causes:
- Session expired (1 hour TTL)
- Server restarted (sessions are in-memory only)
- Wrong session ID

**Solution**: Create new session.

### Task Manager Agent Fails

Requires remote MCP server:

```bash
# Verify MCP_SERVER_URL is set
echo $MCP_SERVER_URL

# Test MCP server connectivity
curl https://mcp.brooksmcmillin.com/mcp/health

# Check logs for connection errors
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log
```

### Security Agent Missing RAG

Requires PostgreSQL + OpenAI:

```bash
# Test database
psql $RAG_DATABASE_URL -c "SELECT COUNT(*) FROM documents"

# Verify OpenAI key
echo $OPENAI_API_KEY
```

### High Memory Usage

Sessions are kept in memory. If running many long sessions:

1. Reduce SESSION_TTL
2. Manually delete sessions when done
3. Monitor with `/health` endpoint
4. Restart server to clear sessions

---

## Architecture

### Components

- **FastAPI**: REST framework
- **Pydantic**: Request/response validation
- **SessionManager**: In-memory session storage with TTL
- **Agent Framework**: Shared agent infrastructure
- **MCP Clients**: Local stdio and remote HTTP/SSE

### Request Flow

**Stateless**:
```
Client → POST /agents/{name}/message
       → Create fresh agent
       → Process message
       → Return response
       → Discard agent
```

**Stateful**:
```
Client → POST /sessions → SessionManager creates session with agent
       → POST /sessions/{id}/message → SessionManager retrieves session
       → Agent processes with history → Response returned
       → Session touched (TTL reset)
```

### Session Cleanup

Background asyncio task runs every 10 minutes:
```python
while True:
    await asyncio.sleep(CLEANUP_INTERVAL)
    session_mgr.cleanup_expired()  # Remove sessions > 1 hour old
```

---

## Deployment

### Production Considerations

**Use multiple workers**:
```bash
uv run uvicorn agents.api.server:app --workers 4 --host 0.0.0.0 --port 8000
```

**Add reverse proxy** (nginx, caddy):
```nginx
location /api/ {
    proxy_pass http://localhost:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

**Environment variables**:
- Set all required API keys
- Configure remote MCP if needed
- Set appropriate LOG_LEVEL

**Monitoring**:
- Health check: GET /health
- Session count: Track via metrics
- Token usage: Monitor per-request usage stats

**Persistence** (if needed):
- Current sessions are in-memory only
- For persistent sessions, extend SessionManager to use Redis/database
- Save/restore session state across restarts

**Security**:
- Add authentication middleware
- Rate limiting per client
- API key validation
- CORS configuration
- HTTPS in production

**Scaling**:
- Each worker process has independent session storage
- For shared sessions across workers, use Redis
- Load balance across multiple server instances
- Consider agent startup time (lazy loading helps)

---

## Development

### Running with Auto-Reload

```bash
uv run uvicorn agents.api.server:app --reload
```

Changes to code automatically reload server.

### API Documentation

FastAPI auto-generates docs:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

### Testing

```bash
# Unit tests (TODO: implement)
uv run pytest tests/test_api.py

# Manual testing
curl http://localhost:8000/health

# Load testing
ab -n 100 -c 10 http://localhost:8000/agents/chatbot/message
```

---

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Project overview and development guide
- [Agent Documentation](../) - Individual agent READMEs
- [agent-framework](../../packages/agent-framework/) - Shared library
- [REMOTE_MCP.md](../../REMOTE_MCP.md) - Remote MCP setup for task manager
- [Testing Guide](../../docs/TESTING.md) - Testing and debugging

---

## License

See project LICENSE file.
