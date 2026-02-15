"""Data models for the task queue runner.

Defines task classification, triage results, configuration, and reporting
structures used throughout the task queue pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Short name -> full Anthropic model ID mapping
MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}


def resolve_model(model: str) -> str:
    """Resolve a short model name to a full Anthropic model ID.

    Passes through full model IDs unchanged.
    """
    return MODEL_ALIASES.get(model, model)


class TriageVerdict(str, Enum):
    """Classification verdict from LLM triage."""

    FULLY_EXECUTABLE = "fully_executable"
    PRE_RESEARCH_ONLY = "pre_research_only"
    NOT_ACTIONABLE = "not_actionable"
    SKIP_DEPENDENCIES = "skip_dependencies"
    SKIP_ALREADY_PROCESSING = "skip_already_processing"


@dataclass
class TriageResult:
    """Result of triaging a single task."""

    verdict: TriageVerdict
    confidence: float  # 0.0 - 1.0
    reasoning: str = ""
    estimated_hours: float | None = None
    suggested_action_type: str | None = None  # research, code, email, etc.
    suggested_autonomy_tier: int | None = None  # 1-4
    suggested_dependencies: list[str] = field(default_factory=list)
    pre_research_queries: list[str] = field(default_factory=list)
    blocking_reason: str | None = None


@dataclass
class TaskQueueConfig:
    """Configuration for the task queue runner."""

    # MCP connection
    mcp_url: str | None = None

    # Execution control
    dry_run: bool = False
    max_tasks: int = 20

    # Model selection
    triage_model: str = "haiku"
    research_model: str = "haiku"
    worker_model: str = "sonnet"
    lightweight_model: str = "sonnet"

    # Task filtering
    task_ids: list[str] = field(default_factory=list)  # Specific task IDs to process
    include_overdue: bool = True
    priority_bump_overdue: bool = True

    # Orchestrator settings
    enable_code_review: bool = True
    enable_security_review: bool = True
    git_repo_url: str | None = None

    # Concurrency
    concurrency: int = 5  # Max parallel triage calls

    # Notifications
    slack_webhook_url: str | None = None
    send_email_report: bool = False


@dataclass
class TaskContext:
    """Accumulated context across task processing for cross-task awareness."""

    research_notes: dict[str, str] = field(default_factory=dict)  # task_id -> notes
    completed_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)

    def get_related_context(self, title: str, description: str) -> str:
        """Find research notes from previously processed tasks with keyword overlap.

        Uses simple keyword matching: extracts significant words from the
        target task and returns notes from tasks sharing 2+ keywords.

        Args:
            title: Task title to match against.
            description: Task description to match against.

        Returns:
            Concatenated relevant notes, or empty string if none match.
        """
        if not self.research_notes:
            return ""

        target_words = _extract_keywords(f"{title} {description}")
        if not target_words:
            return ""

        related: list[str] = []
        for task_id, notes in self.research_notes.items():
            note_words = _extract_keywords(notes)
            overlap = target_words & note_words
            if len(overlap) >= 2:
                related.append(f"[Context from task {task_id}]\n{notes}")

        return "\n\n".join(related)


def _extract_keywords(text: str) -> set[str]:
    """Extract significant keywords from text for matching.

    Filters out common stop words and short tokens.
    """
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "and",
        "but",
        "or",
        "not",
        "no",
        "nor",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "then",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "my",
        "your",
        "our",
        "their",
        "his",
        "her",
        "i",
        "you",
        "we",
        "they",
        "me",
        "him",
        "us",
        "them",
        "task",
        "need",
        "make",
        "get",
        "set",
        "use",
        "new",
        "add",
        "update",
    }
    words = set()
    for word in text.lower().split():
        # Strip punctuation
        cleaned = "".join(c for c in word if c.isalnum())
        if len(cleaned) > 2 and cleaned not in stop_words:
            words.add(cleaned)
    return words


@dataclass
class ProcessedTask:
    """Record of a single task processed during a run."""

    external_id: str
    title: str
    triage_verdict: TriageVerdict
    confidence: float
    outcome: str = (
        ""  # "completed", "partial", "failed", "researched", "blocked", "skipped", "needs_human"
    )
    notes: str = ""
    estimated_hours: float | None = None
    error: str | None = None
    orchestrator_task_id: str | None = None
    branch_name: str | None = None


@dataclass
class RunReport:
    """Summary report for a complete task queue run."""

    started_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None
    tasks_processed: list[ProcessedTask] = field(default_factory=list)
    total_fetched: int = 0
    dry_run: bool = False

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "failed")

    @property
    def researched_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "researched")

    @property
    def blocked_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "blocked")

    @property
    def needs_human_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "needs_human")

    @property
    def partial_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "partial")

    @property
    def skipped_count(self) -> int:
        return sum(1 for t in self.tasks_processed if t.outcome == "skipped")

    def format_summary(self) -> str:
        """Format a human-readable summary of the run."""
        duration = ""
        if self.completed_at:
            delta = self.completed_at - self.started_at
            minutes = int(delta.total_seconds() // 60)
            seconds = int(delta.total_seconds() % 60)
            duration = f" in {minutes}m {seconds}s"

        lines = [
            f"Task Queue Run {'(DRY RUN) ' if self.dry_run else ''}Summary{duration}",
            f"  Fetched: {self.total_fetched}",
            f"  Processed: {len(self.tasks_processed)}",
            f"  Completed: {self.completed_count}",
            f"  Partial: {self.partial_count}",
            f"  Needs human: {self.needs_human_count}",
            f"  Failed: {self.failed_count}",
            f"  Researched: {self.researched_count}",
            f"  Blocked: {self.blocked_count}",
            f"  Skipped: {self.skipped_count}",
        ]

        if self.tasks_processed:
            lines.append("")
            lines.append("Details:")
            for t in self.tasks_processed:
                verdict = t.triage_verdict.value
                conf = f"{t.confidence:.0%}"
                status = t.outcome or "pending"
                line = f"  [{status:>10}] {t.title[:60]:<60} ({verdict}, {conf})"
                if t.error:
                    line += f"\n             Error: {t.error[:100]}"
                lines.append(line)

        return "\n".join(lines)

    def format_slack_message(self) -> str:
        """Format a Slack-compatible summary message."""
        prefix = ":test_tube: *DRY RUN*\n" if self.dry_run else ""
        parts = [
            f"{prefix}:robot_face: *Task Queue Run Complete*",
            f"Fetched {self.total_fetched} tasks, processed {len(self.tasks_processed)}",
            "",
        ]

        if self.completed_count:
            parts.append(f":white_check_mark: Completed: {self.completed_count}")
        if self.partial_count:
            parts.append(f":hourglass: Partial: {self.partial_count}")
        if self.needs_human_count:
            parts.append(f":hand: Needs human: {self.needs_human_count}")
        if self.researched_count:
            parts.append(f":mag: Researched: {self.researched_count}")
        if self.blocked_count:
            parts.append(f":no_entry: Blocked: {self.blocked_count}")
        if self.failed_count:
            parts.append(f":x: Failed: {self.failed_count}")
        if self.skipped_count:
            parts.append(f":fast_forward: Skipped: {self.skipped_count}")

        # Show failed tasks with errors
        failed = [t for t in self.tasks_processed if t.outcome == "failed"]
        if failed:
            parts.append("")
            parts.append("*Failures:*")
            for t in failed[:5]:
                error_msg = t.error[:80] if t.error else "Unknown error"
                parts.append(f"• {t.title[:50]}: {error_msg}")

        return "\n".join(parts)
