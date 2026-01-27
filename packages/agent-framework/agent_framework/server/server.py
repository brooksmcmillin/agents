"""Base MCP server implementation.

This module provides utilities for creating MCP servers with tool registration.
"""

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from agent_framework.tools import ALL_TOOL_SCHEMAS

logger = logging.getLogger(__name__)


class MCPServerBase:
    """
    Base class for MCP servers with tool registration.

    This provides a clean interface for building MCP servers with automatic
    tool registration and error handling.
    """

    def __init__(self, name: str, setup_defaults: bool = True):
        """
        Initialize MCP server.

        Args:
            name: Server name
            setup_defaults: Whether or not to set up default tools
        """
        self.app = Server(name)
        self.tools: dict[str, dict[str, Any]] = {}
        self._tool_handlers: dict[str, Callable] = {}

        if setup_defaults:
            self.register_tools_from_schemas(ALL_TOOL_SCHEMAS)

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable,
    ):
        """
        Register a tool with the server.

        Args:
            name: Tool name
            description: Tool description
            input_schema: JSON schema for tool inputs
            handler: Async function to handle tool calls
        """
        self.tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._tool_handlers[name] = handler
        logger.info(f"Registered tool: {name}")

    def register_tools_from_schemas(self, schemas: list[dict[str, Any]]) -> None:
        """
        Register multiple tools from a list of schema dicts.

        Each schema dict must have ``name``, ``description``, ``input_schema``,
        and ``handler`` keys (the same shape as the ``TOOL_SCHEMAS`` lists
        exported by each tool module).

        Args:
            schemas: List of tool schema dictionaries
        """
        for schema in schemas:
            self.register_tool(
                name=schema["name"],
                description=schema["description"],
                input_schema=schema["input_schema"],
                handler=schema["handler"],
            )

    def setup_handlers(self) -> None:
        """Set up MCP handlers for tool listing and calling."""

        @self.app.list_tools()
        async def list_tools() -> list[Tool]:
            """List available MCP tools."""
            logger.info("Listing available tools")
            return [
                Tool(
                    name=tool_info["name"],
                    description=tool_info["description"],
                    inputSchema=tool_info["input_schema"],
                )
                for tool_info in self.tools.values()
            ]

        @self.app.call_tool()
        async def call_tool(
            name: str, arguments: Any
        ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
            """Execute a tool with the given arguments."""
            logger.info(f"Calling tool: {name} with arguments: {arguments}")

            try:
                # Check if tool exists
                if name not in self._tool_handlers:
                    raise ValueError(f"Unknown tool: {name}")

                # Call the handler
                handler = self._tool_handlers[name]
                result = await handler(**arguments)

                # Return as TextContent with JSON
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]

            except ValueError as e:
                logger.error(f"Validation error in {name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "validation_error",
                                "message": str(e),
                                "tool": name,
                            }
                        ),
                    )
                ]

            except PermissionError as e:
                logger.error(f"Auth error in {name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "authentication_required",
                                "message": str(e),
                                "tool": name,
                                "action_required": "Please complete OAuth authentication flow",
                            }
                        ),
                    )
                ]

            except Exception as e:
                logger.exception(f"Error executing tool {name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "execution_error",
                                "message": str(e),
                                "tool": name,
                            }
                        ),
                    )
                ]

    async def run(self) -> None:
        """Run the MCP server."""
        logger.info(f"Starting MCP Server: {self.app.name}")

        # Run the server using stdio transport
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server running on stdio")
            await self.app.run(
                read_stream,
                write_stream,
                self.app.create_initialization_options(),
            )


def create_mcp_server(name: str) -> MCPServerBase:
    """
    Create a new MCP server.

    This is a convenience function for creating servers.

    Args:
        name: Server name

    Returns:
        MCPServerBase instance

    Example:
        ```python
        server = create_mcp_server("my-agent")

        server.register_tool(
            name="my_tool",
            description="Does something useful",
            input_schema={
                "type": "object",
                "properties": {
                    "param": {"type": "string"}
                },
                "required": ["param"]
            },
            handler=my_tool_handler
        )

        server.setup_handlers()
        await server.run()
        ```
    """
    return MCPServerBase(name)
