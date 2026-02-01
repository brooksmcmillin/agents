"""Claude Code automation tools for spawning headless instances.

These tools allow agents to spawn headless Claude Code instances to work on
code in isolated workspace directories, enabling meta-programming and
delegation to Claude Code for complex coding tasks.

Security Note:
    The output from Claude Code (an LLM) is automatically sanitized before
    being returned to the calling agent (another LLM). This prevents indirect
    prompt injection attacks where malicious content in the subprocess output
    could manipulate the parent agent's behavior.

    The sanitization includes:
    - Structural isolation with clear data delimiters
    - Detection and escaping of common prompt injection patterns
    - Length limits to prevent context overflow attacks
"""

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

from agent_framework.security import LLMOutputSanitizer

logger = logging.getLogger(__name__)

# Shared sanitizer instance for LLM output
_output_sanitizer = LLMOutputSanitizer(
    max_length=100000,  # 100K character limit
    escape_suspicious=True,
    strict_mode=False,  # Escape rather than remove
)

# Default base directory for workspaces (configurable via environment)
DEFAULT_WORKSPACES_DIR = os.environ.get(
    "CLAUDE_CODE_WORKSPACES_DIR",
    str(Path.home() / ".claude_code_workspaces"),
)


def _validate_folder_name(folder_name: str) -> None:
    """Validate folder name to prevent path traversal attacks.

    Args:
        folder_name: The folder name to validate

    Raises:
        ValueError: If folder name contains invalid characters
    """
    # Only allow alphanumeric, hyphens, underscores, and dots (but not at start)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*$", folder_name):
        raise ValueError(
            f"Invalid folder name: {folder_name}. "
            "Must start with alphanumeric and contain only alphanumeric, "
            "hyphens, underscores, and dots."
        )

    # Prevent path traversal
    if ".." in folder_name or "/" in folder_name or "\\" in folder_name:
        raise ValueError(
            f"Invalid folder name: {folder_name}. Path traversal characters not allowed."
        )


def _get_workspace_path(folder_name: str, working_dir_base: str | None) -> Path:
    """Get and validate the full workspace path.

    Args:
        folder_name: Name of the workspace folder
        working_dir_base: Base directory for workspaces (optional)

    Returns:
        Path object for the workspace

    Raises:
        ValueError: If folder name is invalid
        FileNotFoundError: If workspace doesn't exist
    """
    _validate_folder_name(folder_name)

    base_dir = Path(working_dir_base or DEFAULT_WORKSPACES_DIR).expanduser()
    workspace_path = base_dir / folder_name

    if not workspace_path.exists():
        # List available workspaces synchronously for error message
        available = (
            [d.name for d in base_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if base_dir.exists()
            else []
        )
        raise FileNotFoundError(
            f"Workspace not found: {workspace_path}. Available workspaces: {available}"
        )

    if not workspace_path.is_dir():
        raise ValueError(f"Path exists but is not a directory: {workspace_path}")

    return workspace_path


async def run_claude_code(
    folder_name: str,
    command: str,
    timeout: int = 300,
    max_turns: int = 10,
    model: str = "sonnet",
    working_dir_base: str | None = None,
    custom_instructions: str | None = None,
    env: dict[str, str] | None = None,
    sanitize_output: bool = True,
) -> dict[str, Any]:
    """Run headless Claude Code in a workspace folder.

    This tool spawns a headless Claude Code instance, sends it a command,
    waits for completion, and returns the results. Useful for delegating
    complex coding tasks to Claude Code while maintaining isolation.

    Security: By default, output is sanitized to prevent indirect prompt
    injection attacks when the output is passed to another LLM. This includes
    structural isolation (data boundary markers), detection and escaping of
    suspicious patterns, and length limits.

    Args:
        folder_name: Name of workspace folder (must exist in workspaces directory)
        command: Command/message to send to Claude Code
        timeout: Maximum seconds to wait for completion (default: 300)
        max_turns: Maximum agentic turns to allow (default: 10)
        model: Claude model to use - "sonnet", "haiku", or "opus" (default: "sonnet")
        working_dir_base: Base directory for workspaces (optional, uses env var or default)
        custom_instructions: Optional custom instructions to prepend to command
        env: Optional environment variables to pass to the subprocess
        sanitize_output: Whether to sanitize output for safe LLM-to-LLM passing (default: True)

    Returns:
        Dict with:
            - success: bool - Whether command completed successfully
            - output: str - Full conversation output from Claude Code (sanitized if enabled)
            - final_response: str - Last response from Claude (sanitized if enabled)
            - turns_used: int - Number of agentic turns used
            - workspace_path: str - Full path to workspace
            - command: str - The command that was executed
            - exit_code: int - Process exit code
            - _sanitization: dict - Sanitization metadata (if sanitize_output=True)

    Raises:
        ValueError: If folder_name is invalid or model is unknown
        FileNotFoundError: If workspace doesn't exist
        TimeoutError: If command execution exceeds timeout

    Example:
        >>> result = await run_claude_code(
        ...     folder_name="my_project",
        ...     command="Fix the authentication bug in login.py",
        ...     timeout=600,
        ...     max_turns=15,
        ...     model="sonnet"
        ... )
        >>> print(result['final_response'])
    """
    workspace_path: Path | None = None
    try:
        workspace_path = _get_workspace_path(folder_name, working_dir_base)

        # Validate model
        model_map = {"sonnet": "sonnet", "haiku": "haiku", "opus": "opus"}
        if model.lower() not in model_map:
            raise ValueError(f"Unknown model: {model}. Valid options: {list(model_map.keys())}")

        # Check if claude CLI is available
        if not shutil.which("claude"):
            raise RuntimeError(
                "Claude Code CLI not found. Please install it first: "
                "https://github.com/anthropics/claude-code"
            )

        # Prepare command with custom instructions if provided
        full_command = command
        if custom_instructions:
            full_command = f"{custom_instructions}\n\n{command}"

        # Build claude command with prompt passed as argument to -p
        claude_cmd = [
            "claude",
            "-p",
            full_command,  # Pass prompt directly as argument
            "--dangerously-skip-permissions",
            "--max-turns",
            str(max_turns),
        ]

        # Add model if not default
        if model.lower() != "sonnet":
            claude_cmd.extend(["--model", model_map[model.lower()]])

        logger.info(f"Running Claude Code in {workspace_path} with command: {command[:100]}...")

        # Run claude and wait for completion
        process = await asyncio.create_subprocess_exec(
            *claude_cmd,
            cwd=str(workspace_path),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            output = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")
        except TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Claude Code execution exceeded timeout of {timeout}s")

        # Parse output to extract final response and turn count
        # Claude Code typically outputs conversation in a structured way
        final_response = output.strip().split("\n")[-1] if output else ""
        turns_used = output.count("Assistant:")  # Rough estimate of turns used

        success = process.returncode == 0

        # Apply output sanitization if enabled (protects against prompt injection)
        sanitization_metadata: dict[str, Any] = {}
        if sanitize_output and output:
            # Sanitize main output
            output_result = _output_sanitizer.sanitize_llm_output(
                output, source="run_claude_code.output"
            )
            sanitized_output = output_result.wrapped_content

            # Sanitize final response
            response_result = _output_sanitizer.sanitize_llm_output(
                final_response, source="run_claude_code.final_response"
            )
            sanitized_final_response = response_result.wrapped_content

            sanitization_metadata = {
                "enabled": True,
                "output_patterns_detected": output_result.patterns_detected,
                "output_was_truncated": output_result.was_truncated,
                "response_patterns_detected": response_result.patterns_detected,
                "output_hash": output_result.content_hash,
            }

            # Log if suspicious patterns were detected
            if output_result.patterns_detected or response_result.patterns_detected:
                all_patterns = list(
                    set(output_result.patterns_detected + response_result.patterns_detected)
                )
                logger.warning(
                    f"Claude Code output contained suspicious patterns that were sanitized: {all_patterns}"
                )
        else:
            sanitized_output = output
            sanitized_final_response = final_response
            sanitization_metadata = {"enabled": False}

        result: dict[str, Any] = {
            "success": success,
            "output": sanitized_output,
            "error_output": error_output if error_output else None,
            "final_response": sanitized_final_response,
            "turns_used": turns_used,
            "workspace_path": str(workspace_path),
            "command": command,
            "exit_code": process.returncode,
            "_sanitization": sanitization_metadata,
        }

        if not success:
            logger.warning(f"Claude Code exited with code {process.returncode}: {error_output}")

        logger.info(
            f"Claude Code completed in {workspace_path} - "
            f"Exit code: {process.returncode}, Turns: {turns_used}"
        )

        return result

    except Exception as e:
        logger.error(f"Error running Claude Code: {e}")
        return {
            "success": False,
            "output": "",
            "error_output": str(e),
            "final_response": "",
            "turns_used": 0,
            "workspace_path": str(workspace_path) if workspace_path else "",
            "command": command,
            "exit_code": -1,
            "error": str(e),
        }


async def list_claude_code_workspaces(
    working_dir_base: str | None = None,
) -> dict[str, Any]:
    """List available workspace folders for Claude Code.

    Args:
        working_dir_base: Base directory for workspaces (optional)

    Returns:
        Dict with:
            - workspaces: List of workspace info dicts containing:
                - name: Workspace folder name
                - path: Full path to workspace
                - is_git_repo: Whether it's a git repository
                - size_mb: Approximate size in MB
            - base_dir: Base directory being used
            - count: Total number of workspaces

    Example:
        >>> result = await list_claude_code_workspaces()
        >>> for ws in result['workspaces']:
        ...     print(f"{ws['name']}: {ws['path']}")
    """
    base_dir = Path(working_dir_base or DEFAULT_WORKSPACES_DIR).expanduser()
    try:
        # Create base directory if it doesn't exist
        base_dir.mkdir(parents=True, exist_ok=True)

        workspaces = []
        for item in sorted(base_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                # Check if it's a git repo
                is_git_repo = (item / ".git").exists()

                # Calculate approximate size
                try:
                    size_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    size_mb = round(size_bytes / (1024 * 1024), 2)
                except Exception as e:
                    logger.warning(f"Failed to calculate size for {item}: {e}")
                    size_mb = 0

                workspaces.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "is_git_repo": is_git_repo,
                        "size_mb": size_mb,
                    }
                )

        return {
            "workspaces": workspaces,
            "base_dir": str(base_dir),
            "count": len(workspaces),
        }

    except Exception as e:
        logger.error(f"Error listing workspaces: {e}")
        return {
            "workspaces": [],
            "base_dir": str(base_dir),
            "count": 0,
            "error": str(e),
        }


async def create_claude_code_workspace(
    folder_name: str,
    git_repo_url: str | None = None,
    working_dir_base: str | None = None,
) -> dict[str, Any]:
    """Create a new workspace folder for Claude Code.

    Args:
        folder_name: Name for the new workspace
        git_repo_url: Optional git repository URL to clone
        working_dir_base: Base directory for workspaces (optional)

    Returns:
        Dict with:
            - success: bool - Whether workspace was created
            - workspace_path: str - Full path to new workspace
            - is_git_repo: bool - Whether it's a git repository
            - message: str - Success or error message

    Example:
        >>> result = await create_claude_code_workspace(
        ...     folder_name="new_project",
        ...     git_repo_url="https://github.com/user/repo.git"
        ... )
    """
    workspace_path = None
    try:
        _validate_folder_name(folder_name)

        base_dir = Path(working_dir_base or DEFAULT_WORKSPACES_DIR).expanduser()
        base_dir.mkdir(parents=True, exist_ok=True)

        workspace_path = base_dir / folder_name

        if workspace_path.exists():
            raise ValueError(f"Workspace already exists: {workspace_path}")

        # Create workspace directory
        workspace_path.mkdir(parents=True, exist_ok=True)

        is_git_repo = False

        # Clone git repo if URL provided
        if git_repo_url:
            logger.info(f"Cloning {git_repo_url} into {workspace_path}")
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                git_repo_url,
                str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            if process.returncode != 0:
                # Clean up failed clone
                shutil.rmtree(workspace_path, ignore_errors=True)
                raise RuntimeError(f"Git clone failed: {stderr.decode('utf-8', errors='replace')}")

            is_git_repo = True
        else:
            # Initialize empty git repo
            logger.info(f"Initializing git repository in {workspace_path}")
            process = await asyncio.create_subprocess_exec(
                "git",
                "init",
                str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()
            is_git_repo = process.returncode == 0

        logger.info(f"Created workspace: {workspace_path}")

        return {
            "success": True,
            "workspace_path": str(workspace_path),
            "is_git_repo": is_git_repo,
            "message": f"Workspace created successfully at {workspace_path}",
        }

    except Exception as e:
        logger.error(f"Error creating workspace: {e}")
        return {
            "success": False,
            "workspace_path": str(workspace_path) if workspace_path else "",
            "is_git_repo": False,
            "message": str(e),
            "error": str(e),
        }


async def delete_claude_code_workspace(
    folder_name: str,
    working_dir_base: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Delete a workspace folder.

    Args:
        folder_name: Name of workspace to delete
        working_dir_base: Base directory for workspaces (optional)
        force: Force deletion even if workspace has uncommitted changes

    Returns:
        Dict with:
            - success: bool - Whether workspace was deleted
            - workspace_path: str - Path that was deleted
            - message: str - Success or error message
            - had_uncommitted_changes: bool - Whether there were uncommitted changes

    Example:
        >>> result = await delete_claude_code_workspace(
        ...     folder_name="old_project",
        ...     force=True
        ... )
    """
    workspace_path = None
    try:
        workspace_path = _get_workspace_path(folder_name, working_dir_base)

        had_uncommitted_changes = False

        # Check for uncommitted changes if it's a git repo
        if workspace_path and (workspace_path / ".git").exists() and not force:
            process = await asyncio.create_subprocess_exec(
                "git",
                "status",
                "--porcelain",
                cwd=str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if stdout.strip():
                had_uncommitted_changes = True
                return {
                    "success": False,
                    "workspace_path": str(workspace_path),
                    "message": "Workspace has uncommitted changes. Use force=True to delete anyway.",
                    "had_uncommitted_changes": True,
                    "error": "Uncommitted changes detected",
                }

        # Delete the workspace
        logger.info(f"Deleting workspace: {workspace_path}")
        shutil.rmtree(workspace_path)

        return {
            "success": True,
            "workspace_path": str(workspace_path),
            "message": f"Workspace deleted successfully: {workspace_path}",
            "had_uncommitted_changes": had_uncommitted_changes,
        }

    except Exception as e:
        logger.error(f"Error deleting workspace: {e}")
        return {
            "success": False,
            "workspace_path": str(workspace_path) if workspace_path else "",
            "message": str(e),
            "had_uncommitted_changes": False,
            "error": str(e),
        }


async def get_claude_code_workspace_status(
    folder_name: str,
    working_dir_base: str | None = None,
) -> dict[str, Any]:
    """Get detailed status of a workspace folder.

    Args:
        folder_name: Name of workspace
        working_dir_base: Base directory for workspaces (optional)

    Returns:
        Dict with:
            - workspace_path: str - Full path to workspace
            - is_git_repo: bool - Whether it's a git repository
            - git_status: str - Git status output (if applicable)
            - has_uncommitted_changes: bool - Whether there are uncommitted changes
            - current_branch: str - Current git branch (if applicable)
            - file_count: int - Number of files in workspace
            - size_mb: float - Approximate size in MB

    Example:
        >>> status = await get_claude_code_workspace_status("my_project")
        >>> print(status['git_status'])
    """
    workspace_path = None
    try:
        workspace_path = _get_workspace_path(folder_name, working_dir_base)

        is_git_repo = (workspace_path / ".git").exists()
        git_status = ""
        has_uncommitted_changes = False
        current_branch = ""

        # Get git status if it's a git repo
        if is_git_repo:
            # Get current branch
            process = await asyncio.create_subprocess_exec(
                "git",
                "branch",
                "--show-current",
                cwd=str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            current_branch = stdout.decode("utf-8").strip()

            # Get status
            process = await asyncio.create_subprocess_exec(
                "git",
                "status",
                "--porcelain",
                cwd=str(workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            git_status = stdout.decode("utf-8").strip()
            has_uncommitted_changes = bool(git_status)

        # Count files and calculate size
        file_count = sum(1 for _ in workspace_path.rglob("*") if _.is_file())
        size_bytes = sum(f.stat().st_size for f in workspace_path.rglob("*") if f.is_file())
        size_mb = round(size_bytes / (1024 * 1024), 2)

        return {
            "workspace_path": str(workspace_path),
            "is_git_repo": is_git_repo,
            "git_status": git_status,
            "has_uncommitted_changes": has_uncommitted_changes,
            "current_branch": current_branch,
            "file_count": file_count,
            "size_mb": size_mb,
        }

    except Exception as e:
        logger.error(f"Error getting workspace status: {e}")
        return {
            "workspace_path": str(workspace_path) if workspace_path else "",
            "is_git_repo": False,
            "git_status": "",
            "has_uncommitted_changes": False,
            "current_branch": "",
            "file_count": 0,
            "size_mb": 0,
            "error": str(e),
        }


# Tool schemas for MCP server registration
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "run_claude_code",
        "description": (
            "Run headless Claude Code in a workspace folder. "
            "Spawns a Claude Code instance, sends it a command, and returns results. "
            "Useful for delegating complex coding tasks to Claude Code in isolated workspaces."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {
                    "type": "string",
                    "description": "Name of workspace folder (must exist in workspaces directory)",
                },
                "command": {
                    "type": "string",
                    "description": "Command or message to send to Claude Code",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for completion (default: 300)",
                    "default": 300,
                },
                "max_turns": {
                    "type": "integer",
                    "description": "Maximum agentic turns to allow (default: 10)",
                    "default": 10,
                },
                "model": {
                    "type": "string",
                    "description": "Claude model to use: 'sonnet', 'haiku', or 'opus' (default: 'sonnet')",
                    "default": "sonnet",
                    "enum": ["sonnet", "haiku", "opus"],
                },
                "working_dir_base": {
                    "type": "string",
                    "description": "Base directory for workspaces (optional, uses CLAUDE_CODE_WORKSPACES_DIR env var or default)",
                },
                "custom_instructions": {
                    "type": "string",
                    "description": "Optional custom instructions to prepend to the command",
                },
                "sanitize_output": {
                    "type": "boolean",
                    "description": (
                        "Whether to sanitize output for safe LLM-to-LLM passing. "
                        "Prevents prompt injection attacks. Default: true"
                    ),
                    "default": True,
                },
            },
            "required": ["folder_name", "command"],
        },
        "handler": run_claude_code,
    },
    {
        "name": "list_claude_code_workspaces",
        "description": (
            "List all available workspace folders for Claude Code. "
            "Shows workspace names, paths, git status, and sizes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "working_dir_base": {
                    "type": "string",
                    "description": "Base directory for workspaces (optional)",
                }
            },
        },
        "handler": list_claude_code_workspaces,
    },
    {
        "name": "create_claude_code_workspace",
        "description": (
            "Create a new workspace folder for Claude Code. "
            "Optionally clone a git repository into the workspace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {
                    "type": "string",
                    "description": "Name for the new workspace folder",
                },
                "git_repo_url": {
                    "type": "string",
                    "description": "Optional git repository URL to clone",
                },
                "working_dir_base": {
                    "type": "string",
                    "description": "Base directory for workspaces (optional)",
                },
            },
            "required": ["folder_name"],
        },
        "handler": create_claude_code_workspace,
    },
    {
        "name": "delete_claude_code_workspace",
        "description": (
            "Delete a workspace folder. Checks for uncommitted changes unless force=True."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {
                    "type": "string",
                    "description": "Name of workspace to delete",
                },
                "working_dir_base": {
                    "type": "string",
                    "description": "Base directory for workspaces (optional)",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force deletion even with uncommitted changes (default: false)",
                    "default": False,
                },
            },
            "required": ["folder_name"],
        },
        "handler": delete_claude_code_workspace,
    },
    {
        "name": "get_claude_code_workspace_status",
        "description": (
            "Get detailed status of a workspace folder. "
            "Shows git status, file count, size, and branch information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder_name": {
                    "type": "string",
                    "description": "Name of workspace to check",
                },
                "working_dir_base": {
                    "type": "string",
                    "description": "Base directory for workspaces (optional)",
                },
            },
            "required": ["folder_name"],
        },
        "handler": get_claude_code_workspace_status,
    },
]
