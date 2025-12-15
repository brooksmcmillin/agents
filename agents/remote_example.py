"""Example of using a remote MCP server with an agent.

This demonstrates how to connect to a remote MCP server instead of
using a local stdio connection.

Usage:
    # Terminal 1: Start the remote MCP server
    uv run python -m mcp_server.server_http

    # Terminal 2: Run this example
    uv run python agents/remote_example.py
"""

import asyncio
import logging
from shared.remote_mcp_client import RemoteMCPClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Demonstrate remote MCP connection."""
    # Connect to remote MCP server
    client = RemoteMCPClient("http://localhost:8000")

    # Check health first
    is_healthy = await client.health_check()
    logger.info(f"Server health check: {'✓ Healthy' if is_healthy else '✗ Unhealthy'}")

    if not is_healthy:
        logger.error("Remote MCP server is not accessible!")
        logger.info("Make sure to run: uv run python -m mcp_server.server_http")
        return

    # Connect and use tools
    async with client:
        # List available tools
        logger.info("\nListing available tools...")
        tools = await client.list_tools()
        for tool in tools:
            logger.info(f"  - {tool['name']}: {tool['description']}")

        # Test a tool call
        logger.info("\nTesting analyze_website tool...")
        result = await client.call_tool(
            "analyze_website",
            {"url": "https://anthropic.com", "analysis_type": "tone"},
        )
        logger.info(f"Result: {result}")

        # Test memory tools
        logger.info("\nTesting memory tools...")
        await client.call_tool(
            "save_memory",
            {
                "key": "test_remote_connection",
                "value": "Successfully connected to remote MCP server!",
                "category": "fact",
                "tags": ["test", "remote"],
                "importance": 8,
            },
        )
        logger.info("✓ Memory saved")

        memories = await client.call_tool("get_memories", {})
        logger.info(f"✓ Retrieved {len(str(memories))} bytes of memories")

    logger.info("\n✓ Remote MCP demo completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
