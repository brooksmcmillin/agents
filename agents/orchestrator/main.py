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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Task-driven agentic orchestrator. Decomposes tasks, "
        "dispatches Claude Code workers, and runs review gates.",
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
        "--no-review",
        action="store_true",
        help="Skip review gates",
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
    """Load tasks from a JSON file.

    Expected format:
    [
        {
            "title": "Task title",
            "description": "Task description",
            "priority": 5,
            "autonomy_tier": 2,
            "tags": ["tag1", "tag2"],
            "category": "category"
        }
    ]
    """
    path = Path(file_path)
    if not path.exists():
        logger.error(f"Task file not found: {file_path}")
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    return data


async def run_orchestrator(args: argparse.Namespace) -> int:
    """Run the orchestrator with the given arguments."""
    from .models import AutonomyTier, OrchestratorConfig, Task
    from .planner import plan_task
    from .state_machine import Orchestrator

    # Build config
    config = OrchestratorConfig(
        worker_model=args.worker_model,
        enable_code_review=not args.no_review,
        enable_security_review=not args.no_review,
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
        task_dicts = load_tasks_from_file(args.file)
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
    logger.info(f"Reviews passed: {summary['state']['total_review_passes']}")
    logger.info(f"Reviews failed: {summary['state']['total_review_failures']}")
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
        for review in task.review_results:
            logger.info(
                f"      Review ({review.reviewer}): {review.verdict.value} "
                f"- {review.summary[:80]}"
            )

    # Exit code: 0 if all completed, 1 if any failed
    failed_count = summary["status_counts"].get("failed", 0)
    return 1 if failed_count > 0 else 0


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    return asyncio.run(run_orchestrator(args))


if __name__ == "__main__":
    sys.exit(main())
