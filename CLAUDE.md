# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a multi-agent system built with Claude (Anthropic SDK) and Model Context Protocol (MCP). The repository is structured to support multiple specialized agents that share common infrastructure:

**Architecture:**
1. **Agents** (`agents/`) - Individual agent implementations, each in its own subdirectory
   - `chatbot/` - General-purpose assistant with access to all 29 MCP tools
   - `pr_agent/` - PR and content strategy assistant
   - `security_researcher/` - AI security research expert with RAG knowledge base
   - `business_advisor/` - Business strategy and monetization advisor
   - `task_manager/` - Interactive task management agent
   - `code_reviewer/` - Batch code review runner (5 specialized review agents)
   - `email_intake/` - Email inbox monitor that routes tasks to appropriate agents
   - `notifier/` - Lightweight task notification script (Slack)
2. **API Server** (`api/`) - REST API server providing HTTP access to agents
3. **Web UI** (`webui/`) - Modern React web interface for agents (requires Node.js)
4. **Entry Points** (`bin/`) - Executable scripts for running agents and services
5. **MCP Server** (`mcp_server/`) - Local MCP server configuration and OAuth infrastructure
6. **Infrastructure** (`infra/`) - Grafana, Loki, Promtail configs
7. **Documentation** (`docs/`) - Project documentation and guides
8. **Shared Utilities** (`shared/`) - Common code reusable across all agents
9. **Packages** (`packages/`) - Internal libraries in monorepo structure:
   - `agent-framework/` - Shared library containing:
     - MCP tools (web analysis, social media, memory, etc.)
     - Security utilities (SSRF protection)
     - Base agent classes and MCP client
   - `chasm/` - Voice interface for agent-framework agents (Deepgram + Cartesia) - optional dependency
10. **Runtime Data** (`.data/`) - Runtime data (logs, memories, tokens)

## Development Setup

This project uses `uv` for dependency management:

```bash
# Install dependencies
uv sync

# Optional: Install voice interface dependencies (requires PortAudio system library)
uv sync --group voice

# Run the chatbot (general-purpose assistant)
uv run python -m agents.chatbot.main

# Run the PR agent
uv run python -m agents.pr_agent.main

# Run the security researcher (requires RAG database + OpenAI)
uv run python -m agents.security_researcher.main

# Run the business advisor agent
uv run python -m agents.business_advisor.main

# Run the task manager agent (requires remote MCP server)
uv run python -m agents.task_manager.main

# Run code review on a directory (sends email report)
uv run python -m agents.code_reviewer.main /path/to/review --parallel
# Or just specific agents: --agents security,deps
# Or skip email: --no-email

# Run email intake agent (checks inbox and routes to agents)
uv run python -m agents.email_intake.main
# Interactive mode: --interactive
# Dry run (don't send replies): --dry-run

# Run the REST API server (HTTP access to agents)
uv run python -m api

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

## Web UI

The project includes a modern React web interface for interacting with agents:

```bash
# Development mode (requires Node.js 18+)
cd webui/frontend
npm install
npm run dev
# Opens on http://localhost:5173 (dev server with hot reload)

# Production build
cd webui/frontend
npm run build
# Output: webui/dist/

# Start server (serves both API and web UI)
uv run python -m api
# Visit http://localhost:8080
```

**Features:**
- Choose from 5 agents (chatbot, PR, tasks, security, business)
- Persistent conversations backed by PostgreSQL
- Create, rename, delete conversations
- Real-time chat with token usage tracking
- Dark mode with localStorage persistence
- Responsive design

**Tech Stack:**
- React 18 + TypeScript + Vite
- Tailwind CSS 3 with typography and forms plugins
- Zustand for state management
- Headless UI for accessible components
- Heroicons for icons

See [webui/README.md](webui/README.md) for detailed documentation.

## REST API Server

The project includes a FastAPI REST server that exposes agents via HTTP endpoints:

```bash
# Start the REST API server
uv run python -m api
# Runs on http://localhost:8080
# API docs at http://localhost:8080/docs
```

### API Endpoints

**Stateless (single-turn):**
```
POST /agents/{agent_name}/message  {"message": "..."}
```

**Stateful Sessions (in-memory):**
```
POST   /sessions              {"agent": "chatbot"}
POST   /sessions/{id}/message {"message": "..."}
GET    /sessions/{id}
DELETE /sessions/{id}
```

**Persistent Conversations (database-backed):**
Requires `DATABASE_URL` environment variable pointing to PostgreSQL.
```
GET    /conversations                    # List conversations
POST   /conversations                    # Create new
GET    /conversations/{id}               # Get with messages
POST   /conversations/{id}/message       # Send message
PATCH  /conversations/{id}               # Update title/metadata
DELETE /conversations/{id}               # Delete
POST   /conversations/{id}/clear         # Clear messages
GET    /conversations/{id}/export        # Export as JSON
GET    /conversations/{id}/messages      # Paginated messages
GET    /conversations/stats              # Storage statistics
```

### Conversation Persistence

To enable persistent conversations that survive server restarts:

1. Set up PostgreSQL database
2. Add to `.env`:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/agents
   ```
3. Tables are created automatically on first startup

**Database Schema:**
```sql
-- Created automatically by DatabaseConversationStore.initialize()

CREATE TABLE conversations (
    id VARCHAR(36) PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL,
    title VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE conversation_messages (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    role VARCHAR(20) NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    token_count INTEGER,
    UNIQUE(conversation_id, turn_number)
);

-- Indexes for efficient queries
CREATE INDEX idx_conversations_agent_name ON conversations(agent_name);
CREATE INDEX idx_conversations_updated_at ON conversations(updated_at DESC);
CREATE INDEX idx_messages_conversation_id ON conversation_messages(conversation_id);
CREATE INDEX idx_messages_turn ON conversation_messages(conversation_id, turn_number);
```

**Migration Notes:**
If you prefer Alembic migrations, create a migration with the above schema. The auto-creation uses `IF NOT EXISTS` so it's safe to run alongside migrations.

## Architecture

### Component Communication Flow

**Local Setup (Default):**
```
User Input → Agent (agents/*/main.py) → Claude API (Sonnet 4.5) → agent-framework (MCP Client)
                ↑                                                          ↓
                │                                                  MCP Server (stdio)
                │                                                          ↓
                └─────────────── Tool Results ←───────────────── Tools (agent-framework/tools/)
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
- See [REMOTE_MCP.md](docs/REMOTE_MCP.md) for setup guide

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

The MCP server exposes **40 tools** across 11 categories (defined in `packages/agent-framework/agent_framework/tools/`):

### Web Analysis Tools (2 tools)
- `fetch_web_content` - Fetch web content as clean markdown for LLM reading and analysis
- `analyze_website` - Web content analysis (tone, SEO, engagement) - uses real web scraping

### Memory Tools (6 tools)
- `save_memory` - Save information with key/value/category/tags/importance (1-10 scale)
- `get_memories` - Retrieve memories with filtering by category/tags/importance
- `search_memories` - Search memories by keyword
- `delete_memory` - Delete a memory by key
- `get_memory_stats` - Get memory system statistics
- `configure_memory_store` - Configure memory backend (file or database)

### RAG Document Search Tools (6 tools)
*Requires PostgreSQL database and OpenAI API key for embeddings*
- `add_document` - Add document to knowledge base for semantic search
- `search_documents` - Search documents by query with similarity threshold
- `get_document` - Retrieve full document by ID
- `list_documents` - List all documents in knowledge base
- `delete_document` - Delete document by ID
- `get_rag_stats` - Get RAG system statistics

### FastMail Email Tools (9 tools)
*Requires FastMail API token and account ID*
- `list_mailboxes` - List all mailboxes
- `get_emails` - Get emails from a mailbox
- `get_email` - Get single email by ID
- `search_emails` - Search emails by query
- `send_email` - Send an email with to/cc/bcc/subject/body (supports identity_email for sender selection)
- `send_agent_report` - Send report/notification from agent to admin (auto-injects agent email and admin recipient)
- `move_email` - Move email to different mailbox
- `update_email_flags` - Update email flags (seen, flagged)
- `delete_email` - Delete an email

### Communication Tools (1 tool)
- `send_slack_message` - Send Slack notification via webhook

### Twilio SMS Tools (2 tools)
*Requires Twilio Account SID, Auth Token, Phone Number, and Admin Phone Number*
- `send_sms_to_admin` - Send SMS notification to admin phone number (security-restricted)
- `get_sms_status` - Get delivery status of a previously sent SMS message

### Twilio SMS Clarification Tools (3 tools)
*Requires DATABASE_URL and TWILIO_PHONE_POOL for two-way SMS conversations*
- `send_sms_clarification` - Send SMS to admin requesting clarification with automatic reply routing
- `get_sms_clarification_status` - Check status of pending SMS clarification for a conversation
- `get_sms_phone_pool_status` - Get current status of the SMS phone pool including availability

### Social Media Tools (1 tool)
- `get_social_media_stats` - Social media metrics (Twitter, LinkedIn) - currently uses mock data, ready for OAuth integration

### Content Suggestion Tools (1 tool)
- `suggest_content_topics` - Content idea generation - currently uses mock data

### Claude Code Automation Tools (5 tools)
- `run_claude_code` - Run headless Claude Code instance in a workspace with a command
- `list_claude_code_workspaces` - List all available workspace folders
- `create_claude_code_workspace` - Create new workspace, optionally clone git repo
- `delete_claude_code_workspace` - Delete workspace folder (checks for uncommitted changes)
- `get_claude_code_workspace_status` - Get detailed workspace status (git, files, size)

**Workspace Directory:** Configurable via `CLAUDE_CODE_WORKSPACES_DIR` env var (default: `~/.claude_code_workspaces/`)

**Use Cases:**
- Meta-programming: Agents can spawn Claude Code to work on isolated codebases
- Batch processing: Run same task across multiple project workspaces
- Code review automation: Clone repos, run analysis, collect results
- Testing automation: Create test environments, run tests, cleanup

**See:** `docs/CLAUDE_CODE_TOOLS.md` for comprehensive documentation and examples.

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

**Send Email via FastMail:**
```python
# Send an email (requires FASTMAIL_API_TOKEN and FASTMAIL_ACCOUNT_ID)
result = await send_email(
    to=["recipient@example.com"],
    subject="Meeting Summary",
    body="Here's a summary of our discussion...",
    cc=["team@example.com"],  # optional
)

# Returns:
# {
#     "id": "email_id",
#     "status": "sent",
#     "to": ["recipient@example.com"]
# }

# Search emails
results = await search_emails(
    query="meeting notes",
    limit=10
)

# Get emails from inbox
emails = await get_emails(
    mailbox_id="inbox",
    limit=50
)
```

This is perfect for:
- Automated email notifications and reminders
- Processing incoming emails for information extraction
- Managing email workflows programmatically
- Email-based task and project management

**Send Agent Reports to Admin:**
```python
# Agents can send reports/notifications to the admin
# The from address is auto-derived from agent name (e.g., chatbot@brooksmcmillin.com)
# The to address is auto-filled from ADMIN_EMAIL_ADDRESS env var
result = await send_agent_report(
    subject="Daily Task Summary - Jan 30, 2026",
    body="""
    Completed tasks today:
    - Processed 15 customer inquiries
    - Updated 3 knowledge base articles
    - Flagged 2 items for human review

    Metrics:
    - Average response time: 2.3 seconds
    - Customer satisfaction: 94%
    """,
)

# Returns:
# {
#     "status": "success",
#     "email_id": "M12345",
#     "from_address": "chatbot@brooksmcmillin.com",
#     "to_address": "admin@example.com",
#     "message": "Email sent successfully to admin@example.com"
# }
```

**Agent Email Configuration:**
To enable agent email reports, configure these environment variables:
```bash
# Required: Admin email address (where reports are sent)
ADMIN_EMAIL_ADDRESS=you@example.com

# Optional: Domain for agent emails (default: brooksmcmillin.com)
AGENT_EMAIL_DOMAIN=brooksmcmillin.com

# Required: FastMail API token
FASTMAIL_API_TOKEN=your_token_here

# Optional: Email intake agent address (for receiving task requests)
INTAKE_EMAIL_ADDRESS=tasks@brooksmcmillin.com

# REQUIRED for email intake: Shared secret to prevent spoofing attacks
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# Include this secret somewhere in your email body when sending tasks
INTAKE_SHARED_SECRET=your_random_secret_here
```

**Security Note:** The email intake agent requires a shared secret in the email body
to prevent email spoofing attacks. Without this, an attacker could forge emails
appearing to come from the admin address and execute arbitrary agent tasks.

You'll also need to set up email identities in FastMail for each agent:
- `chatbot@brooksmcmillin.com`
- `pr-agent@brooksmcmillin.com`
- `task-manager@brooksmcmillin.com`
- `email-intake@brooksmcmillin.com` (or your INTAKE_EMAIL_ADDRESS)
- etc.

The `agent_name` parameter is automatically injected by the Agent class, so agents
simply call the tool with subject and body - the from/to are handled automatically.

**Send SMS to Admin via Twilio:**
```python
# Send an SMS to the admin (requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
# TWILIO_PHONE_NUMBER, and ADMIN_PHONE_NUMBER)
# The agent_name is automatically injected by the Agent class
result = await send_sms_to_admin(
    body="Task completed: processed 15 customer inquiries with 94% satisfaction.",
)

# Returns:
# {
#     "success": True,
#     "message_sid": "SM1234567890abcdef",
#     "to": "+15559876543",  # ADMIN_PHONE_NUMBER
#     "from": "+15551234567",  # TWILIO_PHONE_NUMBER
#     "status": "queued",
#     "segments": 1,
#     "agent_name": "chatbot"
# }
# Message received: "[Chatbot] Task completed: processed 15 customer inquiries..."

# Check delivery status
status = await get_sms_status(message_sid="SM1234567890abcdef")

# Returns:
# {
#     "success": True,
#     "message_sid": "SM1234567890abcdef",
#     "status": "delivered",  # or "queued", "sent", "failed", "undelivered"
#     "to": "+15559876543",
#     "from": "+15551234567",
#     "date_sent": "2026-01-30T10:30:00Z"
# }
```

**Security Note:** For security, `send_sms_to_admin` can ONLY send messages to the
configured `ADMIN_PHONE_NUMBER`. This prevents agents from sending unsolicited
messages to arbitrary phone numbers, similar to how `send_agent_report` restricts
email recipients.

This is perfect for:
- Sending urgent alerts that need immediate attention
- Task completion notifications
- Error alerts and system status updates
- Time-sensitive notifications when email isn't fast enough

**Two-Way SMS Clarification (Agent-Admin Conversation):**

For scenarios where an agent needs to ask the admin for clarification and wait for a response,
use the SMS Clarification tools with a phone pool:

```python
# Agent requests clarification from admin
# Requires: DATABASE_URL, TWILIO_PHONE_POOL (comma-separated phone numbers)
result = await send_sms_clarification(
    question="Should I prioritize the security fix or the new feature?",
    conversation_id="conv-abc123",  # Required for reply routing
    timeout_minutes=30,  # Optional, defaults to 30
)

# Returns:
# {
#     "success": True,
#     "method": "sms",
#     "phone_number": "+15551234567",  # Pool phone used for this conversation
#     "message_sid": "SM...",
#     "expires_at": "2026-01-30T11:00:00",
#     "message": "Clarification request sent. The conversation will resume when the admin replies."
# }

# If no phones available, falls back to email:
# {
#     "success": True,
#     "method": "email",
#     "fallback_reason": "All SMS phone numbers are in use (pool exhausted)",
#     "email_id": "M12345"
# }

# Check status of pending clarification
status = await get_sms_clarification_status(conversation_id="conv-abc123")

# Check phone pool availability
pool_status = await get_sms_phone_pool_status()
# {
#     "configured": True,
#     "total_phones": 3,
#     "available": 2,
#     "locked": 1,
#     "phones": [...]
# }
```

**How the Phone Pool Works:**
1. When an agent calls `send_sms_clarification`, it acquires a phone from the pool
2. The phone is "locked" to that conversation until the admin replies or timeout expires
3. Admin receives SMS from that specific Twilio number
4. When admin replies, the webhook routes the reply to the correct conversation based on which phone received it
5. After processing the reply, the phone is released back to the pool

**Configuration for SMS Phone Pool:**
```bash
# .env
DATABASE_URL=postgresql://user:pass@localhost:5432/agents
TWILIO_PHONE_POOL=+15551234567,+15551234568,+15551234569  # Comma-separated
SMS_LOCK_TIMEOUT_MINUTES=30  # Optional, default 30
```

**Twilio Webhook Configuration:**
Configure your Twilio phone numbers to send incoming SMS to:
```
POST https://your-domain.com/webhooks/sms/incoming
```

**Adding a New Tool:**

1. Create implementation in `packages/agent-framework/agent_framework/tools/your_tool.py`:
```python
async def your_tool(param: str) -> dict[str, Any]:
    # Implementation
    return {"result": "data"}
```

2. Export from `packages/agent-framework/agent_framework/tools/__init__.py`:
```python
from .your_tool import your_tool

__all__ = [..., "your_tool"]
```

3. Register in `mcp_server/server.py`:
   - Import the tool from `agent_framework.tools`
   - Register with `server.register_tool()` in `setup_custom_tools()`
   - Tool automatically available to all agents that use this MCP server

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
- SQL schema examples available in agent-framework documentation

## Observability with Langfuse

The agent framework includes built-in observability via [Langfuse](https://langfuse.com), providing:
- **Traces** for each conversation turn with full context
- **Spans** for individual tool calls with inputs/outputs
- **Automatic LLM call instrumentation** via OpenTelemetry
- **Token usage and latency tracking**
- **Dashboard and alerting capabilities**

**Setup:**

1. Sign up for [Langfuse Cloud](https://cloud.langfuse.com) or [self-host](https://langfuse.com/docs/deployment/self-host)
2. Get your API keys from Project Settings
3. Add to `.env`:
   ```
   LANGFUSE_ENABLED=true
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   # Optional for self-hosted:
   # LANGFUSE_HOST=https://your-langfuse-instance.com
   ```
4. Restart your agent - traces will appear in the Langfuse dashboard

**What Gets Traced:**

| Event | Captured Data |
|-------|--------------|
| Message processing | Agent name, model, user/session IDs, iterations |
| Claude API calls | Full request/response (automatic via OpenTelemetry) |
| Tool executions | Tool name, arguments, output, errors, latency |
| Token usage | Input/output tokens per turn |

**Architecture:**

The observability module (`agent_framework/observability/`) uses:
- **Langfuse SDK** for trace management and span creation
- **OpenTelemetry Anthropic Instrumentor** for automatic Claude call tracing
- **Graceful degradation** - agents work normally if Langfuse is not configured

**Custom Tracing:**

For agents that extend the base `Agent` class, pass `user_id` and `session_id` to `process_message()` for better trace filtering:

```python
response = await agent.process_message(
    user_message,
    user_id="user-123",
    session_id="conv-456",
)
```

## Key Files and Responsibilities

**Agents:**
- `agents/chatbot/main.py` - General-purpose assistant with all 29 tools
- `agents/pr_agent/main.py` - PR agent implementation extending agent-framework
- `agents/security_researcher/main.py` - Security research expert with RAG
- `agents/business_advisor/main.py` - Business strategy and monetization advisor
- `agents/task_manager/main.py` - Task management with remote MCP
- `api/server.py` - REST API server for HTTP access to agents
- `agents/notifier/main.py` - Slack notification script
- `agents/*/prompts.py` - System prompts defining agent behavior and memory usage

**Shared Infrastructure:**
- `shared/` - Common utilities and base classes for all agents
- `packages/agent-framework/` - Internal library providing:
  - `agent_framework/tools/` - All 29 MCP tools organized in 8 modules (web, memory, RAG, email, social, slack, content)
  - `agent_framework/security/` - Security utilities (SSRF protection)
  - `agent_framework/server.py` - MCP server base classes
  - `agent_framework/core/` - Base Agent class and MCP client
- `packages/chasm/` - Voice interface library (Deepgram STT + Cartesia TTS) - optional dependency
  - Install with: `uv sync --group voice`
  - Requires PortAudio system library

**MCP Server:**
- `mcp_server/server.py` - MCP server configuration (registers agent-framework tools)
- `mcp_server/auth/` - OAuth handler and token storage (for future social media API integration)
- `mcp_server/config.py` - Configuration via pydantic-settings

## Development Workflow

**Editing Tools Without Restarting:**

1. Start agent: `uv run python -m agents.pr_agent.main`
2. Edit tool code in `packages/agent-framework/agent_framework/tools/*.py`
3. Save changes (changes affect all agents using the framework)
4. Next tool call automatically picks up changes
5. Type `reload` to force reconnection if needed

See `docs/HOT_RELOAD.md` for details.

**Note:** Tools are in the local agent-framework package, making them reusable across all agents in this monorepo.

**Testing and Debugging:**

See [docs/TESTING.md](docs/TESTING.md) for comprehensive testing and debugging guide, including:
- Memory system testing with `scripts/testing/test_memory.py`
- Backend configuration (file vs database)
- Log file locations and common error patterns
- Database connectivity testing
- Common issues and solutions

**Quick Debugging:**

```bash
# Test memory system
uv run python scripts/testing/test_memory.py stats

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
- 7 specialized agents with different capabilities
- 34 MCP tools across 9 categories (web, memory, RAG, email, communication, social, content, claude-code)
- Real web scraping and content analysis
- RAG document search with semantic similarity
- FastMail email integration
- Persistent memory across conversations (file or database backend)
- Hot reload for tool development
- OAuth infrastructure (ready for production integration)
- Token usage tracking
- Remote MCP support for distributed deployments
- REST API server for HTTP access to agents
- **Langfuse observability** for tracing, monitoring, and alerting
- Comprehensive error handling

**Production Readiness:**
- Social media tools use mock data - integrate Twitter/LinkedIn APIs via OAuth
- Add rate limiting for API endpoints
- Add multi-user support (user_id to memory/auth/RAG)
- Distributed deployment with remote MCP
- Security hardening for public-facing deployments

## Adding New Agents

**MANDATORY RULES — all new agents MUST follow these:**

1. **Subclass `Agent`** — Every agent must be a subclass of the `Agent` base class from `agent_framework`. Use either a direct subclass or `create_simple_agent()` from `shared/agent_factory.py` (which returns an `Agent` subclass).
2. **Register in `bin/run-agent`** — Every agent must be importable and registered in the `AGENTS` dict in `bin/run-agent` so it can be run via `uv run python bin/run-agent <name>`. No exceptions.
3. **Exportable agent class** — The agent's `main.py` must export the agent class (e.g., `YourAgent`) at module level so `bin/run-agent` can import it directly.

### Steps

1. **Create agent directory:**
   ```bash
   mkdir -p agents/your_agent
   ```

2. **Create main.py with an Agent subclass:**

   **Option A — Direct subclass** (when you need custom init logic):
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

   **Option B — Factory function** (for simple prompt/tool-list agents):
   ```python
   # agents/your_agent/main.py
   import asyncio
   from shared import create_simple_agent, run_agent
   from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

   YourAgent = create_simple_agent(
       name="YourAgent",
       system_prompt=SYSTEM_PROMPT,
       greeting=USER_GREETING_PROMPT,
       allowed_tools=["fetch_web_content", "save_memory"],
   )

   async def main():
       await run_agent(YourAgent)

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

5. **Register in `bin/run-agent`:**
   ```python
   # Add import at top of bin/run-agent
   from agents.your_agent.main import YourAgent

   # Add entry to the AGENTS dict
   AGENTS: dict[str, tuple[type, dict | None]] = {
       ...
       "your-agent": (YourAgent, None),  # or pass MCP config dict
       ...
   }
   ```

6. **Run your new agent:**
   ```bash
   uv run python bin/run-agent your-agent                # Interactive
   uv run python bin/run-agent your-agent "Your message"  # One-off
   ```

All agents automatically have access to the agent-framework tools via the MCP server. You can add agent-specific tools to agent-framework or create a custom MCP server configuration as needed.

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
# In packages/agent-framework/agent_framework/tools/social_media.py
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
# agent-framework already supports database memory backend
# Set environment variable: MEMORY_BACKEND=database
# Set database URL: MEMORY_DATABASE_URL=postgresql://user:pass@host:5432/dbname  # pragma: allowlist secret
# See agent-framework documentation for details
```
