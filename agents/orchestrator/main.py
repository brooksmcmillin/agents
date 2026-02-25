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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Maximum allowed length for string fields from JSON input
_MAX_TITLE_LEN = 200
_MAX_DESCRIPTION_LEN = 10000
_MAX_CATEGORY_LEN = 100
_MAX_TAG_LEN = 50
_MAX_TAGS_COUNT = 20


class TaskFileValidationError(Exception):
    """Raised when a task file contains invalid data."""


def _validate_task_dict(td: dict, index: int) -> None:
    """Validate a single task dictionary from JSON input.

    Args:
        td: Task dictionary to validate.
        index: Position in the task list (for error messages).

    Raises:
        TaskFileValidationError: If validation fails.
    """
    if not isinstance(td, dict):
        raise TaskFileValidationError(
            f"Task #{index}: expected a JSON object, got {type(td).__name__}"
        )

    # title is required
    if "title" not in td:
        raise TaskFileValidationError(f"Task #{index}: missing required field 'title'")
    if not isinstance(td["title"], str) or not td["title"].strip():
        raise TaskFileValidationError(f"Task #{index}: 'title' must be a non-empty string")
    if len(td["title"]) > _MAX_TITLE_LEN:
        raise TaskFileValidationError(f"Task #{index}: 'title' exceeds {_MAX_TITLE_LEN} characters")

    # description (optional)
    if "description" in td:
        if not isinstance(td["description"], str):
            raise TaskFileValidationError(f"Task #{index}: 'description' must be a string")
        if len(td["description"]) > _MAX_DESCRIPTION_LEN:
            raise TaskFileValidationError(
                f"Task #{index}: 'description' exceeds {_MAX_DESCRIPTION_LEN} characters"
            )

    # priority (optional)
    if "priority" in td:
        if not isinstance(td["priority"], int) or not (1 <= td["priority"] <= 10):
            raise TaskFileValidationError(f"Task #{index}: 'priority' must be an integer 1-10")

    # autonomy_tier (optional)
    if "autonomy_tier" in td:
        if not isinstance(td["autonomy_tier"], int) or td["autonomy_tier"] not in (1, 2, 3, 4):
            raise TaskFileValidationError(f"Task #{index}: 'autonomy_tier' must be 1, 2, 3, or 4")

    # tags (optional)
    if "tags" in td:
        if not isinstance(td["tags"], list):
            raise TaskFileValidationError(f"Task #{index}: 'tags' must be a list")
        if len(td["tags"]) > _MAX_TAGS_COUNT:
            raise TaskFileValidationError(f"Task #{index}: too many tags (max {_MAX_TAGS_COUNT})")
        for i, tag in enumerate(td["tags"]):
            if not isinstance(tag, str):
                raise TaskFileValidationError(f"Task #{index}: tag #{i} must be a string")
            if len(tag) > _MAX_TAG_LEN:
                raise TaskFileValidationError(
                    f"Task #{index}: tag #{i} exceeds {_MAX_TAG_LEN} characters"
                )

    # category (optional)
    if "category" in td:
        if not isinstance(td["category"], str):
            raise TaskFileValidationError(f"Task #{index}: 'category' must be a string")
        if len(td["category"]) > _MAX_CATEGORY_LEN:
            raise TaskFileValidationError(
                f"Task #{index}: 'category' exceeds {_MAX_CATEGORY_LEN} characters"
            )


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


def load_tasks_from_file(file_path: str) -> list[dict]:
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
    path = Path(file_path)
    if not path.exists():
        logger.error(f"Task file not found: {file_path}")
        sys.exit(1)

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

    for i, td in enumerate(data):
        _validate_task_dict(td, i)

    return data


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
            task_dicts = load_tasks_from_file(args.file)
        except TaskFileValidationError as e:
            logger.error(f"Task file validation failed: {e}")
            return 1

        for td in task_dicts:
            tier_value = td.get("autonomy_tier", args.tier)
            tasks.append(
                Task(
                    title=td["title"],
                    description=td.get("description", ""),
                    priority=td.get("priority", args.priority),
                    autonomy_tier=AutonomyTier(tier_value),
                    tags=td.get("tags", []),
                    category=td.get("category", args.category),
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
