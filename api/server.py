"""FastAPI REST server exposing agents as HTTP endpoints.

Provides three usage patterns:

1. **Stateless** - Fire a single prompt at an agent and get a response:
       POST /agents/{name}/message  {"message": "..."}

2. **Stateful sessions** - Multi-turn conversations with preserved history (in-memory):
       POST   /sessions              {"agent": "pr"}
       POST   /sessions/{id}/message {"message": "..."}
       GET    /sessions/{id}
       DELETE /sessions/{id}

3. **Persistent conversations** - Database-backed conversations that survive restarts:
       GET    /conversations              List all conversations
       POST   /conversations              Create new conversation
       GET    /conversations/{id}         Get conversation with messages
       POST   /conversations/{id}/message Send message
       PATCH  /conversations/{id}         Update title/metadata
       DELETE /conversations/{id}         Delete conversation
       POST   /conversations/{id}/clear   Clear messages (keep conversation)
       GET    /conversations/{id}/export  Export as JSON

Run with:
    uv run python -m api
"""

import asyncio
import logging
import os
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from agent_framework.storage import SMSPhonePoolManager

import anthropic
from agent_framework import Agent
from agent_framework.logging import correlation_id_var
from agent_framework.storage import DatabaseConversationStore
from anthropic.types import TextBlock
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Security,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .claude_code_sessions import ClaudeCodeSession, ClaudeCodeSessionManager
from .models import (
    AgentInfo,
    AgentListResponse,
    ClaudeCodeCreateWorkspaceRequest,
    ClaudeCodeInputRequest,
    ClaudeCodePermissionResponse,
    ClaudeCodeResizeRequest,
    ClaudeCodeSessionCreateRequest,
    ClaudeCodeSessionInfo,
    ClaudeCodeWorkspaceInfo,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationExport,
    ConversationInfo,
    ConversationListResponse,
    ConversationMessage,
    ConversationStatsResponse,
    ConversationUpdateRequest,
    HealthResponse,
    MessageRequest,
    MessageResponse,
    SessionCreateRequest,
    SessionInfo,
    TokenUsage,
)
from .sessions import SessionManager

logger = logging.getLogger(__name__)


def _sanitize_log_input(value: str) -> str:
    """Sanitize user input for safe logging.

    Prevents log injection attacks by removing newlines and control characters
    that could be used to forge log entries or corrupt log analysis.
    """
    # Replace newlines and carriage returns, then remove other control chars
    sanitized = value.replace("\n", "\\n").replace("\r", "\\r")
    # Remove other ASCII control characters (0x00-0x1F except tab)
    return "".join(c if c == "\t" or (ord(c) >= 0x20) else f"\\x{ord(c):02x}" for c in sanitized)


# ---------------------------------------------------------------------------
# Agent registry
#
# Uses the shared registry (shared/registry.py) as single source of truth.
# Populated lazily on first access so that imports only happen when the
# server actually starts.
# ---------------------------------------------------------------------------

_registry: dict[str, tuple[type[Agent], dict[str, Any] | None, str]] | None = None


def _get_registry() -> dict[str, tuple[type[Agent], dict[str, Any] | None, str]]:
    global _registry
    if _registry is None:
        from shared.registry import build_agent_registry  # noqa: PLC0415

        _registry = build_agent_registry()
    return _registry  # type: ignore[return-value]


def _create_agent(name: str) -> Agent:
    """Instantiate a named agent from the registry."""
    registry = _get_registry()
    if name not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found",
        )
    agent_class, kwargs, _ = registry[name]

    # Inject GitHub MCP config lazily for agents that need it
    from shared.registry import GITHUB_MCP_AGENTS, github_mcp_config  # noqa: PLC0415

    if name in GITHUB_MCP_AGENTS:
        kwargs = github_mcp_config()

    return agent_class(**(kwargs or {}))


# ---------------------------------------------------------------------------
# Auto-title generation
# ---------------------------------------------------------------------------

_title_client: anthropic.AsyncAnthropic | None = None


def _get_title_client() -> anthropic.AsyncAnthropic:
    """Get or create the Anthropic client for title generation."""
    global _title_client
    if _title_client is None:
        _title_client = anthropic.AsyncAnthropic()
    return _title_client


async def _generate_conversation_title(user_message: str, assistant_response: str) -> str | None:
    """Generate a short title for a conversation based on first exchange.

    Uses Claude Haiku for cost efficiency. Returns None on failure to avoid
    blocking the main conversation flow.
    """
    try:
        client = _get_title_client()
        response = await client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=30,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Generate a brief 3-6 word title for this conversation. "
                        "Return only the title, no quotes or punctuation.\n\n"
                        f"User: {user_message[:500]}\n\n"
                        f"Assistant: {assistant_response[:500]}"
                    ),
                }
            ],
        )
        content_block = response.content[0]
        if not isinstance(content_block, TextBlock):
            return None
        title = content_block.text.strip().strip("\"'")
        # Ensure reasonable length
        if len(title) > 100:
            title = title[:97] + "..."
        return title
    except Exception as e:
        logger.warning("Failed to generate conversation title: %s", e)
        return None


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

session_mgr = SessionManager()
claude_code_mgr = ClaudeCodeSessionManager()

# Dummy token used by _check_session_token to make the response time for a
# non-existent session indistinguishable from a wrong-token response.
_DUMMY_SESSION_TOKEN: str = secrets.token_urlsafe(32)

# Conversation store - initialized lazily if DATABASE_URL is set
_conversation_store: DatabaseConversationStore | None = None


def _get_conversation_store() -> DatabaseConversationStore:
    """Get the conversation store, raising if not configured."""
    global _conversation_store
    if _conversation_store is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation persistence not configured. Set DATABASE_URL environment variable.",
        )
    return _conversation_store


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start background tasks on startup, clean up on shutdown."""
    global _conversation_store

    session_mgr.start_cleanup_loop()
    claude_code_mgr.start_cleanup_loop()

    # Initialize conversation store if DATABASE_URL is set
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        _conversation_store = DatabaseConversationStore(database_url)
        await _conversation_store.initialize()
        logger.info("Conversation persistence enabled (PostgreSQL)")
    else:
        logger.info("Conversation persistence disabled (no DATABASE_URL)")

    if not _api_key:
        _disable_auth = os.getenv("DISABLE_AUTH", "").lower() in ("true", "1", "yes")
        if _disable_auth:
            logger.warning(
                "SECURITY: Authentication disabled via DISABLE_AUTH=true. "
                "All endpoints are publicly accessible."
            )
        else:
            raise RuntimeError(
                "API_KEY environment variable is required. "
                "Set API_KEY to enable authentication, or set DISABLE_AUTH=true "
                "to explicitly run without authentication (development only)."
            )

    logger.info("Agent REST API started")
    yield

    # Cleanup
    await claude_code_mgr.shutdown()
    if _conversation_store:
        await _conversation_store.close()
    logger.info("Agent REST API shutting down")


app = FastAPI(
    title="Agent REST API",
    description="REST interface for calling agents as stateless endpoints or multi-turn sessions.",
    version="0.1.0",
    lifespan=lifespan,
)


def _validate_cors_origin(origin: str) -> bool:
    """Validate a CORS origin string.

    Rejects wildcards, empty strings, and non-http(s) schemes.
    """
    if not origin or origin == "*":
        return False
    return origin.startswith(("http://", "https://"))


# Configure CORS for web UI
# Use explicit localhost origins plus any configured extras (even in dev mode)
allow_origins = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:8080",  # Production (same origin)
    "http://127.0.0.1:5173",  # Vite dev server (IP)
    "http://127.0.0.1:8080",  # Production (IP)
]
if extra_origins := os.getenv("CORS_ALLOWED_ORIGINS"):
    for origin in extra_origins.split(","):
        origin = origin.strip()
        if origin and _validate_cors_origin(origin):
            allow_origins.append(origin)
        elif origin:
            logger.warning("Ignoring invalid CORS origin: %s", origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Correlation ID Middleware (for distributed tracing)
# ---------------------------------------------------------------------------

# Allow alphanumeric characters and hyphens, 1-64 chars.
# Rejects header injection / log forgery payloads.
_CORRELATION_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


@app.middleware("http")
async def add_correlation_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Add correlation ID to each request for distributed tracing.

    If X-Correlation-ID header is present and passes validation, use it.
    Otherwise, generate a new UUID. The correlation ID is stored in a
    ContextVar for use by logging throughout the request lifecycle.
    """
    raw_id = request.headers.get("X-Correlation-ID")
    if raw_id and _CORRELATION_ID_RE.match(raw_id):
        correlation_id = raw_id
    else:
        correlation_id = str(uuid.uuid4())

    # Set correlation ID in context var for logging
    token = correlation_id_var.set(correlation_id)
    try:
        response = await call_next(request)
        # Add correlation ID to response headers for tracing
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    finally:
        # Reset to prevent context leaking between requests
        correlation_id_var.reset(token)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

_api_key = os.getenv("API_KEY")
_security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Verify API key.

    Requires a valid Authorization: Bearer <API_KEY> header when API_KEY
    is set. When DISABLE_AUTH=true (no API_KEY), all requests are allowed.

    Uses constant-time comparison to prevent timing attacks.
    """
    if not _api_key:
        return  # Auth not configured, allow all
    if not credentials or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        _api_key.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def _authenticate_websocket(websocket: WebSocket) -> dict | None:
    """Authenticate a WebSocket connection via initial message exchange.

    Always waits for an auth message from the client::

        {"type": "auth", "api_key": "...", "session_token": "..."}

    When API_KEY is not configured the ``api_key`` field is not checked, but the
    message must still be sent so that the ``session_token`` (required for
    session-ownership verification) can be read.

    Returns:
        The parsed auth payload dict on success, or ``None`` on failure.

    Uses constant-time comparison to prevent timing attacks.
    Credentials never appear in query strings, avoiding leakage via
    server logs, browser history, referrer headers, or proxy logs.
    """
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except Exception:  # TimeoutError, WebSocketDisconnect, JSONDecodeError, etc.
        return None
    if not isinstance(data, dict) or data.get("type") != "auth":
        return None
    if _api_key:
        ws_key = data.get("api_key")
        if not isinstance(ws_key, str):
            return None
        if not secrets.compare_digest(ws_key.encode("utf-8"), _api_key.encode("utf-8")):
            return None
    return data


def _check_session_token(
    session_id: str,
    x_session_token: str | None,
) -> ClaudeCodeSession:
    """Verify session ownership and return the session object.

    Called by REST endpoints that mutate session state (input, permission,
    resize, delete).  Raises HTTP 403 on mismatch to avoid leaking whether
    the session exists via a differential response.

    Args:
        session_id: The session ID from the URL path.
        x_session_token: Value of the ``X-Session-Token`` request header.

    Returns:
        The verified session object.

    Raises:
        HTTPException: 403 if the session is not found or the token is wrong.
    """
    session = claude_code_mgr.get_session(session_id)
    # Always run compare_digest to avoid timing side-channels.  When the session
    # doesn't exist or the provided token is not a string, we compare a dummy
    # value so the response time is indistinguishable from a wrong-token attempt.
    stored_token = session.session_token if session is not None else _DUMMY_SESSION_TOKEN
    candidate = x_session_token if isinstance(x_session_token, str) else ""
    digest_ok = secrets.compare_digest(
        candidate.encode("utf-8"),
        stored_token.encode("utf-8"),
    )
    if session is None or not digest_ok:
        raise HTTPException(status_code=403, detail="Session not found or invalid token")
    return session


# ---------------------------------------------------------------------------
# Rate Limiting (optional)
# ---------------------------------------------------------------------------

_rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"


def _get_rate_limit_key(request: Request) -> str:
    """Extract a rate-limit key from the request.

    Keys on the Bearer token prefix (first 16 chars) so that rate limits
    are tied to the authenticated identity rather than a spoofable IP.
    Falls back to the connecting client IP (request.client.host) when no
    Authorization header is present -- this avoids reading X-Forwarded-For,
    which clients can trivially forge.
    """
    auth_header: str | None = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()  # strip "Bearer " and any whitespace
        if token:
            # Use a prefix so we never store full secrets in rate-limit backends.
            return f"apikey:{token[:16]}"
    # Unauthenticated / health-check traffic: fall back to real peer IP.
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


if _rate_limit_enabled:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=_get_rate_limit_key)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    logger.info("Rate limiting enabled (keyed on API key, not IP)")
else:
    limiter = None


F = TypeVar("F", bound=Callable[..., Any])


class _TokenSnapshot:
    """Context manager that captures token usage delta for a single agent turn.

    Usage::

        async with _TokenSnapshot(agent) as snap:
            response_text = await agent.process_message(...)
        usage = snap.usage  # TokenUsage with input/output deltas

    Attributes:
        usage: Populated after ``__aexit__`` with the token delta.
    """

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self._input_before: int = 0
        self._output_before: int = 0
        self.usage: TokenUsage = TokenUsage(input_tokens=0, output_tokens=0)

    async def __aenter__(self) -> "_TokenSnapshot":
        self._input_before = self._agent.total_input_tokens
        self._output_before = self._agent.total_output_tokens
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.usage = TokenUsage(
            input_tokens=self._agent.total_input_tokens - self._input_before,
            output_tokens=self._agent.total_output_tokens - self._output_before,
        )


def rate_limit(limit_string: str) -> Callable[[F], F]:
    """Apply rate limit decorator only if rate limiting is enabled."""

    def decorator(func: F) -> F:
        if limiter is not None:
            return limiter.limit(limit_string)(func)  # type: ignore[return-value]
        return func

    return decorator


# ---------------------------------------------------------------------------
# Health & discovery
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.get("/agents", response_model=AgentListResponse)
async def list_agents(_: None = Depends(verify_api_key)) -> AgentListResponse:
    registry = _get_registry()
    return AgentListResponse(
        agents=[AgentInfo(name=name, description=desc) for name, (_, _, desc) in registry.items()]
    )


# ---------------------------------------------------------------------------
# Stateless one-shot endpoint
# ---------------------------------------------------------------------------


@app.post("/agents/{agent_name}/message", response_model=MessageResponse)
@rate_limit("10/minute")
async def stateless_message(
    request: Request,
    agent_name: str,
    body: MessageRequest,
    _: None = Depends(verify_api_key),
) -> MessageResponse:
    """Send a single message to an agent with no conversation history.

    A fresh agent is created, processes the message, and is discarded.
    Use this for simple request/response patterns where you don't need
    multi-turn context.
    """
    agent = _create_agent(agent_name)

    try:
        async with _TokenSnapshot(agent) as snap:
            response_text = await agent.process_message(body.message)
    except Exception as e:
        logger.exception("Agent %s failed processing message", _sanitize_log_input(agent_name))
        raise HTTPException(status_code=500, detail="Internal server error") from e

    return MessageResponse(
        response=response_text,
        agent=agent_name,
        session_id=None,
        usage=snap.usage,
    )


# ---------------------------------------------------------------------------
# Session-based (stateful) endpoints
# ---------------------------------------------------------------------------


@app.post("/sessions", response_model=SessionInfo, status_code=201)
@rate_limit("20/minute")
async def create_session(
    request: Request,
    body: SessionCreateRequest,
    _: None = Depends(verify_api_key),
) -> SessionInfo:
    """Create a new session with a persistent agent instance.

    The session keeps conversation history between calls so the agent
    can reference earlier messages.  Sessions expire after 1 hour of
    inactivity.
    """
    agent = _create_agent(body.agent)
    session = session_mgr.create(agent)
    return SessionInfo(
        session_id=session.id,
        agent=body.agent,
        message_count=0,
        context_stats=agent.get_context_stats(),
    )


@app.post("/sessions/{session_id}/message", response_model=MessageResponse)
@rate_limit("10/minute")
async def session_message(
    request: Request,
    session_id: str,
    body: MessageRequest,
    _: None = Depends(verify_api_key),
) -> MessageResponse:
    """Send a message within an existing session.

    Conversation history is preserved from prior calls in this session.
    """
    session = session_mgr.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    agent = session.agent

    try:
        async with _TokenSnapshot(agent) as snap:
            response_text = await agent.process_message(
                body.message,
                session_id=session_id,  # For Langfuse tracing
            )
    except Exception as e:
        logger.exception("Session %s failed processing message", _sanitize_log_input(session_id))
        raise HTTPException(status_code=500, detail="Internal server error") from e

    session.touch()

    return MessageResponse(
        response=response_text,
        agent=agent.get_agent_name(),
        session_id=session_id,
        usage=snap.usage,
    )


@app.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str, _: None = Depends(verify_api_key)) -> SessionInfo:
    """Get metadata about an active session."""
    session = session_mgr.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return SessionInfo(
        session_id=session.id,
        agent=session.agent.get_agent_name(),
        message_count=len(session.agent.messages),
        context_stats=session.agent.get_context_stats(),
    )


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, _: None = Depends(verify_api_key)) -> None:
    """End a session and free its resources."""
    if not session_mgr.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found or expired")


# ---------------------------------------------------------------------------
# Persistent conversation endpoints (database-backed)
# ---------------------------------------------------------------------------


@app.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    agent: str | None = Query(None, description="Filter by agent name"),
    limit: int = Query(50, ge=1, le=100, description="Max conversations to return"),
    offset: int = Query(0, ge=0, description="Number to skip for pagination"),
    _: None = Depends(verify_api_key),
) -> ConversationListResponse:
    """List all persistent conversations.

    Conversations are stored in PostgreSQL and survive server restarts.
    Use the agent query parameter to filter by specific agent type.
    """
    store = _get_conversation_store()
    conversations = await store.list_conversations(agent_name=agent, limit=limit, offset=offset)

    # Get total count for pagination
    stats = await store.get_stats()
    total = stats["total_conversations"]
    if agent:
        total = stats["conversations_by_agent"].get(agent, 0)

    return ConversationListResponse(
        conversations=[
            ConversationInfo(
                id=c.id,
                agent=c.agent_name,
                title=c.title,
                created_at=c.created_at,
                updated_at=c.updated_at,
                message_count=c.message_count,
                metadata=c.metadata,
            )
            for c in conversations
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.post("/conversations", response_model=ConversationInfo, status_code=201)
@rate_limit("20/minute")
async def create_conversation(
    request: Request,
    body: ConversationCreateRequest,
    _: None = Depends(verify_api_key),
) -> ConversationInfo:
    """Create a new persistent conversation.

    This creates a database record for the conversation. Use
    POST /conversations/{id}/message to add messages.
    """
    # Validate agent exists
    registry = _get_registry()
    if body.agent not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{body.agent}' not found. Available: {list(registry.keys())}",
        )

    store = _get_conversation_store()
    conv = await store.create_conversation(
        agent_name=body.agent,
        title=body.title,
        metadata=body.metadata,
    )

    return ConversationInfo(
        id=conv.id,
        agent=conv.agent_name,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=conv.message_count,
        metadata=conv.metadata,
    )


@app.get("/conversations/stats", response_model=ConversationStatsResponse)
async def get_conversation_stats(_: None = Depends(verify_api_key)) -> ConversationStatsResponse:
    """Get statistics about stored conversations."""
    store = _get_conversation_store()
    stats = await store.get_stats()

    return ConversationStatsResponse(
        total_conversations=stats["total_conversations"],
        total_messages=stats["total_messages"],
        conversations_by_agent=stats["conversations_by_agent"],
        oldest_conversation=stats["oldest_conversation"],
        newest_activity=stats["newest_activity"],
    )


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str, _: None = Depends(verify_api_key)
) -> ConversationDetail:
    """Get a conversation with its full message history."""
    store = _get_conversation_store()
    conv = await store.get_conversation_with_messages(conversation_id)

    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetail(
        id=conv.id,
        agent=conv.agent_name,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=conv.message_count,
        metadata=conv.metadata,
        messages=[
            ConversationMessage(
                role=m.role,
                content=m.content,
                turn_number=m.turn_number,
                created_at=m.created_at,
                token_count=m.token_count,
            )
            for m in conv.messages
        ],
    )


@app.post("/conversations/{conversation_id}/message", response_model=MessageResponse)
@rate_limit("10/minute")
async def conversation_message(
    request: Request,
    conversation_id: str,
    body: MessageRequest,
    _: None = Depends(verify_api_key),
) -> MessageResponse:
    """Send a message to a persistent conversation.

    This loads the conversation history, creates a fresh agent instance,
    processes the message, and saves both the user message and response
    to the database.
    """
    store = _get_conversation_store()

    # Load conversation
    conv = await store.get_conversation_with_messages(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Create agent instance
    agent = _create_agent(conv.agent_name)

    # Restore conversation history into agent
    # Type cast needed because msg.role is str but MessageParam expects Literal
    for msg in conv.messages:
        if msg.role in ("user", "assistant"):
            agent.messages.append({"role": msg.role, "content": msg.content})  # type: ignore[arg-type]

    try:
        async with _TokenSnapshot(agent) as snap:
            response_text = await agent.process_message(
                body.message,
                session_id=conversation_id,  # For Langfuse tracing
            )
    except Exception as e:
        logger.exception(
            "Conversation %s failed processing message", _sanitize_log_input(conversation_id)
        )
        raise HTTPException(status_code=500, detail="Internal server error") from e

    # Save both messages to database
    await store.add_messages_batch(
        conversation_id,
        [
            {"role": "user", "content": body.message},
            {"role": "assistant", "content": response_text},
        ],
    )

    # Auto-generate title on first message if no title set.
    # We check len(conv.messages) which reflects the state when we loaded the conversation,
    # before we saved the new messages. This is intentional - we want to generate a title
    # only for the first message exchange. Note: concurrent requests to a new conversation
    # could both trigger title generation, with the last one winning.
    is_first_message = len(conv.messages) == 0
    if is_first_message and not conv.title:
        title = await _generate_conversation_title(body.message, response_text)
        if title:
            await store.update_conversation(conversation_id, title=title)

    return MessageResponse(
        response=response_text,
        agent=conv.agent_name,
        session_id=None,
        conversation_id=conversation_id,
        usage=snap.usage,
    )


@app.patch("/conversations/{conversation_id}", response_model=ConversationInfo)
async def update_conversation(
    conversation_id: str, body: ConversationUpdateRequest, _: None = Depends(verify_api_key)
) -> ConversationInfo:
    """Update conversation title or metadata."""
    store = _get_conversation_store()
    conv = await store.update_conversation(
        conversation_id,
        title=body.title,
        metadata=body.metadata,
    )

    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationInfo(
        id=conv.id,
        agent=conv.agent_name,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=conv.message_count,
        metadata=conv.metadata,
    )


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, _: None = Depends(verify_api_key)) -> None:
    """Delete a conversation and all its messages."""
    store = _get_conversation_store()
    if not await store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@app.post("/conversations/{conversation_id}/clear", status_code=200)
async def clear_conversation_messages(
    conversation_id: str, _: None = Depends(verify_api_key)
) -> dict[str, Any]:
    """Clear all messages from a conversation (keeps the conversation itself)."""
    store = _get_conversation_store()

    # Check conversation exists
    conv = await store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    count = await store.clear_messages(conversation_id)
    return {"cleared_messages": count}


@app.get("/conversations/{conversation_id}/export", response_model=ConversationExport)
async def export_conversation(
    conversation_id: str, _: None = Depends(verify_api_key)
) -> ConversationExport:
    """Export a conversation as JSON for backup or analysis."""
    store = _get_conversation_store()
    conv = await store.get_conversation_with_messages(conversation_id)

    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationExport(
        conversation=ConversationInfo(
            id=conv.id,
            agent=conv.agent_name,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=conv.message_count,
            metadata=conv.metadata,
        ),
        messages=[
            ConversationMessage(
                role=m.role,
                content=m.content,
                turn_number=m.turn_number,
                created_at=m.created_at,
                token_count=m.token_count,
            )
            for m in conv.messages
        ],
        exported_at=datetime.now(UTC),
    )


@app.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=500, description="Max messages to return"),
    offset: int = Query(0, ge=0, description="Number to skip for pagination"),
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get paginated messages from a conversation."""
    store = _get_conversation_store()

    # Check conversation exists
    conv = await store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await store.get_messages(conversation_id, limit=limit, offset=offset)

    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "turn_number": m.turn_number,
                "created_at": m.created_at,
                "token_count": m.token_count,
            }
            for m in messages
        ],
        "total": conv.message_count,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Claude Code interactive session endpoints
# ---------------------------------------------------------------------------


@app.get("/claude-code/workspaces", response_model=list[ClaudeCodeWorkspaceInfo])
async def list_claude_code_workspaces(
    _: None = Depends(verify_api_key),
) -> list[ClaudeCodeWorkspaceInfo]:
    """List available Claude Code workspaces."""
    workspaces = await claude_code_mgr.list_workspaces()
    return [
        ClaudeCodeWorkspaceInfo(
            name=w.name,
            path=w.path,
            is_git_repo=w.is_git_repo,
            size_mb=w.size_mb,
            file_count=w.file_count,
            current_branch=w.current_branch,
        )
        for w in workspaces
    ]


@app.post("/claude-code/workspaces", response_model=ClaudeCodeWorkspaceInfo, status_code=201)
async def create_claude_code_workspace(
    body: ClaudeCodeCreateWorkspaceRequest,
    _: None = Depends(verify_api_key),
) -> ClaudeCodeWorkspaceInfo:
    """Create a new Claude Code workspace."""
    try:
        workspace = await claude_code_mgr.create_workspace(
            name=body.name,
            git_url=body.git_url,
        )
        return ClaudeCodeWorkspaceInfo(
            name=workspace.name,
            path=workspace.path,
            is_git_repo=workspace.is_git_repo,
            size_mb=workspace.size_mb,
            file_count=workspace.file_count,
            current_branch=workspace.current_branch,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.exception("Workspace creation failed")
        raise HTTPException(status_code=500, detail="Workspace creation failed") from e


@app.delete("/claude-code/workspaces/{workspace_name}", status_code=204)
async def delete_claude_code_workspace(
    workspace_name: str,
    force: bool = Query(False, description="Force deletion even with uncommitted changes"),
    _: None = Depends(verify_api_key),
) -> None:
    """Delete a Claude Code workspace."""
    try:
        await claude_code_mgr.delete_workspace(workspace_name, force=force)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/claude-code/sessions", response_model=list[ClaudeCodeSessionInfo])
async def list_claude_code_sessions(
    _: None = Depends(verify_api_key),
) -> list[ClaudeCodeSessionInfo]:
    """List active Claude Code sessions."""
    sessions = claude_code_mgr.list_sessions()
    return [
        ClaudeCodeSessionInfo(
            session_id=s["session_id"],
            workspace=s["workspace"],
            state=s["state"],
            created_at=datetime.fromisoformat(s["created_at"]),
            last_activity=datetime.fromisoformat(s["last_activity"]),
        )
        for s in sessions
    ]


@app.post("/claude-code/sessions", response_model=ClaudeCodeSessionInfo, status_code=201)
async def create_claude_code_session(
    body: ClaudeCodeSessionCreateRequest,
    _: None = Depends(verify_api_key),
) -> ClaudeCodeSessionInfo:
    """Create a new Claude Code session.

    This creates a session but doesn't start it - use the WebSocket endpoint
    to connect and receive output.
    """
    try:
        session = await claude_code_mgr.create_session(
            workspace_name=body.workspace,
            initial_prompt=body.initial_prompt,
        )
        # session_token is only included in the creation response so the caller
        # can prove ownership when opening the WebSocket.  Subsequent GET calls
        # omit it to avoid exposing the secret unnecessarily.
        return ClaudeCodeSessionInfo(
            session_id=session.session_id,
            workspace=session.workspace_path.name,
            state=session.state.value,
            created_at=session.created_at,
            last_activity=session.last_activity,
            session_token=session.session_token,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.exception("Session creation failed")
        raise HTTPException(status_code=500, detail="Session creation failed") from e


@app.get("/claude-code/sessions/{session_id}", response_model=ClaudeCodeSessionInfo)
async def get_claude_code_session(
    session_id: str, _: None = Depends(verify_api_key)
) -> ClaudeCodeSessionInfo:
    """Get information about a Claude Code session."""
    session = claude_code_mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return ClaudeCodeSessionInfo(
        session_id=session.session_id,
        workspace=session.workspace_path.name,
        state=session.state.value,
        created_at=session.created_at,
        last_activity=session.last_activity,
    )


@app.delete("/claude-code/sessions/{session_id}", status_code=204)
async def delete_claude_code_session(
    session_id: str,
    _: None = Depends(verify_api_key),
    x_session_token: str | None = Header(default=None),
) -> None:
    """Terminate a Claude Code session.

    Requires the ``X-Session-Token`` header matching the token returned when
    the session was created.
    """
    session = _check_session_token(session_id, x_session_token)
    # Use the verified session object directly rather than looking it up again
    await claude_code_mgr.terminate_session(session.session_id)


@app.post("/claude-code/sessions/{session_id}/input", status_code=204)
async def send_claude_code_input(
    session_id: str,
    body: ClaudeCodeInputRequest,
    _: None = Depends(verify_api_key),
    x_session_token: str | None = Header(default=None),
) -> None:
    """Send input to a Claude Code session (alternative to WebSocket).

    Requires the ``X-Session-Token`` header matching the token returned when
    the session was created.
    """
    session = _check_session_token(session_id, x_session_token)

    try:
        await session.send_input(body.text)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/claude-code/sessions/{session_id}/permission", status_code=204)
async def respond_claude_code_permission(
    session_id: str,
    body: ClaudeCodePermissionResponse,
    _: None = Depends(verify_api_key),
    x_session_token: str | None = Header(default=None),
) -> None:
    """Respond to a permission request in a Claude Code session.

    Requires the ``X-Session-Token`` header matching the token returned when
    the session was created.
    """
    session = _check_session_token(session_id, x_session_token)

    try:
        await session.respond_permission(body.approved)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/claude-code/sessions/{session_id}/resize", status_code=204)
async def resize_claude_code_terminal(
    session_id: str,
    body: ClaudeCodeResizeRequest,
    _: None = Depends(verify_api_key),
    x_session_token: str | None = Header(default=None),
) -> None:
    """Resize the terminal for a Claude Code session.

    Requires the ``X-Session-Token`` header matching the token returned when
    the session was created.
    """
    session = _check_session_token(session_id, x_session_token)

    await session.resize_terminal(body.rows, body.cols)


@app.websocket("/ws/claude-code/{session_id}")
async def claude_code_websocket(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time Claude Code interaction.

    Events sent from server:
    - {"type": "output", "data": "...", "timestamp": "..."}
    - {"type": "permission_request", "data": {...}, "timestamp": "..."}
    - {"type": "state_change", "data": {"state": "..."}, "timestamp": "..."}
    - {"type": "error", "data": "...", "timestamp": "..."}
    - {"type": "completed", "data": {"exit_code": ...}, "timestamp": "..."}

    Commands from client:
    - {"type": "input", "text": "..."}
    - {"type": "permission", "approved": true/false}
    - {"type": "resize", "rows": 40, "cols": 120}
    - {"type": "abort"}

    Authentication (when API_KEY is configured):
    The first message after connecting MUST be:
        {"type": "auth", "api_key": "...", "session_token": "<token from POST /claude-code/sessions>"}
    If auth fails or times out (10s), the connection is closed with code 4001.
    When API_KEY is not configured, only the session_token is required:
        {"type": "auth", "session_token": "<token>"}
    The session_token proves ownership of the specific session and prevents any
    other authenticated caller from connecting to sessions they did not create.
    """
    await websocket.accept()

    auth_data = await _authenticate_websocket(websocket)
    if auth_data is None:
        await websocket.close(code=4001, reason="Invalid or missing API key")
        return

    session = claude_code_mgr.get_session(session_id)

    # Verify session ownership via per-session token before revealing whether
    # the session exists.  Returning the same close code for "session not found"
    # and "wrong token" prevents authenticated callers from enumerating valid
    # session IDs by observing differential responses.
    #
    # Always run compare_digest to avoid timing side-channels: use
    # _DUMMY_SESSION_TOKEN so the work done when the session doesn't exist is
    # indistinguishable from a real wrong-token check.
    stored_token = session.session_token if session is not None else _DUMMY_SESSION_TOKEN
    provided_token = auth_data.get("session_token")
    candidate = provided_token if isinstance(provided_token, str) else ""
    digest_ok = secrets.compare_digest(
        candidate.encode("utf-8"),
        stored_token.encode("utf-8"),
    )
    if session is None or not digest_ok:
        await websocket.close(code=4003, reason="Session not found or invalid token")
        return

    async def send_events() -> None:
        """Send session events to WebSocket client."""
        try:
            async for event in session.events():
                await websocket.send_json(event.to_dict())
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error sending events: {e}")

    async def receive_commands() -> None:
        """Receive and process commands from WebSocket client."""
        try:
            while True:
                data = await websocket.receive_json()
                cmd_type = data.get("type")

                if cmd_type == "input":
                    text = data.get("text", "")
                    await session.send_input(text)

                elif cmd_type == "permission":
                    approved = data.get("approved", False)
                    await session.respond_permission(approved)

                elif cmd_type == "resize":
                    rows = data.get("rows", 40)
                    cols = data.get("cols", 120)
                    await session.resize_terminal(rows, cols)

                elif cmd_type == "abort":
                    await session.terminate()
                    break

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error receiving commands: {e}")

    # Run both tasks concurrently
    send_task = asyncio.create_task(send_events())
    receive_task = asyncio.create_task(receive_commands())

    try:
        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [send_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Don't terminate session on disconnect - it might be intentional
        # to reconnect later
        pass


# ---------------------------------------------------------------------------
# SMS Webhook for two-way agent-admin conversations
# ---------------------------------------------------------------------------

# SMS phone pool manager - initialized lazily
_sms_phone_pool: "SMSPhonePoolManager | None" = None


def _get_sms_phone_pool() -> "SMSPhonePoolManager | None":
    """Get the SMS phone pool manager if configured."""
    global _sms_phone_pool
    if _sms_phone_pool is not None:
        return _sms_phone_pool

    database_url = os.getenv("DATABASE_URL")
    phone_pool_config = os.getenv("TWILIO_PHONE_POOL")

    if not database_url or not phone_pool_config:
        return None

    from agent_framework.storage import SMSPhonePoolManager

    phone_numbers = [p.strip() for p in phone_pool_config.split(",") if p.strip()]
    if not phone_numbers:
        return None

    _sms_phone_pool = SMSPhonePoolManager(
        database_url=database_url,
        phone_numbers=phone_numbers,
    )
    return _sms_phone_pool


def _validate_twilio_signature(url: str, params: dict[str, str], signature: str) -> bool:
    """Validate Twilio request signature.

    Uses HMAC-SHA1 with the Twilio auth token to verify request authenticity.
    """
    import base64
    import hashlib
    import hmac

    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not auth_token:
        logger.warning("TWILIO_AUTH_TOKEN not set, cannot validate signature")
        return False

    # Build the data string for validation
    data = url
    if params:
        sorted_params = sorted(params.items())
        data += "".join(f"{k}{v}" for k, v in sorted_params)

    # Compute expected signature
    expected = hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1,
    ).digest()

    expected_b64 = base64.b64encode(expected).decode("utf-8")

    return hmac.compare_digest(expected_b64, signature)


@app.post("/webhooks/sms/incoming")
async def handle_incoming_sms(request: Request) -> Response:
    """
    Receive incoming SMS from Twilio and route to the correct conversation.

    Twilio sends POST requests with form data including:
    - From: sender phone number (the admin)
    - To: Twilio phone number from our pool
    - Body: message text
    - MessageSid: unique message identifier

    The webhook:
    1. Validates the Twilio signature (in production)
    2. Looks up which conversation the Twilio number is locked to
    3. Adds the admin's reply as a user message
    4. Processes through the agent
    5. Sends the agent's response back via SMS
    6. Releases the phone back to the pool

    Returns TwiML response (empty for async processing).
    """
    # Parse form data and sanitize for safe logging
    form = await request.form()
    from_phone = _sanitize_log_input(str(form.get("From", "")))
    to_phone = _sanitize_log_input(str(form.get("To", "")))
    message_body = _sanitize_log_input(str(form.get("Body", "")))

    logger.info(f"Incoming SMS from {from_phone} to {to_phone}")

    # Validate Twilio signature (can be explicitly skipped for local development)
    skip_validation = os.getenv("SKIP_TWILIO_SIGNATURE_VALIDATION", "").lower() == "true"
    if skip_validation:
        logger.warning(
            "SECURITY: Twilio signature validation is DISABLED via "
            "SKIP_TWILIO_SIGNATURE_VALIDATION=true. Do NOT use in production."
        )
    if not skip_validation:
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        params = {k: str(v) for k, v in form.items()}

        if not _validate_twilio_signature(url, params, signature):
            logger.warning(f"Invalid Twilio signature for SMS from {from_phone}")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="text/xml",
            )

    # Get phone pool
    phone_pool = _get_sms_phone_pool()
    if phone_pool is None:
        logger.error("SMS phone pool not configured, cannot route incoming SMS")
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="text/xml",
        )

    # Track whether we have a phone lock that needs releasing
    phone_locked = False

    try:
        await phone_pool.initialize()

        # Look up conversation by the Twilio number that received the message
        phone_entry = await phone_pool.get_by_phone_number(to_phone)

        if phone_entry is None or phone_entry.status != "locked":
            logger.warning(f"SMS to unlocked/unknown number {to_phone}")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="text/xml",
            )

        # We have a valid locked phone - mark for cleanup
        phone_locked = True
        conversation_id = phone_entry.locked_to_conversation_id
        agent_name = phone_entry.locked_to_agent

        if not conversation_id:
            logger.error(f"Phone {to_phone} locked but no conversation ID")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="text/xml",
            )

        logger.info(
            f"Routing SMS reply to conversation {_sanitize_log_input(conversation_id)} "
            f"(agent: {_sanitize_log_input(agent_name or 'unknown')})"
        )

        # Get conversation store
        store = _get_conversation_store()

        # Load conversation
        conv = await store.get_conversation_with_messages(conversation_id)
        if conv is None:
            logger.error(f"Conversation {conversation_id} not found")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="text/xml",
            )

        # Create agent instance
        agent = _create_agent(conv.agent_name)

        # Restore conversation history
        for msg in conv.messages:
            if msg.role in ("user", "assistant"):
                agent.messages.append({"role": msg.role, "content": msg.content})

        # Process the SMS reply through the agent
        try:
            response_text = await agent.process_message(
                message_body,
                session_id=conversation_id,
            )
        except Exception as e:
            logger.exception(f"Error processing SMS reply for conversation {conversation_id}")
            response_text = f"Error processing your reply: {str(e)[:100]}"

        # Save both messages to database
        await store.add_messages_batch(
            conversation_id,
            [
                {"role": "user", "content": f"[SMS Reply] {message_body}"},
                {"role": "assistant", "content": response_text},
            ],
        )

        # Send response back via SMS
        await _send_sms_response(
            to_phone=from_phone,
            from_phone=to_phone,
            body=response_text,
            agent_name=agent_name,
        )

        logger.info(f"SMS conversation completed for {conversation_id}")

    except Exception as e:
        logger.exception(f"Error handling incoming SMS: {e}")

    finally:
        # Always release the phone back to pool if we acquired a lock
        if phone_locked:
            try:
                await phone_pool.release(to_phone)
            except Exception as release_error:
                logger.error(f"Failed to release phone {to_phone}: {release_error}")

    # Return empty TwiML (we handle responses async)
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="text/xml",
    )


async def _send_sms_response(
    to_phone: str,
    from_phone: str,
    body: str,
    agent_name: str | None,
) -> bool:
    """Send SMS response back to admin.

    Args:
        to_phone: Admin phone number
        from_phone: Twilio phone number
        body: Message body
        agent_name: Agent name for prefix

    Returns:
        True if sent successfully
    """
    from urllib.parse import quote

    import httpx

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        logger.error("Twilio credentials not configured")
        return False

    # Add agent prefix and truncate if needed
    if agent_name:
        safe_agent_name = agent_name.replace("_", "-").title()
        message_body = f"[{safe_agent_name}] {body}"
    else:
        message_body = body

    # Truncate to SMS limit
    if len(message_body) > 1600:
        message_body = message_body[:1597] + "..."

    payload = {
        "To": to_phone,
        "From": from_phone,
        "Body": message_body,
    }

    url = f"https://api.twilio.com/2010-04-01/Accounts/{quote(account_sid, safe='')}/Messages.json"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(account_sid, auth_token),
            )

            if response.status_code == 201:
                logger.info(f"SMS response sent to {to_phone}")
                return True
            else:
                logger.error(f"Failed to send SMS response: {response.status_code}")
                return False

    except Exception as e:
        logger.exception(f"Error sending SMS response: {e}")
        return False


# ---------------------------------------------------------------------------
# Web UI static file serving (production mode)
# ---------------------------------------------------------------------------

WEBUI_DIST = Path(__file__).parent.parent / "webui" / "dist"

if WEBUI_DIST.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=WEBUI_DIST / "assets"), name="assets")
    logger.info(f"Serving Web UI static assets from {WEBUI_DIST / 'assets'}")

    # SPA catch-all route - must be LAST route
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve the React SPA for all non-API routes."""
        # Don't catch API routes
        if full_path.startswith(
            (
                "agents/",
                "sessions/",
                "conversations/",
                "health",
                "assets/",
                "claude-code/",
                "ws/",
                "webhooks/",
            )
        ):
            raise HTTPException(status_code=404, detail="Not found")

        # Serve index.html for all other routes (SPA routing)
        index_file = WEBUI_DIST / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        raise HTTPException(
            status_code=404,
            detail="Web UI not built. Run 'npm run build' in webui/frontend/",
        )
else:
    logger.info("Web UI not built. To enable, run 'npm run build' in webui/frontend/")
