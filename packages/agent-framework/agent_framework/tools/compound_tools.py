"""Compound tools that bundle common tool sequences into single tool calls.

Agents have access to 55+ individual tools, but common workflows require chaining
several together, each costing an LLM iteration. Compound tools reduce iteration
count (and thus latency/cost) by executing entire workflows in a single call.

These are parameterized templates, not hard-coded workflows -- callers control
behavior through arguments rather than being locked into fixed sequences.

Examples:
    - research_and_save: fetch_web_content -> sanitize -> save_memory
    - execute_in_workspace: create workspace -> run claude code -> capture output -> cleanup
"""

import logging
import uuid
from typing import Any

from ..security import LLMOutputSanitizer
from ..utils.tool_decorators import handle_tool_errors
from .claude_code import (
    create_claude_code_workspace,
    delete_claude_code_workspace,
    run_claude_code,
)
from .memory import save_memory
from .web_reader import fetch_web_content

logger = logging.getLogger(__name__)

# Maximum characters stored in a single memory entry.  The memory backend
# enforces its own 10 000 char limit (MAX_VALUE_LENGTH in memory.py), but we
# truncate *before* saving so that the metadata header is preserved and the
# caller gets a correct ``was_truncated`` flag.
_MAX_MEMORY_CHARS = 10_000

# Maximum timeout (seconds) and agentic turns for execute_in_workspace.
_MAX_TIMEOUT = 3600
_MAX_TURNS = 50

# Sanitizer for web content before saving to memory.  Prevents prompt
# injection via malicious web pages whose title or body contain instructions
# that could manipulate the agent when the memory is recalled later.
_web_content_sanitizer = LLMOutputSanitizer(
    max_length=_MAX_MEMORY_CHARS,
    escape_suspicious=True,
    strict_mode=False,
    block_on_critical=False,  # Don't block -- just escape suspicious patterns
)


@handle_tool_errors(operation="research and save")
async def research_and_save(
    url: str,
    memory_key: str,
    extraction_hint: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    importance: int = 5,
    max_length: int = 50000,
    agent_name: str = "shared",
) -> dict[str, Any]:
    """Fetch web content, sanitize it, and save to memory.

    This compound tool replaces the common 2-3 step sequence of:
    1. fetch_web_content(url)
    2. (optionally) ask LLM to summarize
    3. save_memory(key, content)

    Web content is sanitized via ``LLMOutputSanitizer`` before being stored
    to prevent prompt injection when memories are recalled later.

    Note: The stored value is capped at ``_MAX_MEMORY_CHARS`` (10 000 chars)
    regardless of ``max_length``.  The ``max_length`` parameter controls how
    much is *fetched*; the memory limit controls how much is *saved*.

    Args:
        url: The URL to fetch content from.
        memory_key: Key to save the content under in memory.
        extraction_hint: Optional annotation describing what to look for in
            the content.  Prepended to the saved value as context for future
            recall.  No LLM summarization is performed -- for that, use the
            individual tools and handle summarization in your own loop.
        category: Optional memory category (e.g., "research", "reference").
        tags: Optional tags for memory organization.
        importance: Memory importance level 1-10 (default: 5).
        max_length: Maximum content length in characters when fetching
            (default: 50000).  Stored value is always capped at
            ``_MAX_MEMORY_CHARS`` (10 000).
        agent_name: Agent identifier for memory isolation (default: "shared").

    Returns:
        Dictionary with combined results from fetch and save steps:
            - status: "success" or "error"
            - fetch_result: Result from fetch_web_content
            - save_result: Result from save_memory
            - url: The fetched URL
            - memory_key: The key used for saving
            - content_length: Length of saved content
            - was_truncated: Whether content was truncated to fit memory limit
    """
    # Step 1: Fetch web content
    logger.info(f"Compound: fetching web content from {url}")
    fetch_result = await fetch_web_content(url=url, max_length=max_length)

    # Check for fetch errors
    if fetch_result.get("status") == "error":
        return {
            "status": "error",
            "message": f"Failed to fetch content: {fetch_result.get('message', 'unknown error')}",
            "fetch_result": fetch_result,
            "save_result": None,
            "url": url,
            "memory_key": memory_key,
            "content_length": 0,
            "was_truncated": False,
        }

    # Extract content from fetch result
    raw_content = fetch_result.get("content", "")
    raw_title = fetch_result.get("title", "No title")

    # Step 2: Sanitize web content to prevent prompt injection when recalled
    sanitize_result = _web_content_sanitizer.sanitize_llm_output(
        raw_content, source="research_and_save.content"
    )
    content = sanitize_result.sanitized_content

    title_sanitize = _web_content_sanitizer.sanitize_llm_output(
        raw_title, source="research_and_save.title"
    )
    title = title_sanitize.sanitized_content

    if sanitize_result.patterns_detected or title_sanitize.patterns_detected:
        all_patterns = list(
            set(sanitize_result.patterns_detected + title_sanitize.patterns_detected)
        )
        logger.warning(
            f"Web content from {url} contained suspicious patterns that were sanitized: "
            f"{all_patterns}"
        )

    # Step 3: Prepare value for memory
    # Sanitize extraction_hint if provided (caller-controlled input that ends
    # up in the memory store and later in an LLM context window).
    if extraction_hint:
        hint_sanitize = _web_content_sanitizer.sanitize_llm_output(
            extraction_hint, source="research_and_save.extraction_hint"
        )
        sanitized_hint = hint_sanitize.sanitized_content
        value = (
            f"[Extraction hint: {sanitized_hint}]\n[Source: {url}]\n[Title: {title}]\n\n{content}"
        )
    else:
        value = f"[Source: {url}]\n[Title: {title}]\n\n{content}"

    # Truncate value if it exceeds memory limits
    was_truncated = len(value) > _MAX_MEMORY_CHARS
    if was_truncated:
        value = value[: _MAX_MEMORY_CHARS - 50] + "\n\n[Content truncated to fit memory limit]"

    # Step 4: Save to memory
    logger.info(f"Compound: saving fetched content to memory key '{memory_key}'")
    save_result = await save_memory(
        key=memory_key,
        value=value,
        category=category or "research",
        tags=tags or ["web", "compound_tool"],
        importance=importance,
        agent_name=agent_name,
    )

    return {
        "status": "success",
        "fetch_result": {
            "url": fetch_result.get("url", url),
            "title": title,
            "word_count": fetch_result.get("word_count", 0),
            "char_count": fetch_result.get("char_count", 0),
        },
        "save_result": save_result,
        "url": url,
        "memory_key": memory_key,
        "content_length": len(value),
        "was_truncated": was_truncated,
        "message": f"Fetched '{title}' from {url} and saved to memory as '{memory_key}'",
    }


@handle_tool_errors(operation="execute in workspace")
async def execute_in_workspace(
    prompt: str,
    repo_url: str | None = None,
    workspace_name: str | None = None,
    timeout: int = 300,
    max_turns: int = 10,
    model: str = "sonnet",
    cleanup: bool = True,
    working_dir_base: str | None = None,
    custom_instructions: str | None = None,
) -> dict[str, Any]:
    """Create a workspace, run Claude Code, capture output, and optionally clean up.

    This compound tool replaces the common 3-4 step sequence of:
    1. create_claude_code_workspace(name, repo_url)
    2. run_claude_code(name, prompt)
    3. (capture and process output)
    4. delete_claude_code_workspace(name)

    Args:
        prompt: The command/message to send to Claude Code.
        repo_url: Optional git repository URL to clone into workspace.
            Must use SSH format (git@host:path).
        workspace_name: Optional workspace folder name. If not provided,
            a unique name is auto-generated.
        timeout: Maximum seconds for Claude Code execution (default: 300,
            max: 3600).
        max_turns: Maximum agentic turns for Claude Code (default: 10,
            max: 50).
        model: Claude model to use -- "sonnet", "haiku", or "opus" (default: "sonnet").
        cleanup: Whether to delete workspace after execution (default: True).
        working_dir_base: Base directory for workspaces (optional).
        custom_instructions: Optional custom instructions to prepend to prompt.

    Returns:
        Dictionary with combined results from all steps:
            - status: "success" or "error"
            - workspace_name: Name of the workspace used
            - create_result: Result from workspace creation
            - run_result: Result from Claude Code execution
            - cleanup_result: Result from workspace deletion (if cleanup=True)
            - output: Final output from Claude Code
            - final_response: Last response from Claude Code
            - success: Whether execution completed successfully
            - turns_used: Number of agentic turns consumed
            - workspace_cleaned_up: Whether the workspace was deleted
    """
    # Clamp timeout and max_turns to safe upper bounds
    timeout = min(timeout, _MAX_TIMEOUT)
    max_turns = min(max_turns, _MAX_TURNS)

    # Validate working_dir_base to prevent path traversal
    if working_dir_base and ".." in working_dir_base:
        raise ValueError("working_dir_base cannot contain path traversal sequences (..)")

    # Generate workspace name if not provided
    if not workspace_name:
        workspace_name = f"compound-{uuid.uuid4().hex[:12]}"

    create_result: dict[str, Any] | None = None
    run_result: dict[str, Any] | None = None
    cleanup_result: dict[str, Any] | None = None

    try:
        # Step 1: Create workspace
        logger.info(f"Compound: creating workspace '{workspace_name}'")
        create_result = await create_claude_code_workspace(
            folder_name=workspace_name,
            git_repo_url=repo_url,
            working_dir_base=working_dir_base,
        )

        if not create_result.get("success"):
            return {
                "status": "error",
                "message": (
                    f"Failed to create workspace: {create_result.get('message', 'unknown error')}"
                ),
                "workspace_name": workspace_name,
                "create_result": create_result,
                "run_result": None,
                "cleanup_result": None,
                "output": "",
                "final_response": "",
                "success": False,
                "turns_used": 0,
                "workspace_cleaned_up": False,
            }

        # Step 2: Run Claude Code
        # Note: custom_instructions is validated by run_claude_code's own
        # _llm_sanitizer.validate_llm_input() which blocks critical patterns.
        logger.info(f"Compound: running Claude Code in workspace '{workspace_name}'")
        run_result = await run_claude_code(
            folder_name=workspace_name,
            command=prompt,
            timeout=timeout,
            max_turns=max_turns,
            model=model,
            working_dir_base=working_dir_base,
            custom_instructions=custom_instructions,
        )

        # Results are extracted from run_result in the return dict below

    finally:
        # Step 3: Cleanup (always attempt if cleanup=True, even on error)
        if cleanup and create_result and create_result.get("success"):
            logger.info(f"Compound: cleaning up workspace '{workspace_name}'")
            cleanup_result = await delete_claude_code_workspace(
                folder_name=workspace_name,
                working_dir_base=working_dir_base,
                force=True,
            )

    return {
        "status": "success" if run_result and run_result.get("success") else "error",
        "workspace_name": workspace_name,
        "create_result": create_result,
        "run_result": run_result,
        "cleanup_result": cleanup_result,
        "output": run_result.get("output", "") if run_result else "",
        "final_response": run_result.get("final_response", "") if run_result else "",
        "success": run_result.get("success", False) if run_result else False,
        "turns_used": run_result.get("turns_used", 0) if run_result else 0,
        "workspace_cleaned_up": bool(cleanup_result and cleanup_result.get("success")),
        "message": (
            f"Executed prompt in workspace '{workspace_name}'"
            if run_result and run_result.get("success")
            else f"Execution failed in workspace '{workspace_name}'"
        ),
    }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "research_and_save",
        "description": (
            "Compound tool: Fetch web content from a URL, sanitize it for prompt "
            "injection safety, and save it to memory in one step. "
            "Replaces the common sequence of fetch_web_content -> save_memory. "
            "Optionally accepts an extraction hint to annotate the saved content. "
            "Reduces tool iterations from 2-3 to 1."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from (must start with http:// or https://)",
                },
                "memory_key": {
                    "type": "string",
                    "maxLength": 256,
                    "description": (
                        "Key to save the content under in memory (e.g., 'research_python_async')"
                    ),
                },
                "extraction_hint": {
                    "type": "string",
                    "maxLength": 1000,
                    "description": (
                        "Optional annotation describing what to look for in the content. "
                        "Prepended to the saved value as context for future recall. "
                        "No LLM summarization is performed."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": "Memory category (default: 'research')",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for memory organization (default: ['web', 'compound_tool'])",
                },
                "importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "description": "Memory importance level 1-10",
                },
                "max_length": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 100000,
                    "default": 50000,
                    "description": (
                        "Maximum content length in characters when fetching. "
                        "Note: stored value is always capped at 10000 chars."
                    ),
                },
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation (default: 'shared')",
                },
            },
            "required": ["url", "memory_key"],
        },
        "handler": research_and_save,
    },
    {
        "name": "execute_in_workspace",
        "description": (
            "Compound tool: Create a Claude Code workspace, run a prompt, capture output, "
            "and clean up -- all in one step. Replaces the common sequence of "
            "create_claude_code_workspace -> run_claude_code -> delete_claude_code_workspace. "
            "Optionally clones a git repo into the workspace before execution. "
            "Reduces tool iterations from 3-4 to 1."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The command/message to send to Claude Code",
                },
                "repo_url": {
                    "type": "string",
                    "description": (
                        "Optional git repository URL to clone (must use SSH format: git@host:path)"
                    ),
                },
                "workspace_name": {
                    "type": "string",
                    "maxLength": 200,
                    "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_\\-\\.]*$",
                    "description": "Optional workspace folder name (auto-generated if not provided)",
                },
                "timeout": {
                    "type": "integer",
                    "default": 300,
                    "minimum": 1,
                    "maximum": 3600,
                    "description": "Maximum seconds for Claude Code execution (default: 300, max: 3600)",
                },
                "max_turns": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum agentic turns for Claude Code (default: 10, max: 50)",
                },
                "model": {
                    "type": "string",
                    "default": "sonnet",
                    "enum": ["sonnet", "haiku", "opus"],
                    "description": "Claude model to use (default: 'sonnet')",
                },
                "cleanup": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to delete workspace after execution (default: true)",
                },
                "working_dir_base": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Base directory for workspaces (optional)",
                },
                "custom_instructions": {
                    "type": "string",
                    "maxLength": 4000,
                    "description": "Optional custom instructions to prepend to prompt",
                },
            },
            "required": ["prompt"],
        },
        "handler": execute_in_workspace,
    },
]
