"""Remote MCP client using HTTP/SSE transport.

This client connects to a remote MCP server over HTTP with Server-Sent Events,
allowing agents to use MCP tools hosted on a different machine or service.
"""

import logging
from typing import Any
import httpx
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)


class RemoteMCPClient:
    """Client for connecting to remote MCP servers via HTTP/SSE.

    Usage:
        client = RemoteMCPClient("http://localhost:8000")
        async with client.connect():
            tools = await client.list_tools()
            result = await client.call_tool("tool_name", {"arg": "value"})
    """

    def __init__(self, base_url: str):
        """Initialize remote MCP client.

        Args:
            base_url: Base URL of the remote MCP server (e.g., "http://localhost:8000")
        """
        self.base_url = base_url.rstrip("/")
        self.sse_url = f"{self.base_url}/sse"
        self._session = None
        self._read_stream = None
        self._write_stream = None

    async def connect(self):
        """Connect to the remote MCP server."""
        try:
            # Create SSE client connection
            self._read_stream, self._write_stream = await sse_client(self.sse_url)

            # Initialize session
            from mcp import ClientSession
            self._session = ClientSession(self._read_stream, self._write_stream)

            # Perform handshake
            await self._session.initialize()

            logger.info(f"Connected to remote MCP server at {self.base_url}")
            return self

        except Exception as e:
            logger.error(f"Failed to connect to remote MCP server: {e}")
            raise

    async def disconnect(self):
        """Disconnect from the remote MCP server."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error disconnecting from MCP server: {e}")
            finally:
                self._session = None
                self._read_stream = None
                self._write_stream = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the remote server.

        Returns:
            List of tool definitions with name, description, and input schema
        """
        if not self._session:
            raise RuntimeError("Not connected. Use 'async with client.connect()' first.")

        response = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the remote server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if not self._session:
            raise RuntimeError("Not connected. Use 'async with client.connect()' first.")

        result = await self._session.call_tool(name, arguments)

        # Extract content from result
        if hasattr(result, "content") and result.content:
            # Return first content item (usually text or JSON)
            first_content = result.content[0]
            if hasattr(first_content, "text"):
                return first_content.text
            elif hasattr(first_content, "data"):
                return first_content.data

        return result

    async def health_check(self) -> bool:
        """Check if the remote server is healthy.

        Returns:
            True if server is healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/health", timeout=5.0)
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False
