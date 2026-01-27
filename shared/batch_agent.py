"""BatchAgent base class for non-interactive, script-style agents.

BatchAgent provides the same remote MCP tool-calling infrastructure as the
interactive Agent, but designed for scripts that run once and exit (e.g.,
cron jobs, CI pipelines, notification scripts).

Usage::

    class MyNotifier(BatchAgent):
        async def execute(self) -> None:
            result = await self.call_tool("get_tasks", {"status": "overdue"})
            # ... process results ...

    async def main():
        agent = MyNotifier(mcp_url="https://mcp.example.com/mcp")
        await agent.run()
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from agent_framework.core.remote_mcp_client import RemoteMCPClient

from .auth_utils import get_valid_token_for_mcp
from .constants import DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL
from .logging_config import setup_logging

logger = logging.getLogger(__name__)


class BatchAgent(ABC):
    """Base class for non-interactive agents that connect to a remote MCP server.

    Handles authentication, MCP connection lifecycle, and tool calling so
    subclasses can focus on business logic in ``execute()``.
    """

    def __init__(
        self,
        mcp_url: str | None = None,
        auth_token: str | None = None,
    ):
        """Initialize the batch agent.

        Args:
            mcp_url: Remote MCP server URL. Defaults to MCP_SERVER_URL env
                var or DEFAULT_MCP_SERVER_URL.
            auth_token: Bearer token for MCP auth. If None, token is loaded
                from shared storage via ``get_valid_token_for_mcp``.
        """
        self.mcp_url = mcp_url or os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)
        self._auth_token = auth_token
        self._client: RemoteMCPClient | None = None

        # Set up logging
        setup_logging(self.get_name())

    def get_name(self) -> str:
        """Return agent name for logging. Defaults to class name."""
        return self.__class__.__name__

    async def _ensure_token(self) -> str:
        """Get or refresh the auth token.

        Returns:
            Valid access token string.

        Raises:
            RuntimeError: If no token is available.
        """
        if self._auth_token:
            return self._auth_token

        token = await get_valid_token_for_mcp(self.mcp_url)
        if not token:
            raise RuntimeError(
                "No valid authentication token found.\n"
                "Run an interactive agent first to authenticate:\n"
                "  uv run python -m agents.task_manager.main"
            )
        self._auth_token = token
        return token

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool on the connected remote MCP server.

        Args:
            name: Tool name.
            arguments: Tool arguments dict.

        Returns:
            Tool result (typically a dict).

        Raises:
            RuntimeError: If not connected (call within ``execute()``).
        """
        if self._client is None:
            raise RuntimeError("call_tool() can only be used inside execute()")
        return await self._client.call_tool(name, arguments or {})

    @abstractmethod
    async def execute(self) -> None:
        """Run the batch job logic.

        Subclasses implement this method. ``self.call_tool()`` is available
        for making MCP tool calls during execution.
        """

    async def run(self) -> None:
        """Authenticate, connect to MCP, and run ``execute()``."""
        token = await self._ensure_token()

        logger.info(f"Connecting to MCP server at {self.mcp_url}...")
        async with RemoteMCPClient(
            self.mcp_url, auth_token=token, enable_oauth=False
        ) as client:
            self._client = client
            logger.info("Connected successfully")
            try:
                await self.execute()
            finally:
                self._client = None
