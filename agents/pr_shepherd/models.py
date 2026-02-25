"""Data models for the PR Shepherd service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


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
class PRShepherdConfig:
    """Configuration for the PR Shepherd service."""

    repos: list[str] = field(default_factory=list)
    poll_interval: int = 60  # seconds between poll cycles
    max_fix_attempts: int = 3
    merge_method: str = "squash"  # squash, merge, rebase
    label_filter: str | None = None  # only process PRs with this label
    worker_model: str = "sonnet"
    worker_timeout: int = 600  # seconds
    dry_run: bool = False


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
