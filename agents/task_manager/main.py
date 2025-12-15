"""Main agent orchestrator for Task Manager.

This agent uses a remote MCP server to manage tasks through tools like
get_tasks, create_task, update_task, etc.
"""

import asyncio
import json
import logging
import os

from agent_framework import Agent
from dotenv import load_dotenv

from shared.remote_mcp_client import RemoteMCPClient
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

    Note: This agent extends the base Agent class but overrides MCP connection
    to use RemoteMCPClient for connecting to a remote MCP server via HTTP/SSE.
    """

    def __init__(self, mcp_url: str = "https://mcp.brooksmcmillin.com/mcp"):
        """Initialize the task manager agent.

        Args:
            mcp_url: URL of the remote MCP server
        """
        # Store mcp_url before calling super().__init__()
        self.mcp_url = mcp_url

        # Initialize the base Agent class
        super().__init__()

    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        """Return the greeting message for this agent."""
        return USER_GREETING_PROMPT

    async def _get_mcp_tools(self):
        """Get available tools from the remote MCP server.

        Returns:
            List of tool definitions in Anthropic format
        """
        async with RemoteMCPClient(self.mcp_url) as mcp:
            mcp_tools = await mcp.list_tools()

            # Convert MCP tools to Anthropic format
            tools = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                }
                for tool in mcp_tools
            ]
            return tools

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> dict:
        """Execute a tool via the remote MCP server.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments to pass to the tool

        Returns:
            Tool execution result
        """
        async with RemoteMCPClient(self.mcp_url) as mcp:
            result = await mcp.call_tool(tool_name, tool_args)

            # Handle result - could be string or dict
            if isinstance(result, str):
                try:
                    # Try to parse as JSON
                    result_dict = json.loads(result)
                    return result_dict
                except json.JSONDecodeError:
                    return {"result": result}
            else:
                return result

    async def start(self):
        """Start the interactive agent session with remote MCP connection test."""
        # Test remote MCP connection before starting
        try:
            print("🔌 Connecting to remote MCP server...", flush=True)
            async with RemoteMCPClient(self.mcp_url) as mcp:
                tools = await asyncio.wait_for(mcp.list_tools(), timeout=10.0)
                logger.info(f"Connected to MCP server with {len(tools)} tools")
                print(f"✅ Connected to {self.mcp_url}")
                print(f"✅ Found {len(tools)} tools\n", flush=True)
        except asyncio.TimeoutError:
            print(f"❌ Timeout while connecting to MCP server at {self.mcp_url}")
            print("The connection was established but listing tools timed out.")
            return
        except Exception as e:
            print(f"❌ Failed to connect to MCP server at {self.mcp_url}")
            print(f"Error: {e}")
            print("\nPlease ensure:")
            print("1. The MCP server is running")
            print("2. The URL is correct")
            print("3. The server is accessible")
            return

        # Call the parent class's start method to begin the agent loop
        await super().start()



async def main():
    """Main entry point for the task manager agent."""
    try:
        # Get MCP URL from environment or use default
        mcp_url = os.getenv("MCP_SERVER_URL", "https://mcp.brooksmcmillin.com/mcp")

        # Create and start the agent
        agent = TaskManagerAgent(mcp_url=mcp_url)
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
