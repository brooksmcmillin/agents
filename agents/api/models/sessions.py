"""Session management models."""

from typing import Any

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """Request body for creating a new session."""

    agent: str = Field(..., description="Agent name (e.g. 'pr', 'chatbot')")


class SessionInfo(BaseModel):
    """Information about an active session."""

    session_id: str
    agent: str
    message_count: int
    context_stats: dict[str, Any]
