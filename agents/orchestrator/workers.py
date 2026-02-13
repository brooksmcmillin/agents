"""Worker dispatch for the orchestrator.

Workers are Claude Code instances running in isolated workspaces.
Each worker gets a focused task, works on a dedicated git branch,
and returns results for review.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from agent_framework.tools.claude_code import (
    create_claude_code_workspace,
    get_claude_code_workspace_status,
    run_claude_code,
)

from .models import OrchestratorConfig, Task
from .prompts import WORKER_INSTRUCTIONS_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass
class WorkerResult:
    """Result from a Claude Code worker execution."""

    success: bool
    output: str
    turns_used: int
    exit_code: int
    error: str | None = None


def _branch_name_for_task(task: Task, config: OrchestratorConfig) -> str:
    """Generate a git branch name for a task.

    Args:
        task: The task being worked on.
        config: Orchestrator configuration.

    Returns:
        A valid git branch name.
    """
    # Sanitize title for branch name
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", task.title.lower()).strip("-")[:50]
    return f"{config.branch_prefix}/{task.id}-{slug}"


async def ensure_workspace(
    task: Task,
    config: OrchestratorConfig,
    git_repo_url: str | None = None,
) -> str:
    """Ensure a workspace exists for the task.

    If the task already has a workspace_name, verifies it exists.
    Otherwise creates a new one, optionally cloning a git repo.

    Args:
        task: The task needing a workspace.
        config: Orchestrator configuration.
        git_repo_url: Optional git repo URL to clone.

    Returns:
        The workspace folder name.
    """
    if task.workspace_name:
        # Verify it exists
        try:
            status = await get_claude_code_workspace_status(task.workspace_name)
            if not status.get("error"):
                logger.info(f"Workspace {task.workspace_name} already exists")
                return task.workspace_name
        except Exception:
            logger.warning(f"Workspace {task.workspace_name} not found, creating new one")

    # Generate workspace name from task
    workspace_name = f"orch-{task.id}"

    result = await create_claude_code_workspace(
        folder_name=workspace_name,
        git_repo_url=git_repo_url,
    )

    if not result.get("success"):
        error = result.get("error", "Unknown error")
        # If workspace already exists, that's fine
        if "already exists" in str(error):
            logger.info(f"Workspace {workspace_name} already exists, reusing")
            return workspace_name
        raise RuntimeError(f"Failed to create workspace: {error}")

    logger.info(f"Created workspace: {workspace_name}")
    return workspace_name


async def dispatch_worker(
    task: Task,
    config: OrchestratorConfig,
    context: str = "",
) -> WorkerResult:
    """Dispatch a Claude Code worker to execute a task.

    Creates/uses a workspace, sets up a git branch, runs Claude Code
    with focused instructions, and returns the result.

    Args:
        task: The task to execute.
        config: Orchestrator configuration.
        context: Additional context to provide to the worker.

    Returns:
        WorkerResult with the execution outcome.
    """
    if not task.workspace_name:
        raise ValueError(f"Task {task.id} has no workspace_name assigned")

    branch_name = task.branch_name or _branch_name_for_task(task, config)
    task.branch_name = branch_name

    # Build worker instructions
    branch_info = f"Branch: {branch_name}\nCreate this branch and work on it."
    workspace_status = await get_claude_code_workspace_status(task.workspace_name)
    workspace_path = workspace_status.get("workspace_path", task.workspace_name)

    instructions = WORKER_INSTRUCTIONS_TEMPLATE.format(
        title=task.title,
        description=task.description,
        workspace_path=workspace_path,
        branch_info=branch_info,
        context=context or "No additional context.",
    )

    # Prepend git branch setup
    git_setup = (
        f"First, create and switch to a new git branch: `git checkout -b {branch_name}`\n"
        f"If the branch already exists, just switch to it: `git checkout {branch_name}`\n\n"
    )

    full_command = git_setup + instructions

    logger.info(
        f"Dispatching worker for task {task.id} ({task.title}) "
        f"in workspace {task.workspace_name} on branch {branch_name}"
    )

    result = await run_claude_code(
        folder_name=task.workspace_name,
        command=full_command,
        timeout=config.worker_timeout,
        max_turns=config.worker_max_turns,
        model=config.worker_model,
    )

    success = result.get("success", False)
    output = result.get("output", "")
    turns_used = result.get("turns_used", 0)
    exit_code = result.get("exit_code", -1)
    error = result.get("error_output") or result.get("error")

    if not success:
        logger.warning(
            f"Worker for task {task.id} failed: exit_code={exit_code}, error={error}"
        )

    return WorkerResult(
        success=success,
        output=output,
        turns_used=turns_used,
        exit_code=exit_code,
        error=error,
    )


async def get_workspace_diff(workspace_name: str, branch_name: str) -> str:
    """Get the git diff for a worker's branch.

    Runs `git diff main...{branch}` in the workspace to get the changes
    made by the worker. This diff is passed to review agents.

    Args:
        workspace_name: Workspace folder name.
        branch_name: The branch the worker committed to.

    Returns:
        The git diff output as a string.
    """
    diff_command = (
        f"Run `git diff main...{branch_name}` and output the full diff. "
        f"If main doesn't exist, use `git diff HEAD~1` instead. "
        f"Output ONLY the diff, nothing else."
    )

    result = await run_claude_code(
        folder_name=workspace_name,
        command=diff_command,
        timeout=60,
        max_turns=3,
        model="haiku",
    )

    return result.get("output", "")
