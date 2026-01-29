# Feature Guides

Comprehensive guides for key features in the agent framework.

## Table of Contents

1. [Memory System Guide](#memory-system-guide)
2. [OAuth Integration Guide](#oauth-integration-guide)
3. [Deployment Guide](#deployment-guide)
4. [Voice Interface Guide](#voice-interface-guide)

---

## Memory System Guide

The memory system allows agents to persist information across conversations, enabling continuity and personalization.

### Architecture

Two backend options:
- **File-based** (default): JSON file at `memories/memories.json`
- **Database-based**: PostgreSQL with full SQL capabilities

### Configuration

```bash
# File-based (default)
MEMORY_BACKEND=file

# Database-based
MEMORY_BACKEND=database
MEMORY_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_memory
```

### Memory Structure

```python
{
    "key": {
        "value": "the stored information",
        "category": "user_preference",  # or "fact", "goal", "insight"
        "tags": ["seo", "twitter"],
        "importance": 8,  # 1-10 scale
        "created_at": "2024-01-15T10:30:00Z",
        "updated_at": "2024-01-20T15:45:00Z"
    }
}
```

### Best Practices

#### 1. Key Naming

**Use descriptive, namespaced keys**:
```python
# Good
await save_memory(
    key="user_blog_url",
    value="https://myblog.com"
)

await save_memory(
    key="client_acme_project_deadline",
    value="2024-06-01"
)

# Bad
await save_memory(
    key="url",  # Too generic
    value="https://myblog.com"
)
```

#### 2. Importance Levels

| Level | Use For | Example |
|-------|---------|---------|
| 9-10 | Critical user information | API keys, primary goals, core preferences |
| 7-8 | Important context | Project details, client info, key decisions |
| 5-6 | Useful details | Secondary preferences, nice-to-know facts |
| 3-4 | Minor details | Temporary notes, low-priority info |
| 1-2 | Rarely used | Test data, experimental info |

**Example**:
```python
# Critical
await save_memory(
    key="user_primary_goal",
    value="Launch SaaS product by Q2 2024",
    importance=10
)

# Important
await save_memory(
    key="user_tech_stack",
    value="Python, FastAPI, PostgreSQL, React",
    importance=7
)

# Useful
await save_memory(
    key="user_favorite_blog_topics",
    value="AI security, LLM vulnerabilities",
    importance=5
)
```

#### 3. Categories

Standard categories for organization:
- **user_preference**: User settings, preferences, style
- **fact**: Objective information, verified facts
- **goal**: User goals, objectives, targets
- **insight**: Learned insights, observations, patterns
- **project**: Project-specific details
- **client**: Client information (for business agents)

**Example**:
```python
await save_memory(
    key="user_writing_style",
    value="Technical, concise, prefers bullet points",
    category="user_preference"
)

await save_memory(
    key="rag_attack_vectors",
    value="Prompt injection, data poisoning, info leakage",
    category="fact"
)
```

#### 4. Tags

Use tags for cross-cutting concerns:
```python
await save_memory(
    key="twitter_engagement_strategy",
    value="Post technical threads on Tuesdays, engage with researchers",
    category="user_preference",
    tags=["twitter", "social_media", "marketing"]
)

# Later: Retrieve all social media related memories
memories = await get_memories(tags=["social_media"])
```

### Agent Workflow Integration

Agents should check memories at conversation start:

```python
# In agent system prompt
"""
## Memory Workflow

At the start of each conversation:
1. Check for saved memories about the user
2. Reference relevant context from previous conversations
3. Provide continuity based on past discussions
4. Save important new information during the conversation
"""
```

**Example in conversation**:
```
[Agent starts]
[Calls get_memories() to check for user context]

Agent: Welcome back! I see you're working on launching a SaaS product for
       developer tools. Last time we discussed your pricing strategy.
       How's that progressing?
```

### Memory Tools Reference

#### save_memory
```python
await save_memory(
    key="unique_key",
    value="information to save",
    category="user_preference",  # optional
    tags=["tag1", "tag2"],       # optional
    importance=7                  # optional, 1-10
)
```

#### get_memories
```python
# Get all memories
memories = await get_memories()

# Filter by category
memories = await get_memories(category="user_preference")

# Filter by tags
memories = await get_memories(tags=["twitter", "marketing"])

# Filter by importance
memories = await get_memories(min_importance=7)

# Combine filters
memories = await get_memories(
    category="goal",
    tags=["business"],
    min_importance=8
)
```

#### search_memories
```python
# Keyword search across all memories
results = await search_memories("blog post")
```

#### delete_memory
```python
await delete_memory("key_to_delete")
```

#### get_memory_stats
```python
stats = await get_memory_stats()
# Returns: {
#   "total": 42,
#   "by_category": {"user_preference": 15, "fact": 20, ...},
#   "average_importance": 6.5
# }
```

#### configure_memory_store
```python
# Switch backends at runtime
await configure_memory_store(
    backend="database",
    database_url="postgresql://..."
)
```

### Migration: File to Database

**Step 1**: Set up PostgreSQL database
```bash
createdb agent_memory
psql agent_memory < packages/agent-framework/schema/memory.sql
```

**Step 2**: Export file-based memories
```bash
cp memories/memories.json memories/memories.backup.json
```

**Step 3**: Configure database backend
```bash
# .env
MEMORY_BACKEND=database
MEMORY_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_memory
```

**Step 4**: Import memories (if migration script exists)
```bash
uv run python scripts/migrate_memory.py \
  --from-file memories/memories.json \
  --to-db $MEMORY_DATABASE_URL
```

**Step 5**: Test
```bash
# Start agent and verify memories are accessible
uv run python -m agents.chatbot.main

# In conversation
You: What do you remember about me?

# Agent should retrieve memories from database
```

### Testing Memory System

```bash
# Test memory operations
uv run python scripts/testing/test_memory.py stats

# Commands:
# - stats: Show memory statistics
# - save: Test saving memories
# - get: Test retrieving memories
# - search: Test search functionality
# - delete: Test deletion
```

---

## OAuth Integration Guide

The project includes complete OAuth 2.0 infrastructure ready for production use.

### Current State

- **Authorization Code Flow**: Full implementation with PKCE
- **Device Flow**: User-friendly authorization for CLI tools
- **Token Storage**: Encrypted token storage with automatic refresh
- **Mock Data**: Social media tools currently use mock data (ready for real APIs)

### Components

```
config/mcp_server/auth/
├── oauth_handler.py      # OAuth flows (authorization code, device, client credentials)
├── token_store.py        # Encrypted token storage using Fernet
└── oauth_providers.py    # Provider configurations (Twitter, LinkedIn, etc.)
```

### Enabling Real APIs

#### Step 1: Register OAuth Apps

**Twitter/X**:
1. Go to https://developer.twitter.com/
2. Create new app
3. Note Client ID and Client Secret
4. Set callback URL: `http://localhost:8000/callback`

**LinkedIn**:
1. Go to https://www.linkedin.com/developers/
2. Create new app
3. Note Client ID and Client Secret
4. Set callback URL: `http://localhost:8000/callback`

#### Step 2: Add Credentials to .env

```bash
# .env
TWITTER_CLIENT_ID=your_client_id
TWITTER_CLIENT_SECRET=your_client_secret
TWITTER_REDIRECT_URI=http://localhost:8000/callback

LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_REDIRECT_URI=http://localhost:8000/callback
```

#### Step 3: Enable OAuth Check in MCP Server

```python
# config/mcp_server/server.py

async def call_tool(name: str, arguments: dict) -> Any:
    # Uncomment for production
    if name in ["get_social_media_stats", "post_to_social_media"]:
        platform = arguments.get("platform", "twitter")
        token = await oauth_handler.get_valid_token(platform)
        if not token:
            raise PermissionError(
                f"Authentication required for {platform}. "
                "Run: uv run python scripts/oauth_login.py"
            )
        # Use token.access_token in API calls
```

#### Step 4: Implement Authorization Flow UI

Create web UI for OAuth callback:

```python
# config/mcp_server/auth_server.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/callback")
async def oauth_callback(request: Request):
    code = request.query_params.get("code")
    # Exchange code for token
    token = await oauth_handler.exchange_code_for_token(code)
    # Save token
    await token_store.save_token("twitter", token)
    return HTMLResponse("<h1>Authorization successful! You can close this window.</h1>")
```

#### Step 5: Replace Mock Data with Real API Calls

```python
# packages/agent-framework/agent_framework/tools/social_media.py

async def get_social_media_stats(platform: str, username: str) -> dict[str, Any]:
    # Get token
    token = await oauth_handler.get_valid_token(platform)

    if platform == "twitter":
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.twitter.com/2/users/by/username/{username}",
                headers={"Authorization": f"Bearer {token.access_token}"}
            )
            data = response.json()
            return {
                "platform": "twitter",
                "username": username,
                "followers": data["public_metrics"]["followers_count"],
                "following": data["public_metrics"]["following_count"],
                # ... map real API response
            }
```

### Token Storage Migration

Current file-based token storage can migrate to database:

```sql
-- schema/tokens.sql
CREATE TABLE oauth_tokens (
    platform VARCHAR(50) PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    token_type VARCHAR(50),
    scope TEXT
);
```

```python
# Implement database token store
class DatabaseTokenStore:
    async def save_token(self, platform: str, token: TokenSet):
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO oauth_tokens (...) VALUES (...) "
                "ON CONFLICT (platform) DO UPDATE SET ..."
            )

    async def get_token(self, platform: str) -> TokenSet | None:
        # Fetch from database
```

### Adding New OAuth Providers

```python
# config/mcp_server/auth/oauth_providers.py

PROVIDERS = {
    "twitter": {
        "authorization_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "scope": "tweet.read users.read",
    },
    "github": {  # Add new provider
        "authorization_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "repo read:user",
    },
}
```

---

## Deployment Guide

### Running Agents in Production

#### Option 1: Systemd Service (Linux)

Create systemd service file:

```ini
# /etc/systemd/system/agent-notifier.service
[Unit]
Description=Task Notifier Agent
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/agents
Environment="PATH=/path/to/.local/bin:/usr/bin"
ExecStart=/path/to/uv run python -m agents.notifier.main
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable agent-notifier
sudo systemctl start agent-notifier
sudo systemctl status agent-notifier
```

#### Option 2: Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install uv
RUN uv sync

CMD ["uv", "run", "python", "-m", "agents.chatbot.main"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  chatbot:
    build: .
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - MEMORY_BACKEND=database
      - MEMORY_DATABASE_URL=postgresql://postgres:password@db:5432/agent_memory
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=agent_memory
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Build and run:
```bash
docker-compose up -d
```

#### Option 3: Cron Job (Scheduled Tasks)

For notifier agent:

```bash
# crontab -e
# Run every hour
0 * * * * cd /path/to/agents && /path/to/uv run python -m agents.notifier.main >> /var/log/agent-notifier.log 2>&1
```

### Remote MCP Deployment

Deploy MCP server separately from agents:

```bash
# Server machine
cd config/mcp_server/
uvicorn server_http:app --host 0.0.0.0 --port 8080 --workers 4

# Or with gunicorn
gunicorn config.mcp_server.server_http:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8080
```

Configure agents:
```bash
# Agent machines (can be different servers)
MCP_SERVER_URL=https://mcp.company.com/mcp
MCP_AUTH_TOKEN=secure_token
uv run python -m agents.task_manager.main
```

### Monitoring and Logging

#### Centralized Logging

```python
# shared/logging_config.py
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(name: str):
    logger = logging.getLogger(name)
    handler = RotatingFileHandler(
        f"/var/log/agents/{name}.log",
        maxBytes=10_000_000,  # 10MB
        backupCount=5
    )
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
```

#### Health Checks

```python
# Add health check endpoint to API server
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agents": len(agent_registry),
        "timestamp": datetime.now().isoformat()
    }
```

Monitor:
```bash
# Simple monitoring script
while true; do
  curl -f http://localhost:8000/health || echo "API down!"
  sleep 60
done
```

#### Metrics (Optional)

```python
# Add Prometheus metrics
from prometheus_client import Counter, Histogram

request_count = Counter('agent_requests_total', 'Total requests')
request_duration = Histogram('agent_request_duration_seconds', 'Request duration')

@request_duration.time()
async def process_message(message: str):
    request_count.inc()
    # ... process message
```

### Environment Configuration

Production `.env`:

```bash
# Core
ANTHROPIC_API_KEY=sk-ant-production-key
LOG_LEVEL=INFO

# Database backends
MEMORY_BACKEND=database
MEMORY_DATABASE_URL=postgresql://user:pass@db.company.com:5432/agent_memory

RAG_DATABASE_URL=postgresql://user:pass@db.company.com:5432/agent_rag
OPENAI_API_KEY=sk-production-key

# Remote MCP
MCP_SERVER_URL=https://mcp.company.com/mcp
MCP_AUTH_TOKEN=production_token

# Communication
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/production/webhook

# FastMail
FASTMAIL_API_TOKEN=production_token
FASTMAIL_ACCOUNT_ID=production_account

# OAuth
TWITTER_CLIENT_ID=production_client_id
TWITTER_CLIENT_SECRET=production_secret
LINKEDIN_CLIENT_ID=production_client_id
LINKEDIN_CLIENT_SECRET=production_secret
```

### Security Checklist

- [ ] Use HTTPS for all remote MCP connections
- [ ] Rotate API keys and tokens regularly
- [ ] Enable authentication for MCP servers
- [ ] Use environment variables, never hardcode secrets
- [ ] Set up firewall rules to restrict access
- [ ] Enable audit logging for all tool calls
- [ ] Use database encryption for sensitive data
- [ ] Implement rate limiting on API endpoints
- [ ] Monitor for unusual activity
- [ ] Keep dependencies updated (`uv sync --upgrade`)

---

## Voice Interface Guide

The optional voice interface (`chasm` package) enables voice conversations with agents using Deepgram (STT) and Cartesia (TTS).

### Prerequisites

1. **System dependency**: PortAudio
   ```bash
   # macOS
   brew install portaudio

   # Ubuntu/Debian
   sudo apt-get install portaudio19-dev

   # Fedora
   sudo dnf install portaudio-devel
   ```

2. **API Keys**:
   - Deepgram API key (speech-to-text)
   - Cartesia API key (text-to-speech)

### Installation

```bash
# Install voice dependencies
uv sync --group voice
```

### Configuration

```bash
# .env
DEEPGRAM_API_KEY=your_deepgram_key
CARTESIA_API_KEY=your_cartesia_key

# Optional: Voice settings
CARTESIA_VOICE_ID=default  # Voice ID from Cartesia
DEEPGRAM_MODEL=nova-2      # STT model
```

### Running Voice-Enabled Agents

```python
# agents/chatbot/main_voice.py
import asyncio
from chasm import VoiceInterface
from agents.chatbot.main import ChatbotAgent

async def main():
    agent = ChatbotAgent()
    voice = VoiceInterface(agent)
    await voice.start()

if __name__ == "__main__":
    asyncio.run(main())
```

```bash
# Start voice interface
uv run python -m agents.chatbot.main_voice
```

### User Experience

```
$ uv run python -m agents.chatbot.main_voice

🎤 Voice interface started
Listening... (Press Ctrl+C to exit)

[User speaks: "What is prompt injection?"]
🔊 Transcribed: "What is prompt injection?"
🤖 Agent: "Prompt injection is a security vulnerability..."
🔉 [Text-to-speech plays response]

Listening...
```

### Troubleshooting

#### PortAudio Not Found

```bash
# Install PortAudio system library
# See Prerequisites section above

# Verify installation
python -c "import pyaudio; print('PortAudio OK')"
```

#### Deepgram API Errors

```bash
# Verify API key
curl -X POST "https://api.deepgram.com/v1/listen" \
  -H "Authorization: Token $DEEPGRAM_API_KEY" \
  -H "Content-Type: audio/wav" \
  --data-binary @test.wav

# Check quota/billing
# Visit https://console.deepgram.com/
```

#### Cartesia API Errors

```bash
# Verify API key
curl "https://api.cartesia.ai/voices" \
  -H "X-API-Key: $CARTESIA_API_KEY"

# Check quota/billing
# Visit Cartesia dashboard
```

#### Audio Device Issues

```python
# List available audio devices
import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    print(p.get_device_info_by_index(i))
```

Configure specific device:
```bash
# .env
AUDIO_INPUT_DEVICE_INDEX=0   # Your microphone
AUDIO_OUTPUT_DEVICE_INDEX=1  # Your speakers
```

### Voice Settings

```python
# Customize voice interface
voice = VoiceInterface(
    agent=agent,
    voice_id="cartesia_voice_id",  # Specific voice
    model="deepgram-nova-2",        # STT model
    language="en-US",               # Language
    enable_vad=True,                # Voice activity detection
    silence_threshold=1.5,          # Seconds of silence to end utterance
)
```

---

## Additional Resources

- [Testing Guide](docs/TESTING.md) - Comprehensive testing strategies
- [REMOTE_MCP.md](REMOTE_MCP.md) - Remote MCP server setup
- [HOT_RELOAD.md](HOT_RELOAD.md) - Development workflow
- [CLAUDE.md](CLAUDE.md) - Project overview
- [agent-framework](packages/agent-framework/) - Framework documentation
