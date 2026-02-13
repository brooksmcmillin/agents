"""Task Manager agent.

Connects to a remote MCP server to manage tasks, reschedule overdue items,
and prioritize work.
"""

from shared import (
    COMMUNICATION_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

TaskManagerAgent = create_simple_agent(
    name="TaskManagerAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(
        ["fetch_web_content", "get_social_media_stats", "suggest_content_topics"]
        + MEMORY_TOOLS
        + COMMUNICATION_TOOLS
    ),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent tasks")
    sys.exit(1)
