"""Claude Code session and workspace models."""

from datetime import datetime

from pydantic import BaseModel, Field


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
    session_token: str | None = Field(
        default=None,
        description=(
            "Per-session secret token required to open a WebSocket connection. "
            "Only present in the response to POST /claude-code/sessions (session creation). "
            "Store it securely; it is never returned again."
        ),
    )


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
