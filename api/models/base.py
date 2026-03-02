"""Core API models for agents, health, and messaging."""

from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    """Request body for sending a message to an agent.

    ⚠️ SECURITY: Message Content is Untrusted Input

    The message field contains user-supplied input that should be treated
    as potentially adversarial. This message will be processed by agents
    and may be stored in conversation history without sanitization.

    Agents receiving this message should be aware that it may contain:
    - Prompt injection attempts
    - Jailbreak payloads
    - Instructions designed to manipulate LLM behavior
    - Attempts to expose sensitive information
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=32_000,
        description="The user message to send to the agent (untrusted input)",
    )


class TokenUsage(BaseModel):
    """Token usage statistics for a request."""

    input_tokens: int
    output_tokens: int


class MessageResponse(BaseModel):
    """Response from an agent after processing a message."""

    response: str
    agent: str
    session_id: str | None = None
    conversation_id: str | None = None
    usage: TokenUsage


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
