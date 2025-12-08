"""MCP client connection handler.

This module manages the connection to the MCP server and provides
a clean interface for calling MCP tools.
"""

import logging
import json
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP client for connecting to the PR Agent MCP server.

    This class handles:
    - Establishing connection to MCP server
    - Tool discovery
    - Tool execution
    - Error handling
    """

    def __init__(self, server_script_path: str = "mcp_server/server.py"):
        """
        Initialize MCP client.

        Args:
            server_script_path: Path to the MCP server script
        """
        self.server_script_path = server_script_path
        self.session: Optional[ClientSession] = None
        self.available_tools: Dict[str, Any] = {}

    @asynccontextmanager
    async def connect(self):
        """
        Connect to the MCP server using stdio transport.

        This is an async context manager that handles connection lifecycle.

        Usage:
            async with client.connect():
                result = await client.call_tool("analyze_website", {...})
        """
        # Set up server parameters
        server_params = StdioServerParameters(
            command="python",
            args=["-m", self.server_script_path.replace("/", ".").replace(".py", "")],
            env=None,
        )

        logger.info(f"Connecting to MCP server: {self.server_script_path}")

        try:
            # Connect to server
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    self.session = session

                    # Initialize the session
                    await session.initialize()
                    logger.info("MCP session initialized")

                    # Discover available tools
                    await self._discover_tools()

                    yield self

        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise

        finally:
            self.session = None
            logger.info("MCP session closed")

    async def _discover_tools(self):
        """Discover available tools from the MCP server."""
        if not self.session:
            raise RuntimeError("MCP session not initialized")

        try:
            # List available tools
            response = await self.session.list_tools()

            # Store tools in a dictionary for easy access
            self.available_tools = {tool.name: tool for tool in response.tools}

            logger.info(f"Discovered {len(self.available_tools)} tools: {list(self.available_tools.keys())}")

        except Exception as e:
            logger.error(f"Failed to discover tools: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Dictionary of tool arguments

        Returns:
            Tool result as a dictionary

        Raises:
            ValueError: If tool doesn't exist
            RuntimeError: If session is not initialized
        """
        if not self.session:
            raise RuntimeError("MCP session not initialized. Use 'async with client.connect():'")

        if tool_name not in self.available_tools:
            raise ValueError(
                f"Unknown tool: {tool_name}. "
                f"Available tools: {list(self.available_tools.keys())}"
            )

        logger.info(f"Calling tool: {tool_name} with arguments: {arguments}")

        try:
            # Call the tool
            result = await self.session.call_tool(tool_name, arguments)

            # Extract text content from result
            if result.content and len(result.content) > 0:
                text_content = result.content[0].text
                parsed_result = json.loads(text_content)

                # Check for errors in the result
                if isinstance(parsed_result, dict) and "error" in parsed_result:
                    error_type = parsed_result.get("error")
                    error_msg = parsed_result.get("message", "Unknown error")

                    if error_type == "authentication_required":
                        logger.warning(f"Authentication required for {tool_name}")
                        raise PermissionError(error_msg)
                    else:
                        logger.error(f"Tool error: {error_msg}")
                        raise RuntimeError(f"Tool execution failed: {error_msg}")

                logger.info(f"Tool {tool_name} executed successfully")
                return parsed_result

            else:
                logger.warning(f"Tool {tool_name} returned no content")
                return {}

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tool result: {e}")
            raise RuntimeError(f"Invalid JSON response from tool: {e}")

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            raise

    def get_available_tools(self) -> List[str]:
        """
        Get list of available tool names.

        Returns:
            List of tool names
        """
        return list(self.available_tools.keys())

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool information dictionary or None if not found
        """
        tool = self.available_tools.get(tool_name)
        if not tool:
            return None

        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema,
        }


# Convenience function for simple use cases
@asynccontextmanager
async def create_mcp_client(server_script_path: str = "mcp_server/server.py"):
    """
    Create and connect an MCP client.

    This is a convenience function for simple use cases.

    Usage:
        async with create_mcp_client() as client:
            result = await client.call_tool("analyze_website", {...})

    Args:
        server_script_path: Path to the MCP server script

    Yields:
        Connected MCPClient instance
    """
    client = MCPClient(server_script_path)
    async with client.connect():
        yield client
