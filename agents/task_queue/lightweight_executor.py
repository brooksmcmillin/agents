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


async def execute_lightweight(
    task: dict,
    call_tool: ToolCaller,
    list_tools: ToolLister,
    model: str = "sonnet",
    api_key: str | None = None,
    max_turns: int = 15,
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

            if not tool_use_blocks:
                # No tool calls — we're done
                logger.info(f"Lightweight execution completed in {turns_used} turns")
                return LightweightResult(success=True, output=last_text, turns_used=turns_used)

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

        # Exhausted max_turns
        logger.warning(f"Lightweight execution hit max_turns ({max_turns})")
        return LightweightResult(
            success=bool(last_text),
            output=last_text or "Max turns reached without completion.",
            turns_used=turns_used,
        )

    except Exception as e:
        logger.error(f"Lightweight execution failed: {e}")
        return LightweightResult(
            success=False, output=last_text, turns_used=turns_used, error=str(e)
        )
    finally:
        await client.close()
