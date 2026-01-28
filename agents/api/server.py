"""FastAPI REST server exposing agents as HTTP endpoints.

Provides two usage patterns:

1. **Stateless** - Fire a single prompt at an agent and get a response:
       POST /agents/{name}/message  {"message": "..."}

2. **Stateful sessions** - Multi-turn conversations with preserved history:
       POST   /sessions              {"agent": "pr"}
       POST   /sessions/{id}/message {"message": "..."}
       GET    /sessions/{id}
       DELETE /sessions/{id}

Run with:
    uv run python -m agents.api
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from agent_framework import Agent

from .models import (
    AgentInfo,
    AgentListResponse,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks on startup, clean up on shutdown."""
    session_mgr.start_cleanup_loop()
    logger.info("Agent REST API started")
    yield
    logger.info("Agent REST API shutting down")


app = FastAPI(
    title="Agent REST API",
    description="REST interface for calling agents as stateless endpoints or multi-turn sessions.",
    version="0.1.0",
    lifespan=lifespan,
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
