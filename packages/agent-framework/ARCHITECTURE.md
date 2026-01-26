# Architecture

This document provides a detailed overview of the Agent Framework's architecture, design decisions, and extension patterns.

## Table of Contents

- [Overview](#overview)
- [Core Components](#core-components)
- [Design Decisions](#design-decisions)
- [Extension Patterns](#extension-patterns)
- [Advanced Topics](#advanced-topics)

## Overview

The Agent Framework is a production-ready system for building LLM agents using the Model Context Protocol (MCP). It provides:

- **Separation of concerns**: Agent logic, tools, and storage are independent
- **Type safety**: Full typing with Pydantic throughout
- **Extensibility**: Clean abstractions for building domain-specific agents
- **Reusability**: Generic components work across different agent implementations

### Philosophy

The framework is extracted from production agent implementations and follows these principles:

1. **Convention over configuration**: Sensible defaults with override options
2. **Explicit is better than implicit**: Clear interfaces and contracts
3. **Fail fast**: Validation errors at startup, not runtime
4. **Easy to debug**: Simple stdio transport, structured logging
5. **Progressive complexity**: Simple things are simple, complex things are possible

## Core Components

### 1. Agent System (`agent_framework/core/`)

#### `agent.py` - Base Agent Class

The `Agent` class implements the core agentic loop:

```python
class Agent(ABC):
    """Base class for all agents."""

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt defining agent behavior."""
        pass

    def get_agent_name(self) -> str:
        """Return the display name (defaults to class name)."""
        return self.__class__.__name__

    def get_greeting(self) -> str:
        """Return the greeting message (has default implementation)."""
        return f"Hello! I'm {self.get_agent_name()}. How can I help you today?"
```

**Key features:**
- Interactive CLI interface with colored output
- Conversation history management
- Token usage tracking and display
- Automatic tool execution via MCP client
- Automatic context management (trimming with memory injection)
- Support for both local and remote MCP servers
- Error handling and recovery

**Constructor parameters:**
```python
Agent(
    api_key: str | None = None,           # Anthropic API key
    model: str = "claude-sonnet-4-5-20250929",
    mcp_server_path: str = "config.mcp_server.server",
    mcp_urls: list[str] | None = None,    # Remote MCP server URLs
    enable_web_search: bool = True,
    web_search_config: dict | None = None,
    mcp_client_config: dict | None = None,  # OAuth/device flow config
    max_context_messages: int | None = 30,  # Auto-trim context
    inject_memories_on_trim: bool = True,   # Inject high-importance memories
)
```

**Extension points:**
- Override `get_system_prompt()` (required)
- Override `get_agent_name()` and `get_greeting()` to customize display
- Hook into conversation lifecycle
- Add custom initialization logic

#### `mcp_client.py` - MCP Client

Handles communication with MCP servers:

```python
class MCPClient:
    async def connect(self, server_path: str) -> None:
        """Connect to MCP server via stdio."""

    async def list_tools(self) -> list[dict]:
        """Discover available tools."""

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Execute a tool call."""
```

**Key features:**
- Stdio transport for simplicity and debuggability
- Dynamic tool discovery
- Hot reload support (reconnects for each tool call)
- Structured error handling
- Request/response logging

**Design choice:** Hot reload pattern
- Reconnects to server for each tool call
- Allows updating tools without restarting agent
- Maintains conversation context across reloads
- Small overhead, but huge development experience win

#### `remote_mcp_client.py` - Remote MCP Client

Connects to remote MCP servers over HTTPS with OAuth:

```python
class RemoteMCPClient:
    async def connect(self) -> None:
        """Connect with automatic OAuth."""

    async def list_tools(self) -> list[dict]:
        """List remote tools."""

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Execute remote tool."""
```

**Key features:**
- HTTPS transport for remote servers
- Automatic OAuth 2.0 authentication
- OAuth discovery via .well-known endpoints
- Device Authorization Grant (RFC 8628) for headless environments
- Token storage and auto-refresh
- Browser-based or device flow authorization
- Health checking
- Manual token support

**OAuth flow:**
1. Discover OAuth config from server
2. Load saved tokens if available
3. Check token expiration, refresh if needed
4. If no valid token, run authorization flow:
   - Register dynamic OAuth client
   - **Browser flow:** Open browser for user login
   - **Device flow:** Display code for user to enter at verification URL
   - Exchange code for access token
5. Use access token for MCP requests

**Usage patterns:**
```python
# Automatic OAuth (browser flow)
async with RemoteMCPClient("https://mcp.example.com/mcp/") as client:
    tools = await client.list_tools()
    result = await client.call_tool("tool_name", args)

# Device flow for headless environments (containers, SSH sessions)
client = RemoteMCPClient(
    "https://mcp.example.com/mcp/",
    prefer_device_flow=True,
    device_authorization_callback=my_callback,  # Optional: notify via Slack
)

# Manual token
client = RemoteMCPClient(
    "https://mcp.example.com/mcp/",
    auth_token="your-token"
)
```

#### `config.py` - Configuration Management

Pydantic-based settings with environment variable support:

```python
class Settings(BaseSettings):
    # LLM Configuration
    anthropic_api_key: str | None = None

    # MCP Server Configuration
    mcp_server_host: str = "localhost"
    mcp_server_port: int = 8000

    # Token Storage
    token_storage_path: Path = Path.home() / ".agents" / "tokens"
    token_encryption_key: str | None = None

    # Memory Storage
    memory_storage_path: Path = Path.home() / ".agents" / "memories"

    # RAG Storage
    rag_database_url: str | None = None  # PostgreSQL connection URL
    openai_api_key: str | None = None    # For embeddings
    rag_embedding_model: str = "text-embedding-3-small"
    rag_table_name: str = "rag_documents"

    # Slack Integration
    slack_webhook_url: str | None = None
    slack_bot_token: str | None = None   # Bot User OAuth Token (xoxb-...)
    slack_app_token: str | None = None   # App-Level Token (xapp-...)
    slack_signing_secret: str | None = None

    # Logging
    log_level: str = "INFO"
    log_dir: Path = Path.home() / ".agents" / "logs"
```

**Key features:**
- `.env` file support
- Type validation
- Auto-creation of storage directories
- Environment variable override
- Sensible defaults

#### Logging System

The framework uses a dual-handler logging system:

```python
# File handler - captures all logs for debugging
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)

# Console handler - only important messages
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
```

**Key features:**
- Automatic log directory creation at `~/.agents/logs/`
- Date-stamped log files: `{agent_name}_{date}.log`
- Clean console output (warnings/errors only)
- Full debug logs in file for troubleshooting
- Log file path displayed at agent startup
- Configurable via `log_dir` parameter or `LOG_DIR` env var

### 2. Storage Layer (`agent_framework/storage/`)

#### `memory_store.py` - Memory System

Persistent storage for agent memories:

```python
class MemoryStore:
    def save_memory(
        self,
        key: str,
        value: str,
        category: str | None = None,
        tags: list[str] | None = None,
        importance: int = 5
    ) -> None:
        """Save a memory with metadata."""

    def get_all_memories(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int | None = None
    ) -> list[Memory]:
        """Retrieve memories with filtering."""

    def search_memories(self, query: str) -> list[Memory]:
        """Search memories by keyword."""
```

**Storage format:**
```json
{
  "user_preference": {
    "key": "user_preference",
    "value": "Prefers Python",
    "category": "preferences",
    "tags": ["python", "languages"],
    "importance": 8,
    "created_at": "2024-01-15T10:30:00",
    "updated_at": "2024-01-15T10:30:00"
  }
}
```

**Design choice:** File-based storage
- Simple to start: no database setup required
- Easy to inspect: JSON files are human-readable
- Clear migration path: interface supports database backends
- Good enough: suitable for most agent use cases

#### `database_memory_store.py` - PostgreSQL Memory Storage

PostgreSQL-backed memory storage with local caching for cross-machine portability:

```python
class DatabaseMemoryStore:
    """PostgreSQL-backed memory storage with caching."""

    def __init__(
        self,
        database_url: str,
        cache_ttl: float = 300.0,  # 5 minutes
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        """Initialize with PostgreSQL connection."""

    async def save_memory(...) -> Memory:
        """Save or update a memory."""

    async def get_memory(key: str) -> Memory | None:
        """Retrieve a specific memory by key."""

    async def get_all_memories(...) -> list[Memory]:
        """Get all memories with optional filtering."""

    async def search_memories(query: str) -> list[Memory]:
        """Search memories by text in key or value."""

    async def delete_memory(key: str) -> bool:
        """Delete a memory."""
```

**Key features:**
- Same interface as file-based MemoryStore
- Connection pooling with asyncpg
- Local TTL-based caching for performance
- Automatic table and index creation
- SQL injection protection
- Cross-machine memory portability

**Usage:**
```python
from agent_framework.storage import DatabaseMemoryStore

store = DatabaseMemoryStore("postgresql://user:pass@localhost/dbname")
await store.initialize()
await store.save_memory("key", "value", category="test")
```

#### `rag_store.py` - RAG Document Storage

PostgreSQL + pgvector storage for semantic document search:

```python
class RAGStore:
    """PostgreSQL + pgvector storage for RAG documents."""

    def __init__(
        self,
        database_url: str,
        openai_api_key: str | None = None,
        embedding_model: str = "text-embedding-3-small",
        table_name: str = "rag_documents",
    ):
        """Initialize RAG store."""

    async def add_document(
        content: str,
        metadata: dict | None = None,
        document_id: str | None = None,
    ) -> Document:
        """Add a document with auto-generated embedding."""

    async def search(
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        metadata_filter: dict | None = None,
    ) -> list[SearchResult]:
        """Semantic search using vector similarity."""

    async def get_document(document_id: str) -> Document | None
    async def delete_document(document_id: str) -> bool
    async def list_documents(...) -> list[Document]
    async def get_stats() -> dict
```

**Key features:**
- Vector embeddings via OpenAI API
- HNSW index for fast similarity search
- Metadata filtering
- Content deduplication via hash
- Automatic table and index creation

**Requirements:**
- PostgreSQL with pgvector extension
- OpenAI API key for embeddings

#### `token_store.py` - OAuth Token Storage

Secure storage for OAuth tokens:

```python
class TokenStore:
    def save_token(
        self,
        service_name: str,
        token_data: TokenData
    ) -> None:
        """Save encrypted token."""

    def get_token(self, service_name: str) -> TokenData | None:
        """Retrieve and decrypt token."""
```

**Key features:**
- Fernet symmetric encryption
- Automatic expiration checking
- Refresh token support
- Proper file permissions (600)
- Per-service storage

**Security:**
- Tokens encrypted at rest
- Encryption key from environment
- File permissions prevent unauthorized access
- In-memory decryption only

### 3. OAuth Module (`agent_framework/oauth/`)

Complete OAuth 2.0 implementation for remote MCP server authentication.

#### `oauth_config.py` - OAuth Discovery

Discovers OAuth configuration from servers via RFC 8414 and RFC 9908:

```python
@dataclass
class OAuthConfig:
    """Discovered OAuth configuration."""
    resource_url: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    scopes_supported: list[str] | None
    code_challenge_methods_supported: list[str] | None

async def discover_oauth_config(base_url: str) -> OAuthConfig:
    """Discover OAuth config from .well-known endpoints."""
```

**Discovery process:**
1. Fetch `/.well-known/oauth-protected-resource` (RFC 9908)
   - Get resource URL and authorization server URL
2. Fetch `/.well-known/oauth-authorization-server` (RFC 8414)
   - Get authorization and token endpoints
   - Get supported features (PKCE, scopes, etc.)
3. Return complete OAuthConfig

**Supported standards:**
- RFC 8414: OAuth Authorization Server Metadata
- RFC 9908: OAuth Protected Resource Metadata
- Fallback to OpenID Connect discovery

#### `oauth_flow.py` - Authorization Flow

Implements OAuth 2.0 authorization code flow with PKCE:

```python
class OAuthFlowHandler:
    async def register_client(self) -> tuple[str, str | None]:
        """Dynamic client registration."""

    async def authorize(self) -> TokenSet:
        """Run authorization flow (opens browser)."""

    async def refresh_token(self, refresh_token: str) -> TokenSet:
        """Refresh access token."""
```

**Authorization flow:**
1. **Register client** (if dynamic registration supported)
   - POST to registration endpoint
   - Get client_id (and client_secret for confidential clients)
2. **Generate PKCE pair**
   - code_verifier: random 43-128 character string
   - code_challenge: SHA256(code_verifier)
3. **Open browser** to authorization endpoint
   - Include client_id, redirect_uri, scopes, code_challenge
4. **Run local callback server** on localhost:8889
   - Wait for OAuth callback with authorization code
   - Display success/error page
5. **Exchange code for token**
   - POST to token endpoint with code and code_verifier
   - Receive access_token and optional refresh_token

**PKCE support:**
- Uses S256 (SHA256) challenge method
- Protects against authorization code interception
- Required for public clients (no client secret)

**Token refresh:**
- Uses refresh_token grant type
- Automatically called when access token expires
- Returns new access token (may include new refresh token)

#### `device_flow.py` - Device Authorization Grant (RFC 8628)

OAuth 2.0 Device Authorization Grant for headless environments:

```python
@dataclass
class DeviceAuthorizationInfo:
    """Information about a pending device authorization."""
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    device_code: str

# Callback type for notifying users (e.g., via Slack)
DeviceAuthorizationCallback = Callable[[DeviceAuthorizationInfo], Awaitable[None] | None]

class DeviceFlowHandler(OAuthHandlerBase):
    async def authorize(self) -> TokenSet:
        """Run complete device authorization flow."""

    async def request_device_code(self) -> dict:
        """Request device code from authorization server."""

    async def poll_for_token(...) -> TokenSet:
        """Poll until user authorizes or code expires."""
```

**Device flow process:**
1. Request device code from authorization server
2. Display verification URL and user code to user
3. Optionally invoke callback (e.g., post to Slack)
4. Poll token endpoint until user completes authorization
5. Return access token

**Use cases:**
- Containers without browser access
- SSH sessions
- Headless servers
- Slack bots (post auth URL to channel)

**Example with Slack notification:**
```python
async def notify_slack(info: DeviceAuthorizationInfo):
    await slack_client.chat_postMessage(
        channel="#auth",
        text=f"Visit: {info.verification_uri_complete}\\n"
             f"Code: {info.user_code}"
    )

handler = DeviceFlowHandler(
    oauth_config,
    authorization_callback=notify_slack
)
```

#### `oauth_tokens.py` - Token Management

Token data structures and file-based storage:

```python
@dataclass
class TokenSet:
    """OAuth token with metadata."""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None
    refresh_token: str | None
    issued_at: float | None

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if token is expired."""

class TokenStorage:
    """File-based token storage."""
    def save_token(self, server_url: str, token_set: TokenSet) -> None
    def load_token(self, server_url: str) -> TokenSet | None
    def delete_token(self, server_url: str) -> None
```

**Storage details:**
- Tokens saved to `~/.agents/tokens/`
- One file per server (based on URL hash)
- JSON format with server URL and token data
- Expiration checking with 60-second buffer

**Security note:**
- These are OAuth access tokens (not encrypted in storage)
- Different from `TokenStore` which encrypts refresh tokens for external services
- OAuth tokens are short-lived and server can revoke them

### 4. Generic Tools (`agent_framework/tools/`)

#### `web_reader.py` - Web Content Fetcher

Fetches and converts web content to clean markdown:

```python
async def fetch_web_content(
    url: str,
    max_length: int = 10000
) -> dict:
    """Fetch web content and convert to markdown."""
```

**Features:**
- HTML to markdown conversion
- Removes navigation, ads, footers
- Extracts metadata (links, images, word count)
- Configurable length limits
- Error handling for network issues

**Implementation:**
- Uses `httpx` for async HTTP
- `BeautifulSoup4` for parsing
- `html2text` for markdown conversion
- Configurable selectors for cleanup

#### `slack.py` - Slack Integration

Send messages via Slack webhooks:

```python
async def send_slack_message(
    text: str,
    username: str | None = None,
    channel: str | None = None,
    icon_emoji: str | None = None
) -> dict:
    """Send message to Slack."""
```

**Features:**
- Incoming webhook support
- Custom username, emoji, channel
- Markdown formatting
- URL validation
- Error handling

#### `memory.py` - Memory Tool Implementations

Wrappers around `MemoryStore` for tool use:

```python
async def save_memory(
    key: str,
    value: str,
    category: str | None = None,
    tags: list[str] | None = None,
    importance: int = 5
) -> dict:
    """Tool wrapper for saving memories."""

async def get_memories(...) -> dict:
    """Tool wrapper for retrieving memories."""

async def search_memories(query: str) -> dict:
    """Tool wrapper for searching memories."""
```

**Design choice:** Tool wrappers
- Separate tool interface from storage implementation
- Return dicts (JSON-serializable for MCP)
- Add error handling for tool context
- Global store instance for convenience

#### `rag.py` - RAG Tool Implementations

Tools for semantic document search:

```python
async def add_document(
    content: str | None = None,
    metadata: dict | None = None,
    document_id: str | None = None,
    file_path: str | None = None,  # PDF support
) -> dict:
    """Add document to RAG knowledge base."""

async def search_documents(
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    metadata_filter: dict | None = None,
) -> dict:
    """Semantic search for relevant documents."""

async def get_document(document_id: str) -> dict
async def delete_document(document_id: str) -> dict
async def list_documents(...) -> dict
async def get_rag_stats() -> dict
```

**Features:**
- Add documents from text or PDF files
- Semantic search using vector similarity
- Metadata filtering and categorization
- PDF text extraction via pymupdf4llm

### 5. Adapters (`agent_framework/adapters/`)

#### `multi_agent_slack_adapter.py` - Multi-Agent Slack Integration

Route Slack messages to multiple specialized agents:

```python
class RoutingStrategy(Enum):
    KEYWORD = "keyword"    # Route based on message keywords
    EXPLICIT = "explicit"  # Route via @agent or "ask agent:"
    CHANNEL = "channel"    # Route based on Slack channel
    HYBRID = "hybrid"      # Try all strategies in order

class MultiAgentSlackAdapter:
    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
        routing_strategy: RoutingStrategy = RoutingStrategy.HYBRID,
        respond_to_mentions_only: bool = False,
        use_threads: bool = True,
        inactivity_timeout: int = 86400,  # 24 hours
    ):
        """Initialize multi-agent Slack adapter."""

    def register_agent(
        self,
        name: str,
        agent: Agent,
        keywords: list[str] | None = None,
        description: str = "",
        channels: list[str] | None = None,
    ) -> None:
        """Register an agent with routing configuration."""

    def set_default_agent(self, name: str) -> None
    def create_device_auth_callback(channel: str, ...) -> DeviceAuthorizationCallback
    def start(self) -> None:
        """Start the Slack bot (blocks)."""
```

**Key features:**
- Route to multiple agents based on keywords, explicit commands, or channels
- Per-agent conversation isolation (separate history per agent per thread)
- Automatic context reset after inactivity
- Device flow OAuth notifications via Slack
- Long message splitting
- Typing indicators

**Usage example:**
```python
from agent_framework import MultiAgentSlackAdapter, RoutingStrategy

adapter = MultiAgentSlackAdapter(routing_strategy=RoutingStrategy.HYBRID)

# Create device auth callback for OAuth notifications
auth_callback = adapter.create_device_auth_callback(channel="#bot-auth")

adapter.register_agent(
    name="tasks",
    agent=TaskAgent(
        mcp_urls=["https://mcp.example.com/"],
        mcp_client_config={"device_authorization_callback": auth_callback}
    ),
    keywords=["task", "todo", "schedule"],
    description="Task management",
)

adapter.register_agent(
    name="pr",
    agent=PRReviewAgent(),
    keywords=["pr", "pull request", "review"],
)

adapter.set_default_agent("tasks")
adapter.start()
```

**Environment variables:**
- `SLACK_BOT_TOKEN`: Bot User OAuth Token (xoxb-...)
- `SLACK_APP_TOKEN`: App-Level Token for Socket Mode (xapp-...)

### 7. MCP Server Infrastructure (`agent_framework/server/`)

#### `server.py` - MCP Server Base

Clean server setup with tool registration:

```python
def create_mcp_server(name: str) -> MCPServer:
    """Factory function for creating MCP servers."""

class MCPServer:
    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable
    ) -> None:
        """Register a tool with the server."""

    def setup_handlers(self) -> None:
        """Set up MCP protocol handlers."""

    async def run(self) -> None:
        """Start the server."""
```

**Key features:**
- Simple registration API
- Automatic error categorization
- JSON schema validation
- Stdio transport
- Request/response logging

**Error handling:**
```python
# Three error categories
ValidationError    # Invalid input schema
AuthenticationError  # Missing/invalid credentials
ToolExecutionError   # Runtime errors
```

Each category provides specific error messages for debugging.

### 8. Utilities (`agent_framework/utils/`)

#### `errors.py` - Error Types

Structured error hierarchy:

```python
class AgentError(Exception):
    """Base class for all agent errors."""

class ValidationError(AgentError):
    """Input validation failed."""

class AuthenticationError(AgentError):
    """Authentication failed."""

class ToolExecutionError(AgentError):
    """Tool execution failed."""
```

**Benefits:**
- Specific error handling
- Clear error messages
- Easy to log and monitor
- Type-safe exception handling

## Design Decisions

### 1. MCP Protocol

**Decision:** Use MCP for tool management

**Rationale:**
- Clean separation between agent and tools
- Language-agnostic tool implementations
- Hot reload without losing conversation
- Standard protocol for tool discovery

**Trade-offs:**
- Additional process overhead
- Stdio communication complexity
- But: huge win for modularity and debugging

### 2. Stdio Transport

**Decision:** Use stdio for MCP communication

**Rationale:**
- Simple to implement and debug
- No network configuration needed
- Process isolation
- Standard input/output

**Trade-offs:**
- Local only (no remote tools)
- Process management overhead
- But: perfect for development and single-machine deployment

### 3. Hot Reload Pattern

**Decision:** Reconnect to MCP server for each tool call

**Rationale:**
- Tools can be updated without restarting agent
- Conversation context preserved
- Development experience is dramatically better
- Small performance cost is worth it

**Implementation:**
```python
async def call_tool(self, name: str, arguments: dict) -> Any:
    await self.connect(self.server_path)  # Reconnect
    result = await self._execute_tool(name, arguments)
    await self.disconnect()
    return result
```

### 4. File-Based Storage

**Decision:** Use JSON files for memory and token storage

**Rationale:**
- No database setup required
- Human-readable for debugging
- Easy to version control
- Sufficient for most use cases
- Clear migration path to databases

**Migration path:**
```python
# Implement the same interface with different backend
class DatabaseMemoryStore(MemoryStore):
    def __init__(self, db_url: str):
        self.db = create_engine(db_url)
    # Implement save_memory, get_all_memories, etc.
```

### 5. Pydantic Everywhere

**Decision:** Use Pydantic for all data validation

**Rationale:**
- Type safety
- Automatic validation
- Clear error messages
- JSON schema generation
- Environment variable parsing

**Example:**
```python
class Settings(BaseSettings):
    anthropic_api_key: str  # Required
    model_name: str = "claude-sonnet-4-5-20250929"  # Default

    class Config:
        env_file = ".env"
```

### 6. Abstract Base Classes

**Decision:** Use ABCs for agent extension points

**Rationale:**
- Forces implementation of required methods
- Clear contract for subclasses
- Compile-time checks (with mypy)
- Self-documenting API

**Example:**
```python
class Agent(ABC):
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Subclasses MUST implement this."""
        pass
```

### 7. Remote MCP with OAuth

**Decision:** Support remote MCP servers with automatic OAuth authentication

**Rationale:**
- Enables distributed agent architectures
- MCP servers can run on different machines/clouds
- OAuth provides secure, standardized authentication
- Browser-based flow is familiar to users
- Token refresh prevents re-authentication

**Trade-offs:**
- More complex than local stdio
- Requires OAuth server setup
- But: enables powerful distributed patterns

**Implementation:**
- Separate `RemoteMCPClient` class (vs modifying `MCPClient`)
- HTTPS transport via MCP's `streamablehttp_client`
- OAuth discovery follows RFC 8414 and RFC 9908
- PKCE required for security (no client secrets in CLI tools)
- Token storage in `~/.agents/tokens/`

**Standards compliance:**
- RFC 6749: OAuth 2.0 Authorization Framework
- RFC 7636: PKCE for OAuth Public Clients
- RFC 8414: OAuth Authorization Server Metadata
- RFC 9908: OAuth Protected Resource Metadata
- MCP Streamable HTTP transport specification

## Extension Patterns

### Building Domain-Specific Agents

Create a separate package that extends the framework:

```
my-agent/
├── my_agent/
│   ├── __init__.py
│   ├── agent.py          # Extends Agent
│   ├── server.py         # MCP server setup
│   ├── prompts.py        # Domain-specific prompts
│   └── tools/
│       ├── tool1.py      # Custom tools
│       ├── tool2.py
│       └── tool3.py
├── pyproject.toml        # Depends on agent-framework
└── README.md
```

**Example implementation:**

```python
# my_agent/agent.py
from agent_framework import Agent
from .prompts import SYSTEM_PROMPT

class MyAgent(Agent):
    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_agent_name(self) -> str:
        return "My Custom Agent"

    def get_greeting(self) -> str:
        return "Hello! I'm your custom agent."
```

```python
# my_agent/server.py
from agent_framework.server import create_mcp_server
from agent_framework.tools import fetch_web_content, save_memory
from .tools import custom_tool1, custom_tool2

async def main():
    server = create_mcp_server("my-agent")

    # Register framework tools
    server.register_tool(
        name="fetch_web_content",
        description="Fetch web content",
        input_schema={...},
        handler=fetch_web_content,
    )

    # Register custom tools
    server.register_tool(
        name="custom_tool1",
        description="Domain-specific functionality",
        input_schema={...},
        handler=custom_tool1,
    )

    server.setup_handlers()
    await server.run()
```

```toml
# pyproject.toml
[project]
name = "my-agent"
dependencies = [
    "agent-framework @ file:///path/to/agent-framework",
    "domain-specific-library",
]
```

### Custom Storage Backends

Implement the storage interface with your backend:

```python
from agent_framework.storage import MemoryStore, Memory

class PostgresMemoryStore(MemoryStore):
    """PostgreSQL-backed memory storage."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)

    def save_memory(
        self,
        key: str,
        value: str,
        category: str | None = None,
        tags: list[str] | None = None,
        importance: int = 5
    ) -> None:
        with Session(self.engine) as session:
            memory = MemoryModel(
                key=key,
                value=value,
                category=category,
                tags=tags,
                importance=importance
            )
            session.merge(memory)
            session.commit()

    def get_all_memories(self, **filters) -> list[Memory]:
        with Session(self.engine) as session:
            query = session.query(MemoryModel)
            # Apply filters...
            return [self._to_memory(m) for m in query.all()]
```

Use in your agent:

```python
from my_agent.storage import PostgresMemoryStore

# In your server setup
memory_store = PostgresMemoryStore("postgresql://...")

async def save_memory_handler(arguments: dict) -> dict:
    memory_store.save_memory(**arguments)
    return {"status": "success"}
```

### Adding Tool Categories

Group related tools into modules:

```python
# my_agent/tools/calendar.py
async def create_event(title: str, start: str, end: str) -> dict:
    """Create a calendar event."""
    # Implementation...

async def list_events(start_date: str, end_date: str) -> dict:
    """List calendar events."""
    # Implementation...

# Register in server
from .tools import calendar

server.register_tool("create_event", ..., calendar.create_event)
server.register_tool("list_events", ..., calendar.list_events)
```

### Multi-Agent Systems

Create specialized agents for different tasks:

```python
# research_agent.py
class ResearchAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You are a research assistant that reads and summarizes web content."

# writing_agent.py
class WritingAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You are a writing assistant that helps draft and edit content."

# orchestrator.py
class OrchestratorAgent(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.research_agent = ResearchAgent(...)
        self.writing_agent = WritingAgent(...)

    async def delegate_task(self, task_type: str, task: str) -> str:
        if task_type == "research":
            return await self.research_agent.process(task)
        elif task_type == "writing":
            return await self.writing_agent.process(task)
```

## Advanced Topics

### Remote MCP Servers

Deploy MCP servers remotely and connect via HTTPS:

**Server setup:**
```python
# Deploy MCP server with OAuth
from agent_framework.server import create_mcp_server
from your_oauth_provider import setup_oauth

server = create_mcp_server("remote-tools")
# Register your tools...

# Deploy with OAuth-enabled web server
# (implementation depends on your OAuth provider)
```

**Client usage:**
```python
from agent_framework.core.remote_mcp_client import RemoteMCPClient

# Automatic OAuth
async with RemoteMCPClient("https://tools.example.com/mcp/") as client:
    tools = await client.list_tools()
    result = await client.call_tool("remote_tool", {"arg": "value"})
```

**Use cases:**
- **Shared tools**: Multiple agents access same tool server
- **Centralized resources**: Database, API keys in one secure location
- **Scalability**: Distribute tool execution across servers
- **Security**: Tools run in isolated environment

**Architecture patterns:**

1. **Hub and spoke**: Central tool server, multiple agents
```
Agent 1 ─┐
Agent 2 ─┼──> Remote MCP Server (OAuth) ──> External APIs
Agent 3 ─┘                                   Databases
```

2. **Specialized servers**: Different servers for different tool categories
```
Agent ──┬──> Auth Server (OAuth) ──> User management tools
        ├──> Data Server (OAuth) ──> Database tools
        └──> API Server (OAuth) ──> External API tools
```

3. **Hybrid**: Local tools for speed, remote for security/sharing
```
Agent ──┬──> Local MCP Server (stdio) ──> File tools, CLI tools
        └──> Remote MCP Server (OAuth) ──> API keys, secrets
```

### Token Management

Monitor and limit token usage:

```python
class Agent:
    def __init__(self, *args, max_conversation_tokens: int = 50000, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_conversation_tokens = max_conversation_tokens

    async def _check_token_limit(self) -> None:
        if self.total_tokens > self.max_conversation_tokens:
            # Summarize or truncate conversation
            await self._summarize_conversation()
```

### Streaming Responses

Add streaming support:

```python
async def stream_response(self, message: str):
    """Stream response tokens as they arrive."""
    async with self.client.messages.stream(
        model=self.settings.model_name,
        messages=self.messages,
        max_tokens=self.settings.max_tokens,
    ) as stream:
        async for text in stream.text_stream:
            print(text, end="", flush=True)
        print()  # Newline at end
```

### Error Recovery

Implement retry logic:

```python
async def call_tool_with_retry(
    self,
    name: str,
    arguments: dict,
    max_retries: int = 3
) -> Any:
    for attempt in range(max_retries):
        try:
            return await self.mcp_client.call_tool(name, arguments)
        except ToolExecutionError as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

### Testing

Framework components are designed for testability:

```python
import pytest
from agent_framework.storage import MemoryStore

@pytest.fixture
def memory_store(tmp_path):
    return MemoryStore(storage_path=tmp_path / "memories.json")

def test_save_and_retrieve(memory_store):
    memory_store.save_memory("test", "value")
    memories = memory_store.get_all_memories()
    assert len(memories) == 1
    assert memories[0].key == "test"
```

### Deployment

**As a CLI tool:**
```python
# setup.py or pyproject.toml
[project.scripts]
my-agent = "my_agent.cli:main"
```

**As a service:**
```python
# service.py
from fastapi import FastAPI
from my_agent import MyAgent

app = FastAPI()
agent = MyAgent(...)

@app.post("/chat")
async def chat(message: str):
    response = await agent.process_message(message)
    return {"response": response}
```

**As a Docker container:**
```dockerfile
FROM python:3.11
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["python", "-m", "my_agent"]
```

## Future Enhancements

Potential areas for framework expansion:

1. ~~**Database backends**~~: ✅ Added PostgreSQL memory storage (DatabaseMemoryStore)
2. **More tools**: Email, calendar, file operations, code execution
3. ~~**Testing utilities**~~: ✅ Added comprehensive test suite
4. **Monitoring**: Metrics, logging, tracing integration
5. **Streaming**: Support for streaming responses
6. **Multi-modal**: Image, audio, video processing tools
7. ~~**Remote MCP**~~: ✅ Added HTTPS remote MCP with OAuth 2.0 and Device Flow
8. ~~**Agent collaboration**~~: ✅ Added Multi-Agent Slack Adapter for routing to multiple agents
9. **OAuth server**: Reference OAuth server implementation for MCP
10. ~~**CI/CD**~~: ✅ Added GitHub Actions for tests and security scanning
11. ~~**RAG**~~: ✅ Added RAG storage and tools with pgvector + OpenAI embeddings

## Summary

The Agent Framework provides a solid foundation for building production LLM agents:

- **Modular**: Clear separation of concerns
- **Extensible**: Clean extension points
- **Type-safe**: Full typing throughout
- **Battle-tested**: Patterns from production systems
- **Well-documented**: Code and architecture docs

Start with the framework's generic components, then extend with domain-specific tools and prompts for your use case.

For hands-on tutorial, see [GETTING_STARTED.md](GETTING_STARTED.md).
