"""Main agent orchestrator for PR Assistant.

This module implements the agentic loop that:
1. Accepts user requests
2. Calls Claude via Anthropic SDK
3. Executes MCP tools as needed
4. Processes results and provides recommendations
"""

import asyncio
import logging

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


class PRAgent(Agent):
    """
    PR Assistant Agent using Claude and MCP tools.

    This agent orchestrates conversations with the user, leveraging
    Claude's capabilities and MCP tools to provide content strategy advice.
    """
    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        return USER_GREETING_PROMPT

async def main():
    """Main entry point for the agent application."""
    try:
        # Create and start the agent
        agent = PRAgent()
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
    """Run the agent application."""
    asyncio.run(main())
