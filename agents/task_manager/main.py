"""Main agent orchestrator for Task Manager.

This agent uses a remote MCP server to manage tasks through tools like
get_tasks, create_task, update_task, etc.
"""

import asyncio
import os

from agent_framework import Agent
from typing import Any
from shared import (
    DEFAULT_MCP_SERVER_URL,
    ENV_MCP_SERVER_URL,
    run_agent,
    setup_logging,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Configure logging
logger = setup_logging(__name__)


class TaskManagerAgent(Agent):
    """
    Task Manager Agent using Claude and remote MCP tools.

    This agent connects to a remote MCP server to manage tasks, including
    rescheduling overdue tasks, pre-researching upcoming tasks, and
    prioritizing tasks based on various criteria.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            allowed_tools=[
                "fetch_web_content",
                "get_memories",
                "get_social_media_stats",
                "save_memory",
                "search_memories",
                "send_slack_message",
                "suggest_content_topics",
            ],
            **kwargs,
        )

    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        """Return the greeting message for this agent."""
        return USER_GREETING_PROMPT


async def main():
    """Start the Task Manager agent.

    Connects to remote MCP server at MCP_SERVER_URL for task management.
    Uses OAuth device flow for authentication.
    Requires ANTHROPIC_API_KEY in environment.
    """
    mcp_url = os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)
    await run_agent(TaskManagerAgent, {"mcp_urls": [mcp_url]})


if __name__ == "__main__":
    """Run the task manager agent."""
    asyncio.run(main())
