"""Data models for the task orchestrator.

Defines task structure, orchestration state, autonomy tiers, and
the state machine phases that drive the orchestration loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any


class AutonomyTier(IntEnum):
    """Controls how much human oversight a task requires.

    Lower numbers = more autonomous. Higher numbers = more human involvement.
    """

    AUTO_MERGE = 1       # Review passes -> merge automatically
    PROPOSE_EXECUTE = 2  # Execute + review, notify human, merge unless vetoed
    PROPOSE_WAIT = 3     # Execute + review, wait for human approval before merge
    MANUAL_ONLY = 4      # Notify human, do not attempt autonomous work


class TaskStatus(str, Enum):
    """Status of a task in the orchestration pipeline."""

    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
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
    REVIEW = "review"
    HUMAN_GATE = "human_gate"
    COMPLETE = "complete"
    FAILED = "failed"


class ReviewVerdict(str, Enum):
    """Outcome of a review gate."""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_CHANGES = "needs_changes"


@dataclass
class ReviewResult:
    """Result from a review agent."""

    reviewer: str
    verdict: ReviewVerdict
    summary: str
    issues: list[ReviewIssue] = field(default_factory=list)
    raw_output: str = ""
    reviewed_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReviewIssue:
    """A specific issue found during review."""

    title: str
    description: str
    severity: str = "medium"  # low, medium, high, critical
    file_path: str | None = None
    line_number: int | None = None
    suggestion: str | None = None

    def to_task_title(self) -> str:
        """Generate a remediation task title from this issue."""
        prefix = f"[{self.severity.upper()}]" if self.severity in ("high", "critical") else ""
        return f"{prefix} Fix: {self.title}".strip()

    def severity_to_priority(self) -> int:
        """Map severity to task priority (1-10 scale, 10=highest)."""
        return {"critical": 10, "high": 8, "medium": 5, "low": 3}.get(self.severity, 5)


@dataclass
class Task:
    """A task to be orchestrated.

    Tasks form a tree via parent_id. The orchestrator decomposes top-level
    tasks into subtasks, dispatches workers, and tracks completion.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
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
    review_results: list[ReviewResult] = field(default_factory=list)
    error: str | None = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # External reference (e.g., TaskManager MCP task ID)
    external_id: str | None = None

    def is_leaf(self) -> bool:
        """True if this task has no subtasks."""
        return len(self.subtask_ids) == 0

    def all_reviews_passed(self) -> bool:
        """True if all review results have a PASSED verdict."""
        return bool(self.review_results) and all(
            r.verdict == ReviewVerdict.PASSED for r in self.review_results
        )


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""

    # Recursion limits
    max_subtask_depth: int = 3
    max_subtasks_per_task: int = 10
    max_remediation_tasks: int = 5

    # Worker configuration
    worker_model: str = "sonnet"
    worker_timeout: int = 600  # 10 minutes
    worker_max_turns: int = 30

    # Review configuration
    review_model: str = "sonnet"
    enable_code_review: bool = True
    enable_security_review: bool = True

    # Git configuration
    branch_prefix: str = "orchestrator"
    auto_create_workspace: bool = True

    # Notification
    notify_on_complete: bool = True
    notify_on_failure: bool = True

    # Polling
    poll_interval_seconds: int = 30


@dataclass
class OrchestratorState:
    """Snapshot of orchestrator state for observability."""

    phase: Phase = Phase.IDLE
    current_task_id: str | None = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_worker_turns: int = 0
    total_review_passes: int = 0
    total_review_failures: int = 0
    started_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging/observability."""
        return {
            "phase": self.phase.value,
            "current_task_id": self.current_task_id,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "total_worker_turns": self.total_worker_turns,
            "total_review_passes": self.total_review_passes,
            "total_review_failures": self.total_review_failures,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }
