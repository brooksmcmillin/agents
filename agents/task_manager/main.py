"""Task Manager agent.

Connects to a remote MCP server to manage tasks, reschedule overdue items,
and prioritize work.
"""

from shared import (
    CLAUDE_CODE_TOOLS,
    COMMUNICATION_TOOLS,
    CONTENT_TOOLS,
    FASTMAIL_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

TaskManagerAgent = create_simple_agent(
    name="TaskManagerAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(
        CONTENT_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS + CLAUDE_CODE_TOOLS + FASTMAIL_TOOLS
    ),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent tasks")
    sys.exit(1)
