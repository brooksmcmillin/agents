"""Pydantic models for the Agent REST API."""

from datetime import datetime
from typing import Any

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
    conversation_id: str | None = None
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


# ---------------------------------------------------------------------------
# Conversation persistence models
# ---------------------------------------------------------------------------


class ConversationCreateRequest(BaseModel):
    """Request body for creating a new conversation."""

    agent: str = Field(..., description="Agent name (e.g. 'pr', 'chatbot')")
    title: str | None = Field(None, description="Optional title for the conversation")
    metadata: dict[str, Any] | None = Field(None, description="Optional metadata")


class ConversationUpdateRequest(BaseModel):
    """Request body for updating a conversation."""

    title: str | None = Field(None, description="New title for the conversation")
    metadata: dict[str, Any] | None = Field(None, description="New metadata")


class ConversationMessage(BaseModel):
    """A single message in a conversation."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: Any = Field(..., description="Message content (string or content blocks)")
    turn_number: int = Field(..., description="Position in conversation (0-indexed)")
    created_at: datetime
    token_count: int | None = None


class ConversationInfo(BaseModel):
    """Information about a conversation."""

    id: str
    agent: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationDetail(ConversationInfo):
    """Conversation with full message history."""

    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationListResponse(BaseModel):
    """Response listing conversations."""

    conversations: list[ConversationInfo]
    total: int
    limit: int
    offset: int


class ConversationExport(BaseModel):
    """Exported conversation data."""

    conversation: ConversationInfo
    messages: list[ConversationMessage]
    exported_at: datetime


class ConversationStatsResponse(BaseModel):
    """Statistics about stored conversations."""

    total_conversations: int
    total_messages: int
    conversations_by_agent: dict[str, int]
    oldest_conversation: datetime | None
    newest_activity: datetime | None


# ---------------------------------------------------------------------------
# Claude Code session models
# ---------------------------------------------------------------------------


class ClaudeCodeSessionCreateRequest(BaseModel):
    """Request body for creating a new Claude Code session."""

    workspace: str = Field(..., description="Name of the workspace directory")
    initial_prompt: str | None = Field(
        None, description="Optional initial prompt to send to Claude Code"
    )


class ClaudeCodeWorkspaceInfo(BaseModel):
    """Information about a Claude Code workspace."""

    name: str
    path: str
    is_git_repo: bool
    size_mb: float
    file_count: int
    current_branch: str | None = None


class ClaudeCodeSessionInfo(BaseModel):
    """Information about a Claude Code session."""

    session_id: str
    workspace: str
    state: str
    created_at: datetime
    last_activity: datetime


class ClaudeCodeCreateWorkspaceRequest(BaseModel):
    """Request body for creating a new workspace."""

    name: str = Field(..., description="Name for the new workspace")
    git_url: str | None = Field(None, description="Optional git repository URL to clone")


class ClaudeCodeDeleteWorkspaceRequest(BaseModel):
    """Request body for deleting a workspace."""

    force: bool = Field(False, description="Force deletion even with uncommitted changes")


class ClaudeCodeInputRequest(BaseModel):
    """Request body for sending input to a Claude Code session."""

    text: str = Field(..., description="Text to send to Claude Code")


class ClaudeCodePermissionResponse(BaseModel):
    """Request body for responding to a permission request."""

    approved: bool = Field(..., description="Whether to approve the permission")


class ClaudeCodeResizeRequest(BaseModel):
    """Request body for resizing the terminal."""

    rows: int = Field(..., ge=1, le=500, description="Number of rows")
    cols: int = Field(..., ge=1, le=500, description="Number of columns")
