"""Worker dispatch for the orchestrator.

Workers are Claude Code instances running in isolated workspaces.
Each worker gets a focused task, works on a dedicated git branch,
and returns results for review.

NOTE: This module is not thread-safe. The Orchestrator serialises all
calls; concurrent usage requires external synchronisation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from agent_framework.tools.claude_code import (
    create_claude_code_workspace,
    get_claude_code_workspace_status,
    run_claude_code,
)

from .models import (
    OrchestratorConfig,
    Task,
    validate_git_ref,
    validate_workspace_name,
)
from .prompts import WORKER_INSTRUCTIONS_TEMPLATE

logger = logging.getLogger(__name__)

# Characters allowed in task text that gets interpolated into worker commands.
# Everything else is stripped to prevent injection via task title/description.
_SAFE_TASK_TEXT_RE = re.compile(r"[^a-zA-Z0-9 _.,'\"()\-:;!?@#/\n\r\t]+")


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
    validate_git_ref(branch, "generated branch name")

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


async def _auto_commit_if_needed(task: Task) -> None:
    """Commit uncommitted changes left by a worker as a safety net.

    Workers are instructed to commit, but if they don't, this ensures
    their work isn't lost before review and publish stages.
    """
    if not task.workspace_name:
        return

    workspaces_dir = os.environ.get(
        "CLAUDE_CODE_WORKSPACES_DIR",
        str(Path.home() / ".claude_code_workspaces"),
    )
    workspace_path = Path(workspaces_dir) / task.workspace_name

    if not workspace_path.is_dir():
        return

    try:
        # Check for uncommitted changes (staged + unstaged + untracked)
        proc = await asyncio.create_subprocess_exec(
            "git",
            "status",
            "--porcelain",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        status_output = stdout.decode("utf-8", errors="replace").strip()

        if not status_output:
            return  # Nothing to commit

        logger.warning(f"Worker for task {task.id} left uncommitted changes, auto-committing")

        # Stage all and commit
        proc = await asyncio.create_subprocess_exec(
            "git",
            "add",
            "-A",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)

        safe_title = _sanitise_task_text(task.title, max_length=100)
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            f"{safe_title}\n\nAuto-committed by orchestrator",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode == 0:
            logger.info(f"Auto-committed changes for task {task.id}")
        else:
            stderr_text = stderr.decode("utf-8", errors="replace")
            logger.warning(f"Auto-commit failed for task {task.id}: {stderr_text}")

    except Exception as e:
        logger.warning(f"Auto-commit check failed for task {task.id}: {e}")


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

    # Defense-in-depth: even pre-validated branch names are re-checked
    # before interpolation into commands sent to Claude Code.
    validate_git_ref(branch_name, "branch name before dispatch")
    task.branch_name = branch_name

    # Sanitise all user-controlled text before interpolation
    safe_title = _sanitise_task_text(task.title, max_length=200)
    safe_description = _sanitise_task_text(task.description)

    # Inject feedback from outcome store if available
    combined_context = context or ""
    try:
        from shared.outcome_store import get_relevant_feedback

        feedback = await get_relevant_feedback(task_category=task.category, limit=5)
        if feedback:
            combined_context = f"{combined_context}\n\n{feedback}" if combined_context else feedback
    except Exception as e:
        logger.debug(f"Could not fetch feedback for worker: {e}")

    safe_context = (
        _sanitise_task_text(combined_context) if combined_context else "No additional context."
    )

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

    # Prepend git branch setup — shlex.quote provides defense-in-depth
    # even though branch_name is already validated by regex above.
    quoted_branch = shlex.quote(branch_name)
    git_setup = (
        f"First, create and switch to a new git branch: `git checkout -b {quoted_branch}`\n"
        f"If the branch already exists, just switch to it: `git checkout {quoted_branch}`\n\n"
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
        skip_permissions=True,
    )

    success = result.get("success", False)
    output = result.get("output", "")
    turns_used = result.get("turns_used", 0)
    exit_code = result.get("exit_code", -1)
    error = result.get("error_output") or result.get("error")

    if not success:
        logger.warning(f"Worker for task {task.id} failed: exit_code={exit_code}, error={error}")

    # Safety net: if worker succeeded but forgot to commit, auto-commit
    if success:
        await _auto_commit_if_needed(task)

    return WorkerResult(
        success=success,
        output=output,
        turns_used=turns_used,
        exit_code=exit_code,
        error=error,
    )


async def push_and_create_pr(
    task: Task,
    config: OrchestratorConfig,
    diff_summary: str = "",
) -> str | None:
    """Push branch and create a PR via Claude Code.

    This is a mechanical step — Claude Code runs git push and gh pr create.
    Best-effort: returns the PR URL on success, None on failure.

    Args:
        task: The task with branch_name and workspace_name set.
        config: Orchestrator configuration (provides base_branch).
        diff_summary: Optional diff summary to include in the PR body.

    Returns:
        The PR URL, or None if push/PR creation failed.
    """
    if not task.workspace_name or not task.branch_name:
        logger.warning(f"Task {task.id} missing workspace/branch for publish")
        return None

    validate_workspace_name(task.workspace_name)
    validate_git_ref(task.branch_name, "branch name for publish")

    safe_title = _sanitise_task_text(task.title, max_length=200)
    safe_description = _sanitise_task_text(task.description, max_length=1000)

    # Build PR body content for the prompt
    body_diff = diff_summary[:2000] if diff_summary else ""
    body_parts = [safe_description]

    # Link back to the originating task (sanitize to prevent prompt/markdown injection)
    if task.external_id:
        safe_external_id = re.sub(r"[^a-zA-Z0-9_\-]", "", task.external_id)[:128]
        if safe_external_id:
            task_ref = f"Task: `{safe_external_id}`"
            taskmanager_url = os.environ.get("TASKMANAGER_URL", "").rstrip("/")
            if taskmanager_url:
                task_ref = f"Task: [{safe_external_id}]({taskmanager_url}/task/{safe_external_id})"
            body_parts.append(task_ref)

    if body_diff:
        body_parts.append(f"## Changes\n\n```\n{body_diff}\n```")
    pr_body = "\n\n".join(body_parts)

    prompt = (
        f"Push the current branch and create a pull request. "
        f"Run these commands:\n\n"
        f"1. `git push -u origin {shlex.quote(task.branch_name)}`\n"
        f"2. Create a PR with `gh pr create`:\n"
        f"   - Base branch: `{config.base_branch}`\n"
        f"   - Title: {safe_title}\n\n"
        f"Use the following as the PR body:\n\n{pr_body}\n\n"
        f"If push or PR creation fails, report the error. "
        f"Do NOT attempt to fix code or make additional commits."
    )

    logger.info(
        f"Publishing task {task.id}: pushing {task.branch_name} "
        f"and creating PR in workspace {task.workspace_name}"
    )

    result = await run_claude_code(
        folder_name=task.workspace_name,
        command=prompt,
        timeout=120,
        max_turns=5,
        model=config.worker_model,
        skip_permissions=True,
    )

    output = result.get("output", "")
    if not result.get("success", False):
        error = result.get("error_output") or result.get("error", "unknown")
        logger.warning(f"Publish failed for task {task.id}: {error}")
        return None

    # Extract PR URL from output
    pr_url = _extract_pr_url(output)

    # Fallback: query gh CLI directly if URL wasn't in sanitized output
    if not pr_url and task.workspace_name and task.branch_name:
        workspace_status = await get_claude_code_workspace_status(task.workspace_name)
        ws_path = workspace_status.get("workspace_path", "")
        # Defense-in-depth: ensure path is under the expected workspaces directory
        workspaces_dir = os.environ.get(
            "CLAUDE_CODE_WORKSPACES_DIR",
            str(Path.home() / ".claude_code_workspaces"),
        )
        if ws_path and Path(ws_path).resolve().is_relative_to(Path(workspaces_dir).resolve()):
            pr_url = await _find_pr_for_branch(ws_path, task.branch_name)
            if pr_url:
                logger.info(f"PR URL found via gh fallback for task {task.id}: {pr_url}")

    if pr_url:
        logger.info(f"PR created for task {task.id}: {pr_url}")
    else:
        logger.warning(f"Push succeeded but no PR URL found in output for task {task.id}")

    return pr_url


def _extract_pr_url(output: str) -> str | None:
    """Extract a GitHub PR URL from Claude Code output.

    Looks for https://github.com/.../pull/N patterns.  The output may have
    been wrapped by the LLM output sanitizer (boundary markers, zero-width
    spaces), so we strip those before matching.
    """
    # Strip zero-width characters that the sanitizer may have inserted
    cleaned = re.sub(r"[\u200b-\u200d\ufeff]", "", output)
    match = re.search(r"https://github\.com/[^\s\"'<>]+/pull/\d+", cleaned)
    return match.group(0) if match else None


async def _find_pr_for_branch(
    workspace_path: str,
    branch_name: str,
) -> str | None:
    """Find an existing PR URL for a branch using gh CLI.

    Fallback when URL extraction from Claude Code output fails.
    This handles cases where claude -p stdout doesn't include tool
    output, or where the sanitizer obscures the URL.

    Args:
        workspace_path: Path to the git workspace (for cwd).
        branch_name: The branch to look up.

    Returns:
        The PR URL, or None if no PR was found.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "pr",
            "list",
            "--head",
            branch_name,
            "--json",
            "url",
            "--limit",
            "1",
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode != 0:
            return None

        data = json.loads(stdout.decode("utf-8", errors="replace"))
        if data and isinstance(data, list) and data[0].get("url"):
            return data[0]["url"]
    except Exception as e:
        logger.debug(f"gh pr list fallback failed: {e}")

    return None


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

    # Validate refs before passing to subprocess (defense-in-depth)
    validate_git_ref(base_branch, "base_branch")
    validate_git_ref(branch_name, "branch_name")

    # Try diffing against the configured base branch
    # "--" separates revisions from paths, preventing option injection.
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            f"{base_branch}...{branch_name}",
            "--",
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
            logger.info(f"Base branch '{base_branch}' not found, falling back to HEAD~1")
        else:
            # Some other git error (empty diff is fine)
            if proc.returncode != 0:
                logger.warning(f"git diff failed: {stderr_text}")
            return stdout.decode("utf-8", errors="replace") if stdout else ""
    except TimeoutError:
        logger.warning("git diff timed out against base branch")
        return ""

    # Fallback: diff against HEAD~1
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "HEAD~1",
            "--",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode == 0:
            return stdout.decode("utf-8", errors="replace")

        # HEAD~1 doesn't exist (first commit) — diff against empty tree
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "4b825dc642cb6eb9a060e54bf899d8e3b71d8631",  # pragma: allowlist secret  # noqa: git empty tree SHA
            "HEAD",
            "--",
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout.decode("utf-8", errors="replace") if stdout else ""
    except TimeoutError:
        logger.warning("git diff fallback timed out")
        return ""
    except Exception as e:
        logger.error(f"git diff failed: {e}")
        return ""
