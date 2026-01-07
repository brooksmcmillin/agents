"""Main agent orchestrator for Task Manager.

This agent uses a remote MCP server to manage tasks through tools like
get_tasks, create_task, update_task, etc.
"""

import asyncio
import os

from agent_framework import Agent
from dotenv import load_dotenv

from shared import run_agent, setup_logging

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging(__name__)


class TaskManagerAgent(Agent):
    """
    Task Manager Agent using Claude and remote MCP tools.

    This agent connects to a remote MCP server to manage tasks, including
    rescheduling overdue tasks, pre-researching upcoming tasks, and
    prioritizing tasks based on various criteria.
    """

    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        """Return the greeting message for this agent."""
        return USER_GREETING_PROMPT


async def main():
    """Main entry point for the task manager agent."""
    mcp_url = os.getenv("MCP_SERVER_URL", "https://mcp.brooksmcmillin.com/mcp")
    await run_agent(TaskManagerAgent, {"mcp_urls": [mcp_url]})


if __name__ == "__main__":
    """Run the task manager agent."""
    asyncio.run(main())
