"""Outcome store — tracks task/PR outcomes for feedback loops.

Thin wrapper over the existing memory system using ``agent_name="feedback"``.
Stores structured outcome data (CI results, failure patterns, fix approaches)
and provides aggregated feedback for prompt injection into workers and planners.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from agent_framework.tools.memory import get_memories, save_memory, search_memories

logger = logging.getLogger(__name__)

AGENT_NAME = "feedback"


@dataclass
class TaskOutcome:
    """Structured outcome data for a task/PR."""

    task_id: str
    task_title: str
    repo: str
    pr_number: int | None = None
    pr_url: str | None = None
    pr_status: str = "open"  # merged | closed | ci_failing | open
    ci_failures: list[str] = field(default_factory=list)
    fix_attempts: int = 0
    worker_success: bool = True
    worker_error: str | None = None
    failure_patterns: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved_at: str | None = None


def _outcome_key(outcome: TaskOutcome) -> str:
    """Generate memory key for an outcome."""
    if outcome.pr_number is not None:
        return f"outcome/{outcome.repo}#{outcome.pr_number}"
    return f"outcome/{outcome.task_id}"


def _pattern_key(repo: str, pattern: str) -> str:
    """Generate memory key for a failure pattern."""
    h = hashlib.sha256(pattern.encode()).hexdigest()[:12]
    return f"pattern/{repo}/{h}"


def _fix_key(repo: str, pattern: str) -> str:
    """Generate memory key for a fix pattern."""
    h = hashlib.sha256(pattern.encode()).hexdigest()[:12]
    return f"fix/{repo}/{h}"


async def save_outcome(outcome: TaskOutcome) -> None:
    """Save a task outcome to memory.

    If the outcome already exists with an unchanged status, skips the write.
    If a failure pattern already exists, bumps its importance.
    """
    key = _outcome_key(outcome)

    # Check for existing outcome to avoid unnecessary writes
    existing = await search_memories(query=key, limit=1, agent_name=AGENT_NAME)
    existing_memories = existing.get("memories", [])
    if existing_memories:
        for mem in existing_memories:
            if mem.get("key") == key:
                try:
                    old = json.loads(mem["value"])
                    if old.get("pr_status") == outcome.pr_status:
                        logger.debug(f"Outcome {key} unchanged, skipping")
                        return
                except (json.JSONDecodeError, KeyError):
                    pass

    # Derive tags from outcome
    tags = ["outcome"]
    if outcome.pr_status == "merged":
        tags.append("merged")
    elif outcome.pr_status == "closed":
        tags.append("closed")
    elif outcome.pr_status == "ci_failing":
        tags.append("ci_failing")

    importance = 5
    if outcome.pr_status == "ci_failing":
        importance = 7
    elif not outcome.worker_success:
        importance = 7

    await save_memory(
        key=key,
        value=json.dumps(asdict(outcome)),
        category="task_outcome",
        tags=tags,
        importance=importance,
        agent_name=AGENT_NAME,
    )

    # Save/escalate individual failure patterns
    for pattern in outcome.failure_patterns:
        await _save_failure_pattern(outcome.repo, pattern)

    logger.info(f"Saved outcome: {key} (status={outcome.pr_status})")


async def _save_failure_pattern(repo: str, pattern: str) -> None:
    """Save or escalate a failure pattern's importance."""
    key = _pattern_key(repo, pattern)

    existing = await search_memories(query=key, limit=1, agent_name=AGENT_NAME)
    existing_memories = existing.get("memories", [])

    importance = 5
    count = 1
    for mem in existing_memories:
        if mem.get("key") == key:
            try:
                old = json.loads(mem["value"])
                count = old.get("count", 1) + 1
                # Escalate: 5 -> 7 -> 9, cap at 9
                importance = min(old.get("importance", 5) + 2, 9)
            except (json.JSONDecodeError, KeyError):
                pass
            break

    tags = _tags_for_pattern(pattern)

    await save_memory(
        key=key,
        value=json.dumps(
            {"pattern": pattern, "repo": repo, "count": count, "importance": importance}
        ),
        category="failure_pattern",
        tags=["pattern", repo] + tags,
        importance=importance,
        agent_name=AGENT_NAME,
    )


async def save_fix_pattern(repo: str, pattern: str, fix_description: str) -> None:
    """Record a successful fix approach for a failure pattern."""
    key = _fix_key(repo, pattern)
    await save_memory(
        key=key,
        value=json.dumps(
            {
                "pattern": pattern,
                "repo": repo,
                "fix": fix_description,
                "saved_at": datetime.now(UTC).isoformat(),
            }
        ),
        category="fix_pattern",
        tags=["fix", repo] + _tags_for_pattern(pattern),
        importance=7,
        agent_name=AGENT_NAME,
    )


def _tags_for_pattern(pattern: str) -> list[str]:
    """Derive tags from a failure pattern string."""
    tags: list[str] = []
    lower = pattern.lower()
    if "ruff" in lower or "flake8" in lower:
        tags.extend(["ci", "lint"])
    elif "pytest" in lower or "test_" in lower:
        tags.extend(["ci", "test"])
    elif "mypy" in lower:
        tags.extend(["ci", "type-check"])
    elif "import" in lower or "module" in lower:
        tags.extend(["ci", "import"])
    else:
        tags.append("ci")
    return tags


async def get_outcomes(
    repo: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[TaskOutcome]:
    """Query outcomes, optionally filtered by repo and status."""
    tags = ["outcome"]
    if status:
        tags.append(status)

    result = await get_memories(
        category="task_outcome",
        tags=tags,
        limit=limit,
        agent_name=AGENT_NAME,
    )

    outcomes: list[TaskOutcome] = []
    for mem in result.get("memories", []):
        try:
            data = json.loads(mem["value"])
            if repo and data.get("repo") != repo:
                continue
            outcomes.append(TaskOutcome(**data))
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"Skipping malformed outcome: {e}")

    return outcomes


async def get_failure_patterns(repo: str | None = None, limit: int = 20) -> list[dict]:
    """Return aggregated failure pattern data, sorted by importance."""
    tags = ["pattern"]
    if repo:
        tags.append(repo)

    result = await get_memories(
        category="failure_pattern",
        tags=tags,
        limit=limit,
        agent_name=AGENT_NAME,
    )

    patterns: list[dict] = []
    for mem in result.get("memories", []):
        try:
            data = json.loads(mem["value"])
            patterns.append(data)
        except (json.JSONDecodeError, KeyError):
            continue

    return patterns


async def get_relevant_feedback(
    repo: str | None = None,
    task_category: str | None = None,
    limit: int = 5,
) -> str:
    """Format accumulated knowledge into a context string for prompt injection.

    Returns a human-readable summary of failure patterns, fix approaches,
    and recent outcomes for the given repo/category. Returns empty string
    if no relevant feedback exists.
    """
    sections: list[str] = []

    # Get failure patterns
    patterns = await get_failure_patterns(repo=repo, limit=limit)
    if patterns:
        lines: list[str] = []
        for p in patterns:
            count = p.get("count", 1)
            pattern = p.get("pattern", "unknown")
            if count > 1:
                lines.append(f"- {pattern} (seen {count} times)")
            else:
                lines.append(f"- {pattern}")
        sections.append("**Common CI failures:**\n" + "\n".join(lines))

    # Get fix patterns
    fix_tags = ["fix"]
    if repo:
        fix_tags.append(repo)
    fix_result = await get_memories(
        category="fix_pattern",
        tags=fix_tags,
        limit=limit,
        agent_name=AGENT_NAME,
    )
    fix_lines: list[str] = []
    for mem in fix_result.get("memories", []):
        try:
            data = json.loads(mem["value"])
            fix_lines.append(f"- {data['pattern']}: {data['fix']}")
        except (json.JSONDecodeError, KeyError):
            continue
    if fix_lines:
        sections.append("**Known fixes:**\n" + "\n".join(fix_lines))

    # Get recent outcome stats
    recent = await get_outcomes(repo=repo, limit=20)
    if recent:
        status_counts = Counter(o.pr_status for o in recent)
        stats = ", ".join(f"{k}: {v}" for k, v in status_counts.most_common())
        sections.append(f"**Recent PR outcomes:** {stats}")

    # Search for category-specific insights
    if task_category:
        cat_result = await search_memories(query=task_category, limit=3, agent_name=AGENT_NAME)
        for mem in cat_result.get("memories", []):
            if mem.get("category") == "fix_pattern":
                try:
                    data = json.loads(mem["value"])
                    sections.append(f"- Category-related fix: {data['fix']}")
                except (json.JSONDecodeError, KeyError):
                    continue

    if not sections:
        return ""

    header = "## Lessons from previous tasks"
    if repo:
        header += f" in {repo}"
    return header + "\n" + "\n\n".join(sections)
