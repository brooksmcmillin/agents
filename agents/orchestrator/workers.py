"""Worker dispatch for the orchestrator.

Workers are Claude Code instances running in isolated workspaces.
Each worker gets a focused task, works on a dedicated git branch,
and returns results for review.

NOTE: This module is not thread-safe. The Orchestrator serialises all
calls; concurrent usage requires external synchronisation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agent_framework.tools.claude_code import (
    create_claude_code_workspace,
    get_claude_code_workspace_status,
    run_claude_code,
)

from .models import OrchestratorConfig, Task, validate_workspace_name
from .prompts import WORKER_INSTRUCTIONS_TEMPLATE

logger = logging.getLogger(__name__)

# Characters allowed in task text that gets interpolated into worker commands.
# Everything else is stripped to prevent injection via task title/description.
_SAFE_TASK_TEXT_RE = re.compile(r"[^a-zA-Z0-9 _.,'\"()\-:;!?@#/\n\r\t]+")

# Valid git branch name component (after sanitisation)
_GIT_REF_COMPONENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_/-]{0,200}$")


def _sanitise_task_text(text: str, max_length: int = 5000) -> str:
    """Strip potentially dangerous characters from task text.

    This prevents command injection when task titles/descriptions are
    interpolated into worker instructions sent to Claude Code.

    Args:
        text: Raw task text.
        max_length: Maximum allowed length.

    Returns:
        Sanitised text safe for interpolation.
    """
    cleaned = _SAFE_TASK_TEXT_RE.sub("", text)
    return cleaned[:max_length]


@dataclass
class WorkerResult:
    """Result from a Claude Code worker execution."""

    success: bool
    output: str
    turns_used: int
    exit_code: int
    error: str | None = None


def _branch_name_for_task(task: Task, config: OrchestratorConfig) -> str:
    """Generate a valid git branch name for a task.

    Args:
        task: The task being worked on.
        config: Orchestrator configuration.

    Returns:
        A valid, safe git branch name.

    Raises:
        ValueError: If a valid branch name cannot be generated.
    """
    # Sanitize title for branch name — allow only alphanumeric and hyphens
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", task.title.lower()).strip("-")[:50]
    if not slug:
        slug = "task"

    # Validate task.id is hex-safe (UUIDs always are, but be defensive)
    safe_id = re.sub(r"[^a-fA-F0-9]", "", task.id)
    if not safe_id:
        raise ValueError(f"Task ID contains no safe characters: {task.id!r}")

    branch = f"{config.branch_prefix}/{safe_id}-{slug}"

    # Final validation
    if not _GIT_REF_COMPONENT_RE.match(branch):
        raise ValueError(f"Generated branch name is not git-safe: {branch!r}")

    return branch


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
        The workspace folder name (validated safe).

    Raises:
        ValueError: If the workspace name is unsafe.
        RuntimeError: If workspace creation fails.
    """
    if task.workspace_name:
        # Validate the user-provided name before any filesystem operation
        validate_workspace_name(task.workspace_name)

        # Verify it exists
        try:
            status = await get_claude_code_workspace_status(task.workspace_name)
            if not status.get("error"):
                logger.info(f"Workspace {task.workspace_name} already exists")
                return task.workspace_name
        except Exception:
            logger.warning(f"Workspace {task.workspace_name} not found, creating new one")

    # Generate workspace name from task (full UUID, always safe)
    workspace_name = f"orch-{task.id}"
    validate_workspace_name(workspace_name)

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

    All user-controlled text (title, description, context) is sanitised
    before interpolation to prevent command injection.

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

    # Sanitise all user-controlled text before interpolation
    safe_title = _sanitise_task_text(task.title, max_length=200)
    safe_description = _sanitise_task_text(task.description)
    safe_context = _sanitise_task_text(context) if context else "No additional context."

    # Build worker instructions with sanitised text
    branch_info = f"Branch: {branch_name}\nCreate this branch and work on it."
    workspace_status = await get_claude_code_workspace_status(task.workspace_name)
    workspace_path = workspace_status.get("workspace_path", task.workspace_name)

    instructions = WORKER_INSTRUCTIONS_TEMPLATE.format(
        title=safe_title,
        description=safe_description,
        workspace_path=workspace_path,
        branch_info=branch_info,
        context=safe_context,
    )

    # Prepend git branch setup
    git_setup = (
        f"First, create and switch to a new git branch: `git checkout -b {branch_name}`\n"
        f"If the branch already exists, just switch to it: `git checkout {branch_name}`\n\n"
    )

    full_command = git_setup + instructions

    logger.info(
        f"Dispatching worker for task {task.id} ({safe_title}) "
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


async def get_workspace_diff(
    workspace_name: str,
    branch_name: str,
    config: OrchestratorConfig | None = None,
) -> str:
    """Get the git diff for a worker's branch using subprocess.

    Runs ``git diff`` directly via subprocess instead of through Claude Code
    to avoid latency and parsing issues.  Falls back to ``HEAD~1`` when the
    base branch does not exist, and to an empty string on first-commit repos.

    Args:
        workspace_name: Workspace folder name (validated).
        branch_name: The branch the worker committed to.
        config: Optional config (provides base_branch). Defaults to "main".

    Returns:
        The git diff output as a string (may be empty).
    """
    validate_workspace_name(workspace_name)

    # Resolve workspace path
    workspaces_dir = os.environ.get(
        "CLAUDE_CODE_WORKSPACES_DIR",
        str(Path.home() / ".claude_code_workspaces"),
    )
    workspace_path = Path(workspaces_dir) / workspace_name

    if not workspace_path.is_dir():
        logger.warning(f"Workspace directory not found: {workspace_path}")
        return ""

    base_branch = config.base_branch if config else "main"

    # Try diffing against the configured base branch
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", f"{base_branch}...{branch_name}",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode == 0 and stdout:
            return stdout.decode("utf-8", errors="replace")

        # Base branch might not exist — detect and try fallback
        stderr_text = stderr.decode("utf-8", errors="replace")
        if "unknown revision" in stderr_text or "bad revision" in stderr_text:
            logger.info(
                f"Base branch '{base_branch}' not found, falling back to HEAD~1"
            )
        else:
            # Some other git error (empty diff is fine)
            if proc.returncode != 0:
                logger.warning(f"git diff failed: {stderr_text}")
            return stdout.decode("utf-8", errors="replace") if stdout else ""
    except asyncio.TimeoutError:
        logger.warning("git diff timed out against base branch")
        return ""

    # Fallback: diff against HEAD~1
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD~1",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode == 0:
            return stdout.decode("utf-8", errors="replace")

        # HEAD~1 doesn't exist (first commit) — diff against empty tree
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "4b825dc642cb6eb9a060e54bf899d8e3b71d8631", "HEAD",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout.decode("utf-8", errors="replace") if stdout else ""
    except asyncio.TimeoutError:
        logger.warning("git diff fallback timed out")
        return ""
    except Exception as e:
        logger.error(f"git diff failed: {e}")
        return ""
