#!/usr/bin/env python3
"""Task orchestrator entry point.

Provides both a CLI interface for ad-hoc task orchestration and a
programmatic API for integration with other agents and services.

Usage:
    # Run a single task
    uv run python -m agents.orchestrator.main "Implement rate limiting on /api/auth" \
        --repo https://github.com/user/project.git \
        --tier 2

    # Run from a task file (JSON)
    uv run python -m agents.orchestrator.main --file tasks.json

    # Dry run (plan only, don't execute)
    uv run python -m agents.orchestrator.main "Add caching layer" --dry-run
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class TaskFileValidationError(Exception):
    """Raised when a task file contains invalid data."""


class TaskFileEntry(BaseModel):
    """Pydantic model for a single task entry loaded from a JSON task file.

    Validates all fields with appropriate constraints before the orchestrator
    converts the entry into an internal Task object.
    """

    title: str = Field(..., min_length=1, max_length=200, description="Task title (required)")
    description: str | None = Field(default=None, max_length=10000, description="Task description")
    priority: int | None = Field(default=None, ge=1, le=10, description="Priority 1-10")
    autonomy_tier: int | None = Field(default=None, description="Autonomy tier: 1, 2, 3, or 4")
    tags: list[str] | None = Field(default=None, max_length=20, description="List of tags (max 20)")
    category: str | None = Field(default=None, max_length=100, description="Task category")

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str) -> str:
        """Ensure title is not only whitespace."""
        if not v.strip():
            raise ValueError("'title' must be a non-empty string")
        return v

    @field_validator("autonomy_tier")
    @classmethod
    def autonomy_tier_must_be_valid(cls, v: int | None) -> int | None:
        """Ensure autonomy_tier is one of 1, 2, 3, or 4."""
        if v is not None and v not in (1, 2, 3, 4):
            raise ValueError("'autonomy_tier' must be 1, 2, 3, or 4")
        return v

    @field_validator("tags")
    @classmethod
    def tags_must_have_valid_items(cls, v: list[str] | None) -> list[str] | None:
        """Ensure each tag is a non-empty, non-blank string within the max length."""
        if v is None:
            return v
        for i, tag in enumerate(v):
            if not tag.strip():
                raise ValueError(f"tag #{i} must be a non-empty string")
            if len(tag) > 50:
                raise ValueError(f"tag #{i} exceeds 50 characters")
        return v


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Task-driven agentic orchestrator. Decomposes tasks, "
        "dispatches Claude Code workers, and publishes PRs.",
    )

    parser.add_argument(
        "task",
        nargs="?",
        type=str,
        help="Task description (title). Use --description for full details.",
    )

    parser.add_argument(
        "--description",
        type=str,
        default="",
        help="Detailed task description",
    )

    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Git repository URL to clone for the workspace",
    )

    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Existing workspace name to use (skip workspace creation)",
    )

    parser.add_argument(
        "--tier",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="Autonomy tier: 1=auto-merge, 2=propose+execute, 3=propose+wait, 4=manual (default: 2)",
    )

    parser.add_argument(
        "--priority",
        type=int,
        default=5,
        choices=range(1, 11),
        help="Task priority 1-10 (default: 5)",
    )

    parser.add_argument(
        "--category",
        type=str,
        default="",
        help="Task category",
    )

    parser.add_argument(
        "--tags",
        type=str,
        nargs="*",
        default=[],
        help="Task tags",
    )

    parser.add_argument(
        "--external-id",
        type=str,
        default=None,
        help="External task ID (e.g., TaskManager task_386) to link in PR body",
    )

    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Load tasks from a JSON file",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only, don't execute workers",
    )

    parser.add_argument(
        "--no-decompose",
        action="store_true",
        help="Skip task decomposition — run as a single worker task",
    )

    parser.add_argument(
        "--worker-model",
        type=str,
        default="sonnet",
        choices=["sonnet", "haiku", "opus"],
        help="Model for workers (default: sonnet)",
    )

    parser.add_argument(
        "--max-tasks",
        type=int,
        default=20,
        help="Maximum tasks to process (safety limit, default: 20)",
    )

    return parser.parse_args()


def load_tasks_from_file(file_path: str) -> list[TaskFileEntry]:
    """Load and validate tasks from a JSON file.

    Expected format:
    [
        {
            "title": "Task title",  (required)
            "description": "Task description",
            "priority": 5,
            "autonomy_tier": 2,
            "tags": ["tag1", "tag2"],
            "category": "category"
        }
    ]

    Raises:
        TaskFileValidationError: If the file contains invalid data.
    """
    _MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    path = Path(file_path)
    if not path.exists():
        logger.error(f"Task file not found: {file_path}")
        sys.exit(1)

    if path.stat().st_size > _MAX_FILE_SIZE:
        raise TaskFileValidationError(
            f"Task file exceeds maximum allowed size of {_MAX_FILE_SIZE // (1024 * 1024)} MB"
        )

    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in task file: {e}")
        sys.exit(1)

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        raise TaskFileValidationError(
            f"Task file must contain a JSON array or object, got {type(data).__name__}"
        )

    entries: list[TaskFileEntry] = []
    for i, td in enumerate(data):
        if not isinstance(td, dict):
            raise TaskFileValidationError(
                f"Task #{i}: expected a JSON object, got {type(td).__name__}"
            )
        try:
            entries.append(TaskFileEntry.model_validate(td))
        except ValidationError as exc:
            # Re-raise as TaskFileValidationError with a human-readable message
            messages = "; ".join(
                f"'{'.'.join(str(loc) for loc in e['loc'])}': {e['msg']}" for e in exc.errors()
            )
            raise TaskFileValidationError(f"Task #{i}: {messages}") from exc

    return entries


async def run_orchestrator(args: argparse.Namespace) -> int:
    """Run the orchestrator with the given arguments."""
    from .models import AutonomyTier, OrchestratorConfig, Task, validate_workspace_name
    from .planner import plan_task
    from .state_machine import Orchestrator

    # Validate workspace name if provided
    if args.workspace:
        try:
            validate_workspace_name(args.workspace)
        except ValueError as e:
            logger.error(f"Invalid workspace name: {e}")
            return 1

    # Build config
    config = OrchestratorConfig(
        worker_model=args.worker_model,
        skip_decomposition=args.no_decompose,
    )

    # Create orchestrator
    orch = Orchestrator(config=config, git_repo_url=args.repo)

    # Register logging callbacks
    orch.on_task_complete(lambda t: logger.info(f"COMPLETED: {t.title}"))
    orch.on_task_failed(lambda t: logger.error(f"FAILED: {t.title} - {t.error}"))
    orch.on_human_approval_needed(
        lambda t: logger.info(f"AWAITING HUMAN: {t.title} (task_id={t.id})")
    )

    # Load tasks
    tasks: list[Task] = []

    if args.file:
        try:
            task_entries = load_tasks_from_file(args.file)
        except TaskFileValidationError as e:
            logger.error(f"Task file validation failed: {e}")
            return 1

        for entry in task_entries:
            tier_value = entry.autonomy_tier if entry.autonomy_tier is not None else args.tier
            tasks.append(
                Task(
                    title=entry.title,
                    description=entry.description or "",
                    priority=entry.priority if entry.priority is not None else args.priority,
                    autonomy_tier=AutonomyTier(tier_value),
                    tags=entry.tags or [],
                    category=entry.category if entry.category is not None else args.category,
                    workspace_name=args.workspace,
                )
            )
    elif args.task:
        tasks.append(
            Task(
                title=args.task,
                description=args.description or args.task,
                priority=args.priority,
                autonomy_tier=AutonomyTier(args.tier),
                tags=args.tags,
                category=args.category,
                workspace_name=args.workspace,
                external_id=args.external_id,
            )
        )
    else:
        logger.error("No task provided. Use positional argument or --file.")
        return 1

    # Dry run: just plan, don't execute
    if args.dry_run:
        logger.info("=== DRY RUN: Planning only ===")
        for task in tasks:
            logger.info(f"\nPlanning: {task.title}")
            subtasks = await plan_task(task, max_subtasks=config.max_subtasks_per_task)
            logger.info(f"  Subtasks ({len(subtasks)}):")
            for i, st in enumerate(subtasks, 1):
                logger.info(f"    {i}. [{st.priority}] {st.title}")
                logger.info(f"       Tags: {st.tags}")
                logger.info(f"       Tier: {st.autonomy_tier.name}")
                if st.description:
                    # Show first 100 chars of description
                    desc_preview = st.description[:100]
                    if len(st.description) > 100:
                        desc_preview += "..."
                    logger.info(f"       Desc: {desc_preview}")
        return 0

    # Add tasks and run
    for task in tasks:
        orch.add_task(task)

    logger.info(f"Starting orchestrator with {len(tasks)} task(s)...")
    processed = await orch.run(max_tasks=args.max_tasks)

    # Print summary
    summary = orch.get_status_summary()
    logger.info("\n" + "=" * 60)
    logger.info("ORCHESTRATOR SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Tasks processed: {len(processed)}")
    logger.info(f"Status counts: {summary['status_counts']}")
    logger.info(f"Worker turns used: {summary['state']['total_worker_turns']}")
    logger.info("=" * 60)

    # Print detailed results
    for task in processed:
        status_icon = {
            "completed": "+",
            "failed": "!",
            "awaiting_human": "?",
            "in_progress": "~",
        }.get(task.status.value, " ")

        logger.info(f"  [{status_icon}] {task.title} ({task.status.value})")
        if task.error:
            logger.info(f"      Error: {task.error}")

    # Exit code: 0 if all completed, 1 if any failed
    failed_count = summary["status_counts"].get("failed", 0)
    return 1 if failed_count > 0 else 0


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    return asyncio.run(run_orchestrator(args))


if __name__ == "__main__":
    sys.exit(main())
