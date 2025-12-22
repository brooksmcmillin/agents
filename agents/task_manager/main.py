"""Main agent orchestrator for Task Manager.

This agent uses a remote MCP server to manage tasks through tools like
get_tasks, create_task, update_task, etc.
"""

import asyncio
import logging
import os

from agent_framework import Agent
from dotenv import load_dotenv

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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
    try:
        # Get MCP URL from environment or use default
        mcp_url = os.getenv("MCP_SERVER_URL", "https://mcp.brooksmcmillin.com/mcp")

        # Create and start the agent
        agent = TaskManagerAgent(mcp_urls=[mcp_url])
        await agent.start()

    except ValueError as e:
        print(f"\nConfiguration error: {e}")
        print("\nPlease ensure:")
        print("1. You have a .env file with ANTHROPIC_API_KEY set")
        print("2. The API key is valid")
        return

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        print(f"\nFatal error: {e}")
        return


if __name__ == "__main__":
    """Run the task manager agent."""
    asyncio.run(main())
