# MCP Tools Reference

The MCP server exposes **73 tools** across 16 categories (defined in `packages/agent-framework/agent_framework/tools/`).

## Web Analysis Tools (2 tools)
- `fetch_web_content` - Fetch web content as clean markdown for LLM reading and analysis
- `analyze_website` - Web content analysis (tone, SEO, engagement) - uses real web scraping

## Browser Testing Tools (6 tools)
*Requires Playwright browser automation library. Install with:*
```bash
uv sync --group browser
uv run playwright install chromium
```
- `browser_screenshot` - Take a screenshot of a webpage using headless Chromium, supporting full-page captures and custom viewports
- `browser_accessibility_audit` - Run an accessibility audit checking heading hierarchy, image alt text, form labels, ARIA landmarks, link text quality, language attribute, skip-navigation links, viewport configuration, and keyboard focus order
- `browser_performance_audit` - Collect performance metrics including DNS/TCP/TTFB/DOM load times, Core Web Vitals (LCP, CLS), total page weight, and resource breakdown by category
- `browser_console_errors` - Capture JavaScript console errors, warnings, and uncaught exceptions from a loaded webpage
- `browser_check_links` - Check for broken links on a webpage by extracting all links and verifying them with HEAD requests
- `browser_crawl_site` - Crawl a website starting from a URL to discover internal pages, following same-origin links up to a maximum page count

## Memory Tools (7 tools)
- `save_memory` - Save information with key/value/category/tags/importance (1-10 scale)
- `get_memories` - Retrieve memories with filtering by category/tags/importance
- `search_memories` - Search memories by keyword
- `recall_memories` - Retrieve memories by semantic similarity using embedding-based vector search or keyword fallback
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

## FastMail Calendar Tools (2 tools)
*Requires FastMail API token (same as email tools)*
- `list_calendars` - List all calendars (name, color, visibility)
- `get_calendar_events` - Query events by date range with optional calendar/title filters

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

## Network Admin Tools (11 tools)
*Requires `SYSADMIN_ALLOWED_SUBNETS` env var for network-based tools (fail-secure: denied when unset)*

**Network Discovery & Scanning:**
- `network_discover_hosts` - Discover live hosts on a local subnet using TCP probes on common ports (80, 443, 22, 445)
- `network_scan_ports` - Scan TCP ports on a target host with support for port ranges, common port lists, and optional service banner grabbing
- `network_grab_banners` - Connect to open ports and retrieve service banners to identify software versions and misconfigurations
- `network_check_tls` - Inspect TLS/SSL configuration including certificate validity, expiration, protocol version, cipher suites, and trust chain validation

**Network Configuration Audit:**
- `network_check_dns` - Perform DNS lookups and check for common misconfigurations (SPF, DMARC, reverse DNS)
- `network_check_default_credentials` - Check for default/common credentials on discovered services (SSH, HTTP, SNMP) for defensive auditing

**Local System Security Audit:**
- `system_get_info` - Collect local system information including OS version, hostname, network interfaces, listening ports, and uptime
- `system_check_ssh_config` - Audit SSH server configuration for security issues (root login, password auth, empty passwords, X11 forwarding)
- `system_check_file_permissions` - Check permissions on sensitive files and directories, identifying world-readable/writable files and overly permissive SSH keys
- `system_check_firewall` - Check firewall configuration and identify issues in ufw, iptables, or nftables rules

**Comprehensive Security Reporting:**
- `network_generate_report` - Run a comprehensive multi-stage security assessment orchestrating port scans, TLS checks, DNS analysis, SSH config audits, firewall review, and default credential tests with findings sorted by severity

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
# From address auto-derived from agent name (e.g., chatbot@yourdomain.com)
# To address auto-filled from ADMIN_EMAIL_ADDRESS env var
result = await send_agent_report(
    subject="Daily Task Summary",
    body="Completed tasks today: ...",
)
```

**Agent Email Configuration:**
```bash
ADMIN_EMAIL_ADDRESS=you@example.com
AGENT_EMAIL_DOMAIN=yourdomain.com  # optional, default
FASTMAIL_API_TOKEN=your_token_here
INTAKE_EMAIL_ADDRESS=tasks@yourdomain.com  # optional
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

TOOL_SCHEMAS = [
    {
        "name": "your_tool",
        "description": "Description of your tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "param": {"type": "string"}
            },
            "required": ["param"]
        },
        "handler": your_tool,
    }
]
```

2. Export from `packages/agent-framework/agent_framework/tools/__init__.py`:
```python
from .your_tool import TOOL_SCHEMAS as _your_tool_schemas
from .your_tool import your_tool

ALL_TOOL_SCHEMAS: list[dict] = [
    # ... existing schemas
    *_your_tool_schemas,  # ← Add your new tool
]

__all__ = [
    # ... existing exports
    "your_tool",  # ← Add your new tool
]
```

3. The tool is now auto-registered:
   - The MCP server's `create_mcp_server()` function automatically discovers and registers all tools from `ALL_TOOL_SCHEMAS`
   - No manual registration in `mcp_server/server.py` is needed
   - Tool is immediately available to all agents on next MCP connection
