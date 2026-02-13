"""Conversation persistence models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
