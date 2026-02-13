"""Pydantic models for the Agent REST API.

Re-exports all models from domain-focused submodules for backward compatibility.
"""

from .base import (
    AgentInfo,
    AgentListResponse,
    HealthResponse,
    MessageRequest,
    MessageResponse,
    TokenUsage,
)
from .claude_code import (
    ClaudeCodeCreateWorkspaceRequest,
    ClaudeCodeDeleteWorkspaceRequest,
    ClaudeCodeInputRequest,
    ClaudeCodePermissionResponse,
    ClaudeCodeResizeRequest,
    ClaudeCodeSessionCreateRequest,
    ClaudeCodeSessionInfo,
    ClaudeCodeWorkspaceInfo,
)
from .conversations import (
    ConversationCreateRequest,
    ConversationDetail,
    ConversationExport,
    ConversationInfo,
    ConversationListResponse,
    ConversationMessage,
    ConversationStatsResponse,
    ConversationUpdateRequest,
)
from .sessions import (
    SessionCreateRequest,
    SessionInfo,
)

__all__ = [
    # Base
    "AgentInfo",
    "AgentListResponse",
    "HealthResponse",
    "MessageRequest",
    "MessageResponse",
    "TokenUsage",
    # Sessions
    "SessionCreateRequest",
    "SessionInfo",
    # Conversations
    "ConversationCreateRequest",
    "ConversationDetail",
    "ConversationExport",
    "ConversationInfo",
    "ConversationListResponse",
    "ConversationMessage",
    "ConversationStatsResponse",
    "ConversationUpdateRequest",
    # Claude Code
    "ClaudeCodeCreateWorkspaceRequest",
    "ClaudeCodeDeleteWorkspaceRequest",
    "ClaudeCodeInputRequest",
    "ClaudeCodePermissionResponse",
    "ClaudeCodeResizeRequest",
    "ClaudeCodeSessionCreateRequest",
    "ClaudeCodeSessionInfo",
    "ClaudeCodeWorkspaceInfo",
]
