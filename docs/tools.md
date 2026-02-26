# MCP Tools Reference

The MCP server exposes **52 tools** across 13 categories (defined in `packages/agent-framework/agent_framework/tools/`).

## Web Analysis Tools (2 tools)
- `fetch_web_content` - Fetch web content as clean markdown for LLM reading and analysis
- `analyze_website` - Web content analysis (tone, SEO, engagement) - uses real web scraping

## Memory Tools (6 tools)
- `save_memory` - Save information with key/value/category/tags/importance (1-10 scale)
- `get_memories` - Retrieve memories with filtering by category/tags/importance
- `search_memories` - Search memories by keyword
- `delete_memory` - Delete a memory by key
- `get_memory_stats` - Get memory system statistics
- `configure_memory_store` - Configure memory backend (file or database)

## RAG Document Search Tools (6 tools)
*Requires PostgreSQL database and OpenAI API key for embeddings*
- `add_document` - Add document to knowledge base for semantic search
- `search_documents` - Search documents by query with similarity threshold
- `get_document` - Retrieve full document by ID
- `list_documents` - List all documents in knowledge base
- `delete_document` - Delete document by ID
- `get_rag_stats` - Get RAG system statistics

## FastMail Email Tools (9 tools)
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

## Communication Tools (1 tool)
- `send_slack_message` - Send Slack notification via webhook

## Twilio SMS Tools (2 tools)
*Requires Twilio Account SID, Auth Token, Phone Number, and Admin Phone Number*
- `send_sms_to_admin` - Send SMS notification to admin phone number (security-restricted)
- `get_sms_status` - Get delivery status of a previously sent SMS message

## Twilio SMS Clarification Tools (3 tools)
*Requires DATABASE_URL and TWILIO_PHONE_POOL for two-way SMS conversations*
- `send_sms_clarification` - Send SMS to admin requesting clarification with automatic reply routing
- `get_sms_clarification_status` - Check status of pending SMS clarification for a conversation
- `get_sms_phone_pool_status` - Get current status of the SMS phone pool including availability

## Social Media Tools (1 tool)
- `get_social_media_stats` - Social media metrics (Twitter, LinkedIn) - currently uses mock data, ready for OAuth integration

## Content Suggestion Tools (1 tool)
- `suggest_content_topics` - Content idea generation - currently uses mock data

## Claude Code Automation Tools (5 tools)
- `run_claude_code` - Run headless Claude Code instance in a workspace with a command
- `list_claude_code_workspaces` - List all available workspace folders
- `create_claude_code_workspace` - Create new workspace, optionally clone git repo
- `delete_claude_code_workspace` - Delete workspace folder (checks for uncommitted changes)
- `get_claude_code_workspace_status` - Get detailed workspace status (git, files, size)

**Workspace Directory:** Configurable via `CLAUDE_CODE_WORKSPACES_DIR` env var (default: `~/.claude_code_workspaces/`)

**See:** `docs/CLAUDE_CODE_TOOLS.md` for comprehensive documentation and examples.

## HTTP Client Tools (7 tools)
*Requires `REDTEAM_ALLOWED_TARGETS` env var (fail-secure: denied when unset)*
- `http_request` - Make HTTP requests with full control over method, headers, cookies, and body
- `http_session_login` - POST credentials to a login endpoint and store session cookies
- `http_upload_file` - Upload files via multipart form data (max 10 MB, base64-encoded)
- `http_inspect_headers` - Analyze response headers for security configuration (CSP, HSTS, CORS, cookie attributes)
- `http_fuzz_parameter` - Send parameter variations to detect injection vulnerabilities
- `http_check_rate_limit` - Send rapid identical requests to test rate limiting
- `http_clear_session` - Clear a named session's cookies and state

## Markdown File Tools (4 tools)
- `list_markdown_files` - List markdown files in agent workspace
- `read_markdown_file` - Read markdown file contents
- `write_markdown_file` - Write/create markdown file contents
- `delete_markdown_file` - Delete a markdown file

## Filesystem Tools (6 tools)
*Requires `FILESYSTEM_ALLOWED_DIRS` env var (fail-secure: denied when unset)*
- `read_file` - Read file contents with line numbers (cat -n style)
- `list_directory` - List directory entries with type and size
- `glob_files` - Search for files by glob pattern
- `grep_files` - Search file contents by regex pattern with ReDoS protection
- `write_file` - Write text content to a file (create or overwrite), optionally creating parent directories
- `edit_file` - Edit a file by finding and replacing an exact string match (unique or replace-all)

## Tool Usage Examples

### Fetch and Read Web Content
```python
result = await fetch_web_content(
    url="https://example.com/article",
    max_length=50000  # optional, defaults to 50000
)
# Returns: {url, title, content (clean markdown), word_count, char_count, has_images, has_links}
```

### Send Email via FastMail
```python
result = await send_email(
    to=["recipient@example.com"],
    subject="Meeting Summary",
    body="Here's a summary of our discussion...",
    cc=["team@example.com"],  # optional
)

results = await search_emails(query="meeting notes", limit=10)
emails = await get_emails(mailbox_id="inbox", limit=50)
```

### Send Agent Reports to Admin
```python
# From address auto-derived from agent name (e.g., chatbot@brooksmcmillin.com)
# To address auto-filled from ADMIN_EMAIL_ADDRESS env var
result = await send_agent_report(
    subject="Daily Task Summary",
    body="Completed tasks today: ...",
)
```

**Agent Email Configuration:**
```bash
ADMIN_EMAIL_ADDRESS=you@example.com
AGENT_EMAIL_DOMAIN=brooksmcmillin.com  # optional, default
FASTMAIL_API_TOKEN=your_token_here
INTAKE_EMAIL_ADDRESS=tasks@brooksmcmillin.com  # optional
INTAKE_SHARED_SECRET=your_random_secret_here   # REQUIRED for email intake
```

**Security Note:** The email intake agent requires a shared secret in the email body
to prevent email spoofing attacks.

### Send SMS to Admin via Twilio
```python
result = await send_sms_to_admin(
    body="Task completed: processed 15 customer inquiries.",
)
status = await get_sms_status(message_sid="SM1234567890abcdef")
```

**Security Note:** `send_sms_to_admin` can ONLY send messages to the configured
`ADMIN_PHONE_NUMBER`.

### Two-Way SMS Clarification
```python
result = await send_sms_clarification(
    question="Should I prioritize the security fix or the new feature?",
    conversation_id="conv-abc123",
    timeout_minutes=30,
)
status = await get_sms_clarification_status(conversation_id="conv-abc123")
pool_status = await get_sms_phone_pool_status()
```

**Configuration:**
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/agents
TWILIO_PHONE_POOL=+15551234567,+15551234568,+15551234569
SMS_LOCK_TIMEOUT_MINUTES=30  # Optional, default 30
```

**Twilio Webhook:** Configure phones to POST incoming SMS to `https://your-domain.com/webhooks/sms/incoming`

## Adding a New Tool

1. Create implementation in `packages/agent-framework/agent_framework/tools/your_tool.py`:
```python
async def your_tool(param: str) -> dict[str, Any]:
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
   - Tool automatically available to all agents
