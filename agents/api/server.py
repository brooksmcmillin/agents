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

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_framework import Agent
from agent_framework.storage import DatabaseConversationStore

from .models import (
    AgentInfo,
    AgentListResponse,
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
# Application
# ---------------------------------------------------------------------------

session_mgr = SessionManager()

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
allow_origins = ["*"] if os.getenv("DEV_MODE", "false").lower() == "true" else [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:8080",  # Production (same origin)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        agents=[
            AgentInfo(name=name, description=desc)
            for name, (_, _, desc) in registry.items()
        ]
    )


# ---------------------------------------------------------------------------
# Stateless one-shot endpoint
# ---------------------------------------------------------------------------


@app.post("/agents/{agent_name}/message", response_model=MessageResponse)
async def stateless_message(agent_name: str, body: MessageRequest) -> MessageResponse:
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
        logger.exception("Agent %s failed processing message", agent_name)
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
async def create_session(body: SessionCreateRequest) -> SessionInfo:
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
async def session_message(session_id: str, body: MessageRequest) -> MessageResponse:
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
        logger.exception("Session %s failed processing message", session_id)
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
async def create_conversation(body: ConversationCreateRequest) -> ConversationInfo:
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
async def conversation_message(
    conversation_id: str, body: MessageRequest
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
        logger.exception("Conversation %s failed processing message", conversation_id)
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Save both messages to database
    await store.add_messages_batch(
        conversation_id,
        [
            {"role": "user", "content": body.message},
            {"role": "assistant", "content": response_text},
        ],
    )

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
        exported_at=datetime.now(timezone.utc),
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
        if full_path.startswith(("agents/", "sessions/", "conversations/", "health", "assets/")):
            raise HTTPException(status_code=404, detail="Not found")

        # Serve index.html for all other routes (SPA routing)
        index_file = WEBUI_DIST / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        raise HTTPException(status_code=404, detail="Web UI not built. Run 'npm run build' in agents/webui/frontend/")
else:
    logger.info("Web UI not built. To enable, run 'npm run build' in agents/webui/frontend/")
