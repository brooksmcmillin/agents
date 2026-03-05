"""Data models for the PR Shepherd service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from agent_framework.core.polling_agent import PollingAgentConfig


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PRStatus(str, Enum):
    """Lifecycle status of a tracked PR."""

    PENDING_CHECKS = "pending_checks"
    CHECKS_PASSING = "checks_passing"
    CHECKS_FAILING = "checks_failing"
    FIXING = "fixing"
    MERGED = "merged"
    ABANDONED = "abandoned"


@dataclass
class PRShepherdConfig(PollingAgentConfig):
    """Configuration for the PR Shepherd service.

    Extends PollingAgentConfig with PR-specific settings.
    """

    repos: list[str] = field(default_factory=list)
    # Inherited: poll_interval, max_retries (replaces max_fix_attempts), dry_run
    merge_method: str = "squash"  # squash, merge, rebase
    label_filter: str | None = None  # only process PRs with this label
    worker_model: str = "sonnet"
    worker_timeout: int = 600  # seconds

    @property
    def max_fix_attempts(self) -> int:
        """Alias for max_retries for backward compatibility."""
        return self.max_retries

    @max_fix_attempts.setter
    def max_fix_attempts(self, value: int) -> None:
        self.max_retries = value


@dataclass
class TrackedPR:
    """State for a PR being shepherded through CI."""

    repo: str
    number: int
    title: str
    head_branch: str
    fix_attempts: int = 0
    status: PRStatus = PRStatus.PENDING_CHECKS
    last_checked: datetime = field(default_factory=_utcnow)


@dataclass
class PRDiagnosis:
    """Result of diagnosing a PR's CI status."""

    overall_status: str  # "pass", "fail", or "pending"
    failing_checks: list[str] = field(default_factory=list)


@dataclass
class PRActionResult:
    """Result of attempting to fix or merge a PR."""

    success: bool
    action: str  # "merged", "fix_pushed", "fix_failed", "push_failed", "no_logs", "abandoned"
    message: str = ""
