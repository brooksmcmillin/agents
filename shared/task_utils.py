"""Task parsing and formatting utilities.

This module provides common utilities for working with task data across agents
and scripts, including parsing task results from MCP tools and formatting
priority values.
"""

import json


def parse_task_result(result: str | dict) -> list[dict]:
    """Parse MCP tool result into task list.

    Args:
        result: JSON string or dict from MCP tool call

    Returns:
        List of task dictionaries
    """
    data = json.loads(result) if isinstance(result, str) else result
    return data.get("tasks", [])


def parse_priority(priority_value: str | int | None) -> int:
    """Parse priority value from various formats to integer.

    Handles priority values that may come as integers, numeric strings,
    or text descriptions like "urgent" or "low". Provides sensible
    defaults and normalization to a 1-10 scale.

    Args:
        priority_value: Priority as int, numeric string, or text like "urgent"

    Returns:
        Integer priority 1-10 (defaults to 5 if can't parse)

    Examples:
        >>> parse_priority(9)
        9
        >>> parse_priority("7")
        7
        >>> parse_priority("urgent")
        9
        >>> parse_priority("low")
        2
        >>> parse_priority(None)
        5
    """
    if priority_value is None:
        return 5

    # If already an int, return it
    if isinstance(priority_value, int):
        return priority_value

    # Try to convert string to int
    try:
        return int(priority_value)
    except (ValueError, TypeError):
        pass

    # Handle text priorities
    text_priority = str(priority_value).lower()
    if text_priority in ("urgent", "high", "critical"):
        return 9
    elif text_priority in ("medium", "normal"):
        return 5
    elif text_priority in ("low",):
        return 2

    return 5  # Default


def format_priority_emoji(priority: int) -> str:
    """Get emoji representation for priority level.

    Args:
        priority: Priority value 1-10

    Returns:
        Emoji string for Slack/chat formatting

    Examples:
        >>> format_priority_emoji(9)
        ':exclamation:'
        >>> format_priority_emoji(5)
        ':small_orange_diamond:'
    """
    return ":exclamation:" if priority >= 8 else ":small_orange_diamond:"
