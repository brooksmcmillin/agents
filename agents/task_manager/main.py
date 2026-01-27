"""Task Manager agent.

Connects to a remote MCP server to manage tasks, reschedule overdue items,
and prioritize work.
"""

import asyncio
import os

from shared import (
    COMMUNICATION_TOOLS,
    DEFAULT_MCP_SERVER_URL,
    ENV_MCP_SERVER_URL,
    MEMORY_TOOLS,
    create_simple_agent,
    run_agent,
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


async def main():
    """Start the Task Manager agent.

    Connects to remote MCP server at MCP_SERVER_URL for task management.
    """
    mcp_url = os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)
    await run_agent(TaskManagerAgent, {"mcp_urls": [mcp_url]})


if __name__ == "__main__":
    asyncio.run(main())
