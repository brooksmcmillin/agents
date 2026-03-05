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

import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_framework.storage import SMSPhonePoolManager

import anthropic
from agent_framework import Agent
from agent_framework.storage import Conversation, DatabaseConversationStore, Message
from agent_framework.utils.errors import PromptInjectionError
from agent_framework.utils.sanitize import sanitize_log_input
from anthropic.types import TextBlock
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
)
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import (
    _DISABLE_AUTH_DEFAULT_CIDRS,  # noqa: F401 - re-exported for backward compat
    _get_api_key,
    _get_rate_limit_key,  # noqa: F401 - re-exported for backward compat
    _ip_in_cidr_list,  # noqa: F401 - re-exported for backward compat
    _parse_cidr_list,  # noqa: F401 - re-exported for backward compat
    check_session_token,
    setup_rate_limiting,
    verify_api_key,
)
from .auth import (
    authenticate_websocket_connection as _authenticate_websocket,  # noqa: F401
)
from .auth import (
    rate_limit as _rate_limit_func,
)
from .claude_code_sessions import ClaudeCodeSession, ClaudeCodeSessionManager
from .middleware import (
    _CORRELATION_ID_RE,  # noqa: F401 - re-exported for backward compat
    _validate_cors_origin,  # noqa: F401 - re-exported for backward compat
    setup_correlation_id_middleware,
    setup_cors,
)
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
from .websocket import claude_code_websocket_handler

logger = logging.getLogger(__name__)

# Backward-compatible module-level API key (used by lifespan and tests).
# Auth functions in api.auth read from environment dynamically.
_api_key = os.getenv("API_KEY")


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


def _check_session_token(
    session_id: str,
    x_session_token: str | None,
) -> ClaudeCodeSession:
    """Verify session ownership and return the session object.

    Delegates to auth.check_session_token with the session looked up
    from claude_code_mgr.
    """
    session = claude_code_mgr.get_session(session_id)
    return check_session_token(session, session_id, x_session_token, _DUMMY_SESSION_TOKEN)


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

    # DISABLE_AUTH is only honoured when ENV=development is explicitly set.
    # Absence of ENV=production is NOT sufficient – staging/CI environments that
    # omit the variable would otherwise be fully unauthenticated.
    _disable_auth = os.getenv("DISABLE_AUTH", "").lower() in ("true", "1", "yes")
    _env = os.getenv("ENV", "").lower()
    if _disable_auth and _env != "development":
        raise RuntimeError(
            "DISABLE_AUTH=true requires ENV=development to be explicitly set. "
            "This prevents accidental exposure in staging or CI environments. "
            "Set API_KEY to enable authentication, or set ENV=development if "
            "you intentionally want to run without authentication."
        )

    if not _get_api_key():
        if _disable_auth:
            allowed_ips_raw = os.getenv("DISABLE_AUTH_ALLOWED_IPS", "127.0.0.0/8,::1/128")
            logger.warning(
                "SECURITY: Authentication disabled via DISABLE_AUTH=true. Access restricted to: %s",
                allowed_ips_raw,
            )
        else:
            raise RuntimeError(
                "API_KEY environment variable is required. "
                "Set API_KEY to enable authentication, or set DISABLE_AUTH=true "
                "with ENV=development to explicitly run without authentication "
                "(development only)."
            )

    # Fail fast if Twilio signature validation is disabled in production.
    _skip_twilio = os.getenv("SKIP_TWILIO_SIGNATURE_VALIDATION", "").lower() == "true"
    if _skip_twilio and _env == "production":
        raise RuntimeError(
            "SKIP_TWILIO_SIGNATURE_VALIDATION=true is not allowed when ENV=production. "
            "Remove SKIP_TWILIO_SIGNATURE_VALIDATION or set it to false in production."
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

# Configure CORS middleware
setup_cors(app)

# Configure correlation ID middleware
setup_correlation_id_middleware(app)

# Configure rate limiting
limiter = setup_rate_limiting(app)


def rate_limit(limit_string: str) -> Any:
    """Apply rate limit decorator only if rate limiting is enabled."""
    return _rate_limit_func(limit_string, limiter)


# ---------------------------------------------------------------------------
# Token usage tracking
# ---------------------------------------------------------------------------


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
    except PromptInjectionError as e:
        logger.warning(
            "Agent %s blocked message: prompt injection detected", sanitize_log_input(agent_name)
        )
        raise HTTPException(status_code=400, detail="Message blocked by security policy") from e
    except Exception as e:
        logger.exception("Agent %s failed processing message", sanitize_log_input(agent_name))
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
    except PromptInjectionError as e:
        logger.warning(
            "Session %s blocked message: prompt injection detected", sanitize_log_input(session_id)
        )
        raise HTTPException(status_code=400, detail="Message blocked by security policy") from e
    except Exception as e:
        logger.exception("Session %s failed processing message", sanitize_log_input(session_id))
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


def _db_conv_to_info(conv: Conversation) -> ConversationInfo:
    """Convert a database Conversation object to a ConversationInfo response model."""
    return ConversationInfo(
        id=conv.id,
        agent=conv.agent_name,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=conv.message_count,
        metadata=conv.metadata,
    )


def _db_msg_to_response(m: Message) -> ConversationMessage:
    """Convert a database Message object to a ConversationMessage response model."""
    return ConversationMessage(
        role=m.role,
        content=m.content,
        turn_number=m.turn_number,
        created_at=m.created_at,
        token_count=m.token_count,
    )


@app.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    agent: str | None = Query(None, description="Filter by agent name"),
    limit: int = Query(50, ge=1, le=100, description="Max conversations to return"),
    offset: int = Query(0, ge=0, description="Number to skip for pagination"),
    _: None = Depends(verify_api_key),
) -> ConversationListResponse:
    """List all persistent conversations."""
    store = _get_conversation_store()
    conversations = await store.list_conversations(agent_name=agent, limit=limit, offset=offset)

    # Get total count for pagination
    stats = await store.get_stats()
    total = stats["total_conversations"]
    if agent:
        total = stats["conversations_by_agent"].get(agent, 0)

    return ConversationListResponse(
        conversations=[_db_conv_to_info(c) for c in conversations],
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
    """Create a new persistent conversation."""
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

    return _db_conv_to_info(conv)


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
        **_db_conv_to_info(conv).model_dump(),
        messages=[_db_msg_to_response(m) for m in conv.messages],
    )


@app.post("/conversations/{conversation_id}/message", response_model=MessageResponse)
@rate_limit("10/minute")
async def conversation_message(
    request: Request,
    conversation_id: str,
    body: MessageRequest,
    _: None = Depends(verify_api_key),
) -> MessageResponse:
    """Send a message to a persistent conversation."""
    store = _get_conversation_store()

    conv = await store.get_conversation_with_messages(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Create agent instance
    agent = _create_agent(conv.agent_name)

    # Restore conversation history into agent
    for msg in conv.messages:
        if msg.role in ("user", "assistant"):
            agent.messages.append({"role": msg.role, "content": msg.content})  # type: ignore[arg-type]

    try:
        async with _TokenSnapshot(agent) as snap:
            response_text = await agent.process_message(
                body.message,
                session_id=conversation_id,  # For Langfuse tracing
            )
    except PromptInjectionError as e:
        logger.warning(
            "Conversation %s blocked message: prompt injection detected",
            sanitize_log_input(conversation_id),
        )
        raise HTTPException(status_code=400, detail="Message blocked by security policy") from e
    except Exception as e:
        logger.exception(
            "Conversation %s failed processing message", sanitize_log_input(conversation_id)
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

    return _db_conv_to_info(conv)


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
        conversation=_db_conv_to_info(conv),
        messages=[_db_msg_to_response(m) for m in conv.messages],
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
    """Create a new Claude Code session."""
    try:
        session = await claude_code_mgr.create_session(
            workspace_name=body.workspace,
            initial_prompt=body.initial_prompt,
        )
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
    """Terminate a Claude Code session."""
    session = _check_session_token(session_id, x_session_token)
    await claude_code_mgr.terminate_session(session.session_id)


@app.post("/claude-code/sessions/{session_id}/input", status_code=204)
async def send_claude_code_input(
    session_id: str,
    body: ClaudeCodeInputRequest,
    _: None = Depends(verify_api_key),
    x_session_token: str | None = Header(default=None),
) -> None:
    """Send input to a Claude Code session (alternative to WebSocket)."""
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
    """Respond to a permission request in a Claude Code session."""
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
    """Resize the terminal for a Claude Code session."""
    session = _check_session_token(session_id, x_session_token)

    await session.resize_terminal(body.rows, body.cols)


@app.websocket("/ws/claude-code/{session_id}")
async def claude_code_websocket(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time Claude Code interaction."""
    await claude_code_websocket_handler(
        websocket=websocket,
        session_id=session_id,
        claude_code_mgr=claude_code_mgr,
        dummy_session_token=_DUMMY_SESSION_TOKEN,
    )


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
    """Validate Twilio request signature."""
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
    """Receive incoming SMS from Twilio and route to the correct conversation."""
    # Parse form data and sanitize for safe logging
    form = await request.form()
    from_phone = sanitize_log_input(str(form.get("From", "")))
    to_phone = sanitize_log_input(str(form.get("To", "")))
    message_body = sanitize_log_input(str(form.get("Body", "")))

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
            f"Routing SMS reply to conversation {sanitize_log_input(conversation_id)} "
            f"(agent: {sanitize_log_input(agent_name or 'unknown')})"
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
        except PromptInjectionError:
            logger.warning(
                f"SMS reply for conversation {conversation_id} blocked: prompt injection detected"
            )
            response_text = "Your message was blocked by our security policy."
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
    """Send SMS response back to admin."""
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
