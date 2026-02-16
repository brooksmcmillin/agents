"""Data models for the task orchestrator.

Defines task structure, orchestration state, autonomy tiers, and
the state machine phases that drive the orchestration loop.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, IntEnum
from typing import Any


def _utcnow() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(UTC)


# Strict pattern for workspace names: alphanumeric, hyphens, underscores only.
# Rejects path traversal sequences and special characters.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")

# Valid git ref component: starts with alphanumeric, allows hyphens, underscores,
# slashes.  Used for branch names, branch prefixes, and base branch values.
_SAFE_GIT_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_/-]{0,200}$")


# Known model short names and full IDs accepted by the orchestrator.
# This is not exhaustive but catches typos early with a clear error.
KNOWN_MODELS = frozenset(
    {
        "sonnet",
        "haiku",
        "opus",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
        "claude-opus-4-6",
    }
)


# Short name -> full Anthropic model ID mapping
MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}


def validate_model_name(model: str) -> str:
    """Validate a model name against known values.

    Args:
        model: Model name or ID.

    Returns:
        The model name unchanged.

    Raises:
        ValueError: If the model name is not recognized.
    """
    if model not in KNOWN_MODELS:
        raise ValueError(f"Unknown model: {model!r}. Known models: {sorted(KNOWN_MODELS)}")
    return model


def resolve_model(model: str) -> str:
    """Resolve a short model name to a full Anthropic API model ID.

    Validates the model name, then maps short names (haiku, sonnet, opus)
    to their full IDs. Full IDs pass through unchanged.
    """
    validate_model_name(model)
    return MODEL_ALIASES.get(model, model)


def validate_git_ref(ref: str, label: str = "git ref") -> str:
    """Validate a git reference name (branch, prefix, etc.).

    Args:
        ref: The git reference to validate.
        label: Human-readable label for error messages.

    Returns:
        The validated reference unchanged.

    Raises:
        ValueError: If the reference contains unsafe characters.
    """
    if not _SAFE_GIT_REF_RE.match(ref):
        raise ValueError(
            f"Invalid {label}: {ref!r}. Must start with alphanumeric "
            f"and contain only alphanumeric, hyphens, underscores, or slashes."
        )
    return ref


class AutonomyTier(IntEnum):
    """Controls how much human oversight a task requires.

    Lower numbers = more autonomous. Higher numbers = more human involvement.
    """

    AUTO_MERGE = 1  # Review passes -> merge automatically
    PROPOSE_EXECUTE = 2  # Execute + review, notify human, merge unless vetoed
    PROPOSE_WAIT = 3  # Execute + review, wait for human approval before merge
    MANUAL_ONLY = 4  # Notify human, do not attempt autonomous work


class TaskStatus(str, Enum):
    """Status of a task in the orchestration pipeline."""

    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class Phase(str, Enum):
    """Orchestrator state machine phases."""

    IDLE = "idle"
    INGEST = "ingest"
    PLAN = "plan"
    EXECUTE = "execute"
    PUBLISH = "publish"
    HUMAN_GATE = "human_gate"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class Task:
    """A task to be orchestrated.

    Tasks form a tree via parent_id. The orchestrator decomposes top-level
    tasks into subtasks, dispatches workers, and tracks completion.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    autonomy_tier: AutonomyTier = AutonomyTier.PROPOSE_EXECUTE
    priority: int = 5  # 1-10, 10 = highest
    tags: list[str] = field(default_factory=list)
    category: str = ""

    # Hierarchy
    parent_id: str | None = None
    subtask_ids: list[str] = field(default_factory=list)
    depth: int = 0  # Nesting depth for recursion limits

    # Execution context
    workspace_name: str | None = None
    branch_name: str | None = None
    assigned_agent: str | None = None

    # Results
    worker_output: str | None = None
    pr_url: str | None = None
    error: str | None = None

    # Estimation
    estimated_hours: float | None = None

    # Metadata
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # External reference (e.g., TaskManager MCP task ID)
    external_id: str | None = None

    def is_leaf(self) -> bool:
        """True if this task has no subtasks."""
        return len(self.subtask_ids) == 0


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""

    # Decomposition
    decompose_threshold_hours: float = 4.0  # Skip decomposition for tasks estimated ≤ this
    max_subtask_depth: int = 3
    max_subtasks_per_task: int = 6
    max_total_tasks: int = 50  # Absolute cap on tasks in the registry

    # Worker configuration
    worker_model: str = "sonnet"
    worker_timeout: int = 600  # 10 minutes
    worker_max_turns: int = 30

    # Planner configuration
    planner_model: str = "sonnet"

    # Git configuration
    branch_prefix: str = "orchestrator"
    base_branch: str = "main"  # Default base branch for diffs
    auto_create_workspace: bool = True

    # Notification
    notify_on_complete: bool = True
    notify_on_failure: bool = True

    # Polling
    poll_interval_seconds: int = 30

    def __post_init__(self) -> None:
        """Validate configuration values on construction."""
        validate_git_ref(self.base_branch, "base_branch")
        validate_git_ref(self.branch_prefix, "branch_prefix")


def validate_workspace_name(name: str) -> str:
    """Validate and return a safe workspace name.

    Args:
        name: Proposed workspace name.

    Returns:
        The validated name.

    Raises:
        ValueError: If the name contains unsafe characters or patterns.
    """
    if not name:
        raise ValueError("Workspace name cannot be empty")
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Workspace name contains path traversal sequence: {name!r}")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Workspace name must be alphanumeric with hyphens/underscores "
            f"(1-128 chars, start with alphanumeric): {name!r}"
        )
    return name


@dataclass
class OrchestratorState:
    """Snapshot of orchestrator state for observability."""

    phase: Phase = Phase.IDLE
    current_task_id: str | None = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_worker_turns: int = 0
    started_at: datetime | None = None
    last_worker_error: str | None = None
    consecutive_identical_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging/observability."""
        return {
            "phase": self.phase.value,
            "current_task_id": self.current_task_id,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "total_worker_turns": self.total_worker_turns,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }
