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
    uv run python -m agents.api
"""

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from agent_framework import Agent
from agent_framework.storage import DatabaseConversationStore
from anthropic.types import TextBlock
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Security,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .claude_code_sessions import ClaudeCodeSessionManager
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
# Maps short name -> (AgentClass, constructor kwargs, human description).
# Populated lazily by _build_registry() on first access so that imports
# only happen when the server actually starts.
# ---------------------------------------------------------------------------

_registry: dict[str, tuple[type[Agent], dict[str, Any] | None, str]] | None = None


def _build_registry() -> dict[str, tuple[type[Agent], dict[str, Any] | None, str]]:
    """Build the agent registry.

    Imports are deferred to here so the module can be imported without
    triggering heavyweight side-effects (Anthropic client init, etc.).
    """
    from agents.business_advisor.main import BusinessAdvisorAgent
    from agents.chatbot.main import ChatbotAgent
    from agents.events.main import EventsAgent
    from agents.pr_agent.main import PRAgent
    from agents.security_researcher.main import SecurityResearcherAgent
    from agents.task_manager.main import TaskManagerAgent
    from shared import DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL

    return {
        "chatbot": (
            ChatbotAgent,
            None,
            "General-purpose chatbot with full MCP tool access",
        ),
        "events": (
            EventsAgent,
            None,
            "Local events discovery with preference learning",
        ),
        "pr": (
            PRAgent,
            None,
            "PR and content strategy assistant",
        ),
        "tasks": (
            TaskManagerAgent,
            {
                "mcp_urls": [os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)],
                "mcp_client_config": {"prefer_device_flow": True},
            },
            "Interactive task management agent",
        ),
        "security": (
            SecurityResearcherAgent,
            None,
            "Security research assistant",
        ),
        "business": (
            BusinessAdvisorAgent,
            {
                "mcp_urls": ["https://api.githubcopilot.com/mcp/"],
                "mcp_client_config": {
                    "auth_token": os.getenv("GITHUB_MCP_PAT"),
                },
            },
            "Business strategy and monetization advisor",
        ),
    }


def _get_registry() -> dict[str, tuple[type[Agent], dict[str, Any] | None, str]]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def _create_agent(name: str) -> Agent:
    """Instantiate a named agent from the registry."""
    registry = _get_registry()
    if name not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found. Available: {list(registry.keys())}",
        )
    agent_class, kwargs, _ = registry[name]
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
async def lifespan(app: FastAPI):
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

# Configure CORS for web UI
# Allow any origin in development, specific origins in production
allow_origins = (
    ["*"]
    if os.getenv("DEV_MODE", "false").lower() == "true"
    else [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:8080",  # Production (same origin)
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Authentication (optional)
# ---------------------------------------------------------------------------

_api_key = os.getenv("API_KEY")
_security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Verify API key if configured.

    If API_KEY environment variable is not set, authentication is disabled
    and all requests are allowed. If set, requests must include a valid
    Authorization: Bearer <API_KEY> header.

    Uses constant-time comparison to prevent timing attacks.
    """
    if not _api_key:
        return  # Auth not configured, allow all
    if not credentials or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        _api_key.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Rate Limiting (optional)
# ---------------------------------------------------------------------------

_rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"

if _rate_limit_enabled:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    logger.info("Rate limiting enabled")
else:
    limiter = None


def rate_limit(limit_string: str):
    """Apply rate limit decorator only if rate limiting is enabled."""

    def decorator(func):
        if limiter is not None:
            return limiter.limit(limit_string)(func)
        return func

    return decorator


# ---------------------------------------------------------------------------
# Health & discovery
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(agents_available=len(_get_registry()))


@app.get("/agents", response_model=AgentListResponse)
async def list_agents() -> AgentListResponse:
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
    input_before = agent.total_input_tokens
    output_before = agent.total_output_tokens

    try:
        response_text = await agent.process_message(body.message)
    except Exception as e:
        logger.exception("Agent %s failed processing message", _sanitize_log_input(agent_name))
        raise HTTPException(status_code=500, detail=str(e)) from e

    return MessageResponse(
        response=response_text,
        agent=agent_name,
        session_id=None,
        usage=TokenUsage(
            input_tokens=agent.total_input_tokens - input_before,
            output_tokens=agent.total_output_tokens - output_before,
        ),
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
    input_before = agent.total_input_tokens
    output_before = agent.total_output_tokens

    try:
        response_text = await agent.process_message(body.message)
    except Exception as e:
        logger.exception("Session %s failed processing message", _sanitize_log_input(session_id))
        raise HTTPException(status_code=500, detail=str(e)) from e

    session.touch()

    return MessageResponse(
        response=response_text,
        agent=agent.get_agent_name(),
        session_id=session_id,
        usage=TokenUsage(
            input_tokens=agent.total_input_tokens - input_before,
            output_tokens=agent.total_output_tokens - output_before,
        ),
    )


@app.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str) -> SessionInfo:
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
async def delete_session(session_id: str) -> None:
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
async def get_conversation_stats() -> ConversationStatsResponse:
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
async def get_conversation(conversation_id: str) -> ConversationDetail:
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

    input_before = agent.total_input_tokens
    output_before = agent.total_output_tokens

    try:
        response_text = await agent.process_message(body.message)
    except Exception as e:
        logger.exception(
            "Conversation %s failed processing message", _sanitize_log_input(conversation_id)
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

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
        usage=TokenUsage(
            input_tokens=agent.total_input_tokens - input_before,
            output_tokens=agent.total_output_tokens - output_before,
        ),
    )


@app.patch("/conversations/{conversation_id}", response_model=ConversationInfo)
async def update_conversation(
    conversation_id: str, body: ConversationUpdateRequest
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
async def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and all its messages."""
    store = _get_conversation_store()
    if not await store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@app.post("/conversations/{conversation_id}/clear", status_code=200)
async def clear_conversation_messages(conversation_id: str) -> dict[str, Any]:
    """Clear all messages from a conversation (keeps the conversation itself)."""
    store = _get_conversation_store()

    # Check conversation exists
    conv = await store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    count = await store.clear_messages(conversation_id)
    return {"cleared_messages": count}


@app.get("/conversations/{conversation_id}/export", response_model=ConversationExport)
async def export_conversation(conversation_id: str) -> ConversationExport:
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
async def list_claude_code_workspaces() -> list[ClaudeCodeWorkspaceInfo]:
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
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/claude-code/workspaces/{workspace_name}", status_code=204)
async def delete_claude_code_workspace(
    workspace_name: str,
    force: bool = Query(False, description="Force deletion even with uncommitted changes"),
) -> None:
    """Delete a Claude Code workspace."""
    try:
        await claude_code_mgr.delete_workspace(workspace_name, force=force)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/claude-code/sessions", response_model=list[ClaudeCodeSessionInfo])
async def list_claude_code_sessions() -> list[ClaudeCodeSessionInfo]:
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
        return ClaudeCodeSessionInfo(
            session_id=session.session_id,
            workspace=session.workspace_path.name,
            state=session.state.value,
            created_at=session.created_at,
            last_activity=session.last_activity,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/claude-code/sessions/{session_id}", response_model=ClaudeCodeSessionInfo)
async def get_claude_code_session(session_id: str) -> ClaudeCodeSessionInfo:
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
async def delete_claude_code_session(session_id: str) -> None:
    """Terminate a Claude Code session."""
    if not await claude_code_mgr.terminate_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/claude-code/sessions/{session_id}/input", status_code=204)
async def send_claude_code_input(
    session_id: str,
    body: ClaudeCodeInputRequest,
) -> None:
    """Send input to a Claude Code session (alternative to WebSocket)."""
    session = claude_code_mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        await session.send_input(body.text)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/claude-code/sessions/{session_id}/permission", status_code=204)
async def respond_claude_code_permission(
    session_id: str,
    body: ClaudeCodePermissionResponse,
) -> None:
    """Respond to a permission request in a Claude Code session."""
    session = claude_code_mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        await session.respond_permission(body.approved)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/claude-code/sessions/{session_id}/resize", status_code=204)
async def resize_claude_code_terminal(
    session_id: str,
    body: ClaudeCodeResizeRequest,
) -> None:
    """Resize the terminal for a Claude Code session."""
    session = claude_code_mgr.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    await session.resize_terminal(body.rows, body.cols)


@app.websocket("/ws/claude-code/{session_id}")
async def claude_code_websocket(websocket: WebSocket, session_id: str):
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
    """
    await websocket.accept()

    session = claude_code_mgr.get_session(session_id)
    if session is None:
        await websocket.close(code=4004, reason="Session not found")
        return

    async def send_events():
        """Send session events to WebSocket client."""
        try:
            async for event in session.events():
                await websocket.send_json(event.to_dict())
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error sending events: {e}")

    async def receive_commands():
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
# Web UI static file serving (production mode)
# ---------------------------------------------------------------------------

WEBUI_DIST = Path(__file__).parent.parent / "webui" / "dist"

if WEBUI_DIST.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=WEBUI_DIST / "assets"), name="assets")
    logger.info(f"Serving Web UI static assets from {WEBUI_DIST / 'assets'}")

    # SPA catch-all route - must be LAST route
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for all non-API routes."""
        # Don't catch API routes
        if full_path.startswith(
            ("agents/", "sessions/", "conversations/", "health", "assets/", "claude-code/", "ws/")
        ):
            raise HTTPException(status_code=404, detail="Not found")

        # Serve index.html for all other routes (SPA routing)
        index_file = WEBUI_DIST / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        raise HTTPException(
            status_code=404,
            detail="Web UI not built. Run 'npm run build' in agents/webui/frontend/",
        )
else:
    logger.info("Web UI not built. To enable, run 'npm run build' in agents/webui/frontend/")
