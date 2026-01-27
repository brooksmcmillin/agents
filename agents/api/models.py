"""Pydantic models for the Agent REST API."""

from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    """Request body for sending a message to an agent."""

    message: str = Field(..., min_length=1, description="The user message to send to the agent")


class TokenUsage(BaseModel):
    """Token usage statistics for a request."""

    input_tokens: int
    output_tokens: int


class MessageResponse(BaseModel):
    """Response from an agent after processing a message."""

    response: str
    agent: str
    session_id: str | None = None
    usage: TokenUsage


class SessionCreateRequest(BaseModel):
    """Request body for creating a new session."""

    agent: str = Field(..., description="Agent name (e.g. 'pr', 'chatbot')")


class SessionInfo(BaseModel):
    """Information about an active session."""

    session_id: str
    agent: str
    message_count: int
    context_stats: dict


class AgentInfo(BaseModel):
    """Public metadata about an available agent."""

    name: str
    description: str


class AgentListResponse(BaseModel):
    """Response listing available agents."""

    agents: list[AgentInfo]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    agents_available: int
