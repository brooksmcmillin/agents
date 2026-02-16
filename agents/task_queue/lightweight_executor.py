"""Lightweight executor for non-code tasks.

Runs an agentic loop using direct Claude API calls with MCP tools,
bypassing the orchestrator's git workspace and code review gates.
Suitable for research, email, document, review, and other non-code tasks.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlock, ToolParam, ToolResultBlockParam, ToolUseBlock

from .models import resolve_model

logger = logging.getLogger(__name__)

# Type aliases matching pre_research.py conventions
ToolCaller = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]
ToolLister = Callable[[], Coroutine[Any, Any, list[dict[str, Any]]]]

# Max characters of agent output to include in the completion verification prompt.
# This is deliberately larger than COMMENT_MAX_LENGTH in runner.py — it feeds a
# Haiku call that evaluates whether the agent succeeded, not a task comment.
VERIFY_OUTPUT_LIMIT = 4000

LIGHTWEIGHT_SYSTEM_PROMPT = """\
You are a task execution agent. Complete the assigned task using the available \
MCP tools. You have access to tools for web search, email, task management, \
file operations, and more.

Rules:
- Use the available tools to complete the task
- Report results clearly and concisely
- Do NOT attempt code changes — code tasks are handled by a separate system
- If you cannot complete the task with available tools, explain what's missing
- When done, provide a clear summary of what was accomplished
"""

COMPLETION_CHECK_PROMPT = """\
You are evaluating whether a task execution agent successfully completed its \
assigned task. Read the task description and the agent's final output, then \
determine if the task was actually completed.

Respond with exactly one of:
- COMPLETED — the agent accomplished what the task asked for
- FAILED — the agent could not complete the task, hit errors, or explicitly \
said it couldn't do it

Just the single word, nothing else."""


@dataclass
class LightweightResult:
    """Result from a lightweight task execution."""

    success: bool
    output: str
    turns_used: int
    error: str | None = None


def _tools_to_api_format(mcp_tools: list[dict[str, Any]]) -> list[ToolParam]:
    """Convert MCP tool schemas to Claude API tool format."""
    return [
        ToolParam(
            name=tool["name"],
            description=tool.get("description", ""),
            input_schema=tool.get("input_schema", {"type": "object"}),
        )
        for tool in mcp_tools
    ]


def _extract_text(content: list[Any]) -> str:
    """Extract text content from Claude API response content blocks."""
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextBlock):
            parts.append(block.text)
    return "\n".join(parts)


async def _verify_completion(
    client: AsyncAnthropic,
    task_title: str,
    task_description: str,
    agent_output: str,
) -> bool:
    """Ask a fast model whether the agent actually completed the task.

    Returns True if completed, False if the output indicates failure or
    verification itself fails.
    """
    # Include beginning and end of output so the verifier sees the conclusion
    # even for long outputs where the failure message is near the end.
    if len(agent_output) > VERIFY_OUTPUT_LIMIT:
        half = VERIFY_OUTPUT_LIMIT // 2
        output_excerpt = f"{agent_output[:half]}\n\n[...truncated...]\n\n{agent_output[-half:]}"
    else:
        output_excerpt = agent_output

    user_msg = (
        f"Task: {task_title}\n"
        f"Description: {task_description or '(none)'}\n\n"
        f"Agent output:\n{output_excerpt}"
    )
    try:
        response = await client.messages.create(
            model=resolve_model("haiku"),
            max_tokens=64,
            system=COMPLETION_CHECK_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        verdict = _extract_text(response.content).strip().upper()
        logger.info(f"Completion check verdict: {verdict}")
        return verdict.startswith("COMPLETED")
    except Exception as e:
        logger.warning(f"Completion check failed, defaulting to not completed: {e}")
        return False


async def execute_lightweight(
    task: dict,
    call_tool: ToolCaller,
    list_tools: ToolLister,
    model: str = "sonnet",
    api_key: str | None = None,
    max_turns: int = 15,
    on_progress: Callable[[int, list[str]], None] | None = None,
) -> LightweightResult:
    """Execute a non-code task using direct Claude API calls with MCP tools.

    Runs an agentic loop: Claude decides which tools to call, we execute
    them via MCP, feed results back, and repeat until done or max_turns.

    Args:
        task: Task dict from MCP (with title, description, etc.).
        call_tool: Async function to call MCP tools.
        list_tools: Async function to list available MCP tool schemas.
        model: Claude model short name or full ID.
        api_key: Anthropic API key (falls back to env var).
        max_turns: Maximum agentic loop iterations.
        on_progress: Optional callback(turn_number, tool_names) called each turn.

    Returns:
        LightweightResult with success status and output.
    """
    task_title = task.get("title", "Untitled")
    task_description = task.get("description", "")
    task_id = task.get("id", "unknown")

    logger.info(f"Starting lightweight execution for {task_id}: {task_title}")

    # Get available tools
    try:
        mcp_tools = await list_tools()
        api_tools = _tools_to_api_format(mcp_tools)
    except Exception as e:
        logger.error(f"Failed to list tools: {e}")
        return LightweightResult(
            success=False, output="", turns_used=0, error=f"Failed to list tools: {e}"
        )

    # Build initial user message
    user_message = f"Task: {task_title}\n"
    if task_description:
        user_message += f"\nDescription:\n{task_description}\n"
    tags = task.get("tags")
    if tags:
        user_message += f"\nTags: {', '.join(tags)}\n"
    category = task.get("category")
    if category:
        user_message += f"\nCategory: {category}\n"
    user_message += "\nPlease complete this task using the available tools."

    messages: list[MessageParam] = [{"role": "user", "content": user_message}]

    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    turns_used = 0
    last_text = ""

    try:
        for turn in range(max_turns):
            turns_used = turn + 1

            create_kwargs: dict[str, Any] = {
                "model": resolve_model(model),
                "max_tokens": 4096,
                "system": LIGHTWEIGHT_SYSTEM_PROMPT,
                "messages": messages,
            }
            if api_tools:
                create_kwargs["tools"] = api_tools
            response = await client.messages.create(**create_kwargs)

            # Extract any text from this response
            text = _extract_text(response.content)
            if text:
                last_text = text

            # Check if there are tool use blocks
            tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]

            # Report progress
            if on_progress:
                tool_names = [b.name for b in tool_use_blocks]
                try:
                    on_progress(turns_used, tool_names)
                except Exception:  # nosec B110
                    pass  # Progress callbacks must never disrupt execution

            if not tool_use_blocks:
                # No tool calls — agent is done. Verify it actually completed.
                completed = await _verify_completion(
                    client, task_title, task_description, last_text
                )
                if completed:
                    logger.info(f"Lightweight execution completed in {turns_used} turns")
                    return LightweightResult(success=True, output=last_text, turns_used=turns_used)
                else:
                    logger.warning(f"Lightweight execution for {task_id} did not complete the task")
                    return LightweightResult(
                        success=False,
                        output=last_text,
                        turns_used=turns_used,
                        error="Agent did not complete the task",
                    )

            # Append the assistant message
            messages.append({"role": "assistant", "content": response.content})  # type: ignore[arg-type]

            # Execute each tool call and collect results
            tool_results: list[ToolResultBlockParam] = []
            for tool_block in tool_use_blocks:
                tool_name = tool_block.name
                tool_input = tool_block.input if isinstance(tool_block.input, dict) else {}

                logger.debug(f"Calling tool: {tool_name}")
                try:
                    result = await call_tool(tool_name, tool_input)
                    # Normalize result to string
                    if isinstance(result, (dict, list)):
                        result_str = json.dumps(result, default=str)
                    else:
                        result_str = str(result)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": result_str,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Tool {tool_name} failed: {e}")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": f"Error: {e}",
                            "is_error": True,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})

        # Exhausted max_turns — verify what we have
        logger.warning(f"Lightweight execution hit max_turns ({max_turns})")
        if last_text:
            completed = await _verify_completion(client, task_title, task_description, last_text)
            return LightweightResult(
                success=completed,
                output=last_text,
                turns_used=turns_used,
                error=None if completed else "Agent did not complete the task within max turns",
            )
        return LightweightResult(
            success=False,
            output="Max turns reached without completion.",
            turns_used=turns_used,
            error="Max turns reached without output",
        )

    except Exception as e:
        logger.error(f"Lightweight execution failed: {e}")
        return LightweightResult(
            success=False, output=last_text, turns_used=turns_used, error=str(e)
        )
    finally:
        await client.close()
