"""Core API models for agents, health, and messaging."""

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, v: str) -> str:
        """Reject whitespace-only messages.

        An empty or whitespace-only message cannot be meaningfully processed
        by an agent and is almost always a caller bug. Reject with a clear
        error rather than silently forwarding blank content.

        Args:
            v: The message string to validate.

        Returns:
            The original message string if it contains non-whitespace content.

        Raises:
            ValueError: If the message is empty or contains only whitespace.
        """
        if not v.strip():
            raise ValueError("Message content must not be empty or whitespace-only")
        return v


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
