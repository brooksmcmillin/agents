# Chatbot Agent

A general-purpose AI assistant powered by Claude Sonnet 4.5 with access to all 29 MCP tools. Unlike specialized agents, this chatbot can help with any task by leveraging the full suite of available tools including web analysis, memory, document search, email management, and communication.

## Features

### 🌐 Web Content Analysis
- Fetch and read web content as clean markdown
- Analyze websites for SEO, tone, and engagement metrics
- Extract structured data from web pages

### 🧠 Persistent Memory
- Save and retrieve information across conversations
- Search through saved memories by keyword
- Organize memories with categories, tags, and importance levels
- Configure backend storage (file or database)

### 📚 RAG Document Search
- Add and manage documents in a knowledge base
- Search through documents with semantic similarity
- Perfect for research and information retrieval

### 📧 Email Management (FastMail)
- List mailboxes and search emails
- Send, read, and manage email messages
- Move emails between folders
- Update email flags (read, flagged, etc.)

### 💬 Communication
- Send Slack messages for notifications and alerts

### 🎨 Content Tools
- Generate content topic suggestions
- Get social media statistics (Twitter, LinkedIn)

### 🔧 Full Tool Access
Unlike specialized agents that are limited to specific tools, the chatbot has unrestricted access to all 29 MCP tools, making it ideal for:
- Multi-domain tasks that span different capabilities
- Exploration and experimentation with tools
- General assistance without predefined workflows

## Quick Start

### Prerequisites

1. **Python 3.11 or higher**
2. **Anthropic API Key**: Set in `.env` file
   ```bash
   ANTHROPIC_API_KEY=your_key_here
   ```
3. **Optional Dependencies** (for specific tools):
   - PostgreSQL database for RAG and database memory backend
   - OpenAI API key for RAG embeddings
   - FastMail API token for email tools
   - Slack webhook URL for notifications

### Installation

```bash
# Install dependencies
uv sync

# Optional: Install voice interface
uv sync --group voice
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional - Memory Backend
MEMORY_BACKEND=file  # or "database"
MEMORY_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_memory  # if using database

# Optional - RAG Tools
RAG_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_rag
OPENAI_API_KEY=sk-...  # for embeddings

# Optional - FastMail Tools
FASTMAIL_API_TOKEN=your_token
FASTMAIL_ACCOUNT_ID=your_account_id

# Optional - Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Optional - Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Running

```bash
# Start the chatbot
uv run python -m agents.chatbot.main
```

## MCP Tools

The chatbot has access to **29 tools** across 8 categories:

### Web Analysis (2 tools)
- **fetch_web_content**: Fetch web content as clean markdown for reading and analysis
  - Parameters: `url` (string), `max_length` (optional, default 50000)
  - Returns: URL, title, content, word count, metadata

- **analyze_website**: Analyze website for SEO, tone, and engagement
  - Parameters: `url` (string), `analysis_type` (seo|tone|engagement|all)
  - Returns: Scores, recommendations, and detailed analysis

### Memory (6 tools)
- **save_memory**: Save information with key/value/category/tags
  - Parameters: `key`, `value`, `category` (optional), `tags` (optional), `importance` (1-10, optional)

- **get_memories**: Retrieve memories with filtering
  - Parameters: `category` (optional), `tags` (optional), `min_importance` (optional)

- **search_memories**: Search memories by keyword
  - Parameters: `query` (string)

- **delete_memory**: Delete a memory by key
  - Parameters: `key` (string)

- **get_memory_stats**: Get memory system statistics
  - Returns: Total memories, categories, average importance

- **configure_memory_store**: Configure memory backend
  - Parameters: `backend` (file|database), `database_url` (optional)

### RAG Document Search (6 tools)
*Requires PostgreSQL database and OpenAI API key*

- **add_document**: Add document to knowledge base
  - Parameters: `content`, `metadata` (optional), `document_id` (optional)

- **search_documents**: Search documents by query
  - Parameters: `query`, `limit` (optional, default 5), `min_similarity` (optional, default 0.7)

- **get_document**: Retrieve document by ID
  - Parameters: `document_id`

- **list_documents**: List all documents
  - Parameters: `limit` (optional), `offset` (optional)

- **delete_document**: Delete document by ID
  - Parameters: `document_id`

- **get_rag_stats**: Get RAG system statistics
  - Returns: Total documents, total chunks, database size

### Email Management - FastMail (8 tools)
*Requires FastMail API token and account ID*

- **list_mailboxes**: List all mailboxes

- **get_emails**: Get emails from a mailbox
  - Parameters: `mailbox_id`, `limit` (optional, default 50)

- **get_email**: Get single email by ID
  - Parameters: `email_id`

- **search_emails**: Search emails
  - Parameters: `query`, `mailbox_id` (optional), `limit` (optional)

- **send_email**: Send an email
  - Parameters: `to`, `subject`, `body`, `cc` (optional), `bcc` (optional)

- **move_email**: Move email to different mailbox
  - Parameters: `email_id`, `mailbox_id`

- **update_email_flags**: Update email flags
  - Parameters: `email_id`, `is_seen` (optional), `is_flagged` (optional)

- **delete_email**: Delete an email
  - Parameters: `email_id`

### Communication (1 tool)
- **send_slack_message**: Send a Slack message
  - Parameters: `channel`, `text`, `username` (optional), `icon_emoji` (optional)

### Social Media (1 tool)
- **get_social_media_stats**: Get social media statistics
  - Parameters: `platform` (twitter|linkedin), `username`
  - Returns: Followers, engagement metrics, recent posts

### Content Suggestions (1 tool)
- **suggest_content_topics**: Generate content topic ideas
  - Parameters: `context` (optional), `target_audience` (optional), `content_type` (optional)
  - Returns: List of topic suggestions with descriptions

## Usage Examples

### Example 1: Web Research with Memory

```
You: Can you read this article and save the key points? https://example.com/article

Chatbot: I'll fetch and read the article, then save the important information.
[Calls fetch_web_content]

The article discusses three main approaches to AI safety:
1. Constitutional AI
2. RLHF (Reinforcement Learning from Human Feedback)
3. Red teaming

Let me save these key points to memory.
[Calls save_memory with key="ai_safety_approaches", importance=8]

Saved! I've stored the three AI safety approaches in memory for future reference.
```

### Example 2: Email and Notification Workflow

```
You: Check my inbox for urgent emails and notify me on Slack if there are any

Chatbot: I'll check your FastMail inbox for urgent emails.
[Calls get_emails with mailbox_id="inbox"]
[Calls search_emails with query="urgent OR important"]

Found 2 urgent emails:
1. "Production issue - immediate attention needed" from team@company.com
2. "Client deadline moved up" from client@example.com

Sending Slack notification...
[Calls send_slack_message]

Done! I've sent a Slack notification with details about both urgent emails.
```

### Example 3: Document Search and Analysis

```
You: Search my knowledge base for information about OAuth security best practices

Chatbot: I'll search through your documents for OAuth security information.
[Calls search_documents with query="OAuth security best practices"]

Found 3 relevant documents:
1. "OAuth 2.0 Security Guidelines" (similarity: 0.89)
   - Use PKCE for public clients
   - Validate redirect URIs strictly
   - Implement state parameter for CSRF protection

2. "Common OAuth Vulnerabilities" (similarity: 0.85)
   - Authorization code interception
   - Token leakage through referrer headers
   ...

Would you like me to read the full content of any of these documents?
```

## Interactive Commands

Once running, you can use these commands:
- `exit`, `quit`, `q` - Exit the agent
- `stats` - Show token usage statistics
- `reload` - Reconnect to MCP server (refresh tools after editing)

## Configuration

### Environment Variables

```bash
# Core Configuration
ANTHROPIC_API_KEY=sk-ant-...          # Required: Anthropic API key
LOG_LEVEL=INFO                        # Optional: Logging level

# Memory Configuration
MEMORY_BACKEND=file                   # Optional: file (default) or database
MEMORY_DATABASE_URL=postgresql://...  # Required if using database backend

# RAG Configuration
RAG_DATABASE_URL=postgresql://...     # Required for RAG tools
OPENAI_API_KEY=sk-...                # Required for RAG embeddings

# Email Configuration (FastMail)
FASTMAIL_API_TOKEN=...               # Required for email tools
FASTMAIL_ACCOUNT_ID=...              # Required for email tools

# Communication
SLACK_WEBHOOK_URL=https://hooks...   # Required for Slack notifications
```

### Customization

Edit `agents/chatbot/prompts.py` to customize:
- **SYSTEM_PROMPT**: Agent behavior and instructions
- **USER_GREETING_PROMPT**: Initial greeting message

## Troubleshooting

### Tool Not Available

If the agent reports a tool is unavailable:

```bash
# Check which tools are loaded
# Start agent and type: reload

# Verify MCP server is running
uv run python -m config.mcp_server.server
```

### Memory Issues

```bash
# Check memory backend configuration
echo $MEMORY_BACKEND

# Test database connection (if using database backend)
psql $MEMORY_DATABASE_URL -c "SELECT 1"

# View memory stats in conversation
You: Can you show me memory statistics?
```

### RAG Not Working

RAG tools require both PostgreSQL and OpenAI API:

```bash
# Verify database connection
psql $RAG_DATABASE_URL -c "SELECT COUNT(*) FROM documents"

# Verify OpenAI API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Check agent logs
tail -f ~/.agents/logs/agent_$(date +%Y-%m-%d).log
```

### Email Tools Failing

```bash
# Verify FastMail credentials
echo $FASTMAIL_API_TOKEN
echo $FASTMAIL_ACCOUNT_ID

# Test API access
curl -X GET https://api.fastmail.com/jmap/session \
  -H "Authorization: Bearer $FASTMAIL_API_TOKEN"
```

### API Key Issues

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

# Check .env file exists and is loaded
cat .env | grep ANTHROPIC_API_KEY
```

## Architecture

The chatbot uses:
- **Claude Sonnet 4.5** for intelligent conversation and decision-making
- **Local MCP Client** connecting to MCP server via stdio
- **Anthropic SDK** for Claude API integration
- **Hot reload** - edit tools while agent is running, changes picked up automatically

The agent maintains conversation context across multiple turns and can execute multiple tool calls in sequence to accomplish complex goals.

## Development

### Hot Reload

You can edit MCP tools while the agent is running:

1. Edit tool code in `packages/agent-framework/agent_framework/tools/*.py`
2. Save the file
3. Next tool call automatically picks up changes
4. Or type `reload` to force reconnection

See [HOT_RELOAD.md](../../HOT_RELOAD.md) for details.

### Testing Tools

```bash
# Test specific tool
uv run python scripts/testing/test_memory.py

# Run demo script to test all tools
uv run python demo.py
```

### Adding New Capabilities

The chatbot automatically gets access to any new tools added to the MCP server:

1. Add tool to `packages/agent-framework/agent_framework/tools/`
2. Export from `tools/__init__.py`
3. Agent discovers it on next connection (or use `reload` command)

See [CLAUDE.md](../../CLAUDE.md) for full development guide.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Project overview and development guide
- [HOT_RELOAD.md](../../HOT_RELOAD.md) - Hot reload development workflow
- [GUIDES.md](../../GUIDES.md) - Memory, RAG, and deployment guides
- [agent-framework](../../packages/agent-framework/) - Shared agent library
- [Testing Guide](../../docs/TESTING.md) - Testing and debugging
