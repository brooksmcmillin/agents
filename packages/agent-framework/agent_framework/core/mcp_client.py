"""MCP client connection handler.

This module manages the connection to the MCP server and provides
a clean interface for calling MCP tools.
"""

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Self, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from agent_framework.utils.errors import MCPSessionNotInitializedError

from .config import settings

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP client for connecting to MCP servers.

    This class handles:
    - Establishing connection to MCP server
    - Tool discovery
    - Tool execution
    - Error handling

    Connection modes:
    - persistent=False (default): Reconnects to the MCP subprocess for every
      tool call. This enables hot reload — tool changes take effect immediately
      without restarting the agent. Best for development.
    - persistent=True: Caches the subprocess connection across calls within a
      turn. Call ``end_turn()`` between turns to close the cached connection
      so a fresh subprocess (with any updated tools) is started next turn.
      Call ``disconnect()`` to close the cached connection at any time.
      Best for production where subprocess startup overhead matters.
    """

    def __init__(
        self,
        server_script_path: str = "mcp_server/server.py",
        agent_name: str | None = None,
        stderr_log_file: Path | None = None,
        allowed_tools: list[str] | None = None,
        persistent: bool = False,
    ):
        """
        Initialize MCP client.

        Args:
            server_script_path: Path to the MCP server script
            agent_name: Name of the agent (used for log file naming if stderr_log_file not provided)
            stderr_log_file: Optional explicit path for stderr log file. If not provided and
                agent_name is given, uses settings.get_log_file(agent_name).
            allowed_tools: A list of local tools that are explicitly allowed. If None
                then allow all local tools. This does not affect remote tools at all.
            persistent: If True, cache the MCP subprocess connection across tool calls
                within a turn. Call end_turn() or disconnect() to close the cached
                connection. If False (default), reconnect for every tool call
                (enables hot reload of tools between calls).
        """
        self.server_script_path = server_script_path
        self.session: ClientSession | None = None
        self.available_tools: dict[str, Any] = {}
        self.allowed_tools = allowed_tools
        self.persistent = persistent

        # Determine stderr log file path
        if stderr_log_file:
            self._stderr_log_path = stderr_log_file
        elif agent_name:
            self._stderr_log_path = settings.get_log_file(agent_name)
        else:
            self._stderr_log_path = None

        self._stderr_file: TextIO | None = None

        # Persistent connection state: holds the active stack when persistent=True
        # so the subprocess stays alive between connect() calls.
        self._persistent_exit_stack: contextlib.AsyncExitStack | None = None

        # Lock to prevent concurrent coroutines from each spawning a fresh
        # subprocess when persistent=True and session is None.
        self._persistent_connect_lock: asyncio.Lock = asyncio.Lock()

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the MCP server subprocess.

        Uses sys.executable to ensure we use the same Python interpreter
        (and virtual environment) as the running agent.
        Passes current environment variables to subprocess so it inherits
        settings like MEMORY_BACKEND, DATABASE_URL, etc.
        """
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", self.server_script_path.replace("/", ".").replace(".py", "")],
            env=dict(os.environ),
        )

    def _open_errlog(self) -> TextIO:
        """Open and return the stderr log file, falling back to sys.stderr."""
        if self._stderr_log_path:
            try:
                self._stderr_file = open(  # noqa: SIM115
                    self._stderr_log_path, "a", encoding="utf-8"
                )
                logger.debug(f"MCP server stderr redirected to: {self._stderr_log_path}")
                return self._stderr_file
            except OSError as e:
                logger.warning(f"Failed to open stderr log file {self._stderr_log_path}: {e}")
        return sys.stderr

    def _close_errlog(self) -> None:
        """Close the stderr log file if one was opened."""
        if self._stderr_file:
            with contextlib.suppress(OSError):
                self._stderr_file.close()
            self._stderr_file = None

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[Self, None]:
        """
        Connect to the MCP server using stdio transport.

        This is an async context manager that handles connection lifecycle.

        When ``persistent=False`` (default): spawns a new MCP subprocess on
        every call and tears it down when the context exits.

        When ``persistent=True``: on the first call, spawns the subprocess and
        caches the connection; subsequent calls reuse the cached connection
        without spawning a new process.  The subprocess stays alive until
        ``disconnect()`` or ``end_turn()`` is called explicitly.

        Usage:
            async with client.connect():
                result = await client.call_tool("tool_name", {...})
        """
        if self.persistent:
            async with self._connect_persistent() as client:
                yield client
        else:
            async with self._connect_fresh() as client:
                yield client

    @asynccontextmanager
    async def _connect_fresh(self) -> AsyncGenerator[Self, None]:
        """Connect by spawning a new subprocess each time (non-persistent mode)."""
        server_params = self._build_server_params()
        errlog = self._open_errlog()

        logger.info(f"Connecting to MCP server: {self.server_script_path}")

        try:
            # Connect to server, passing errlog for stderr capture
            async with stdio_client(server_params, errlog=errlog) as (read, write):
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
            self._close_errlog()

    @asynccontextmanager
    async def _connect_persistent(self) -> AsyncGenerator[Self, None]:
        """Reuse cached subprocess connection (persistent mode).

        On the first call, spawns a fresh subprocess and caches it.
        Subsequent calls within the same turn skip the spawn and yield
        the already-connected client.  Callers must call ``end_turn()``
        or ``disconnect()`` to close the subprocess between turns so that
        updated tools are picked up on the next turn.

        The lock only guards the connection-setup phase to prevent concurrent
        coroutines from each spawning a fresh subprocess when session is None.
        The lock is released before yielding so concurrent tool calls can
        proceed in parallel once the connection is established.
        """
        async with self._persistent_connect_lock:
            if self.session is None:
                # No cached connection yet — start one and cache it.
                # Note: if the subprocess crashes while the session is cached,
                # self.session will still be non-None and the stale client will be
                # returned on the next call, causing transport errors.  Transparent
                # reconnection-on-failure is a known limitation deferred to a future
                # improvement (see task #606).
                server_params = self._build_server_params()
                errlog = self._open_errlog()

                logger.info(f"Connecting to MCP server (persistent): {self.server_script_path}")

                # Use an AsyncExitStack to keep both the stdio_client and ClientSession
                # context managers alive beyond this method invocation.
                stack = contextlib.AsyncExitStack()
                try:
                    read, write = await stack.enter_async_context(
                        stdio_client(server_params, errlog=errlog)
                    )
                    session = await stack.enter_async_context(ClientSession(read, write))
                    self.session = session
                    self._persistent_exit_stack = stack

                    await session.initialize()
                    logger.info("MCP persistent session initialized")

                    await self._discover_tools()

                except Exception as e:
                    logger.error(f"Failed to connect to MCP server (persistent): {e}")
                    # Clean up on connection failure
                    self.session = None
                    self._persistent_exit_stack = None
                    with contextlib.suppress(OSError, RuntimeError, asyncio.CancelledError):
                        await stack.aclose()
                    self._close_errlog()
                    raise
            else:
                logger.debug("Reusing cached MCP connection (persistent mode)")

        # Lock released here — concurrent callers can proceed in parallel once
        # the connection is established.
        yield self

    async def disconnect(self) -> None:
        """Close the cached persistent connection, if any.

        Safe to call even when not in persistent mode or when already
        disconnected.  After this call, the next ``connect()`` will spawn
        a fresh subprocess (allowing updated tools to be loaded).
        """
        stack = self._persistent_exit_stack
        if stack is not None:
            self._persistent_exit_stack = None
            self.session = None
            logger.info("Closing persistent MCP connection")
            with contextlib.suppress(OSError, RuntimeError, asyncio.CancelledError):
                await stack.aclose()
            self._close_errlog()
            logger.info("Persistent MCP connection closed")

    async def end_turn(self) -> None:
        """Signal the end of an agent turn.

        In persistent mode, closes the cached subprocess so that the next
        turn starts with a fresh subprocess (enabling hot reload of tools
        between turns).  In non-persistent mode this is a no-op.
        """
        if self.persistent:
            await self.disconnect()

    async def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        if not self.session:
            raise MCPSessionNotInitializedError()

        try:
            # List available tools
            response = await self.session.list_tools()

            # Store tools in a dictionary for easy access
            # If there is an allow list of tools, only load the definitions for those to keep agents limited / context cleaner
            self.available_tools = {
                tool.name: tool
                for tool in response.tools
                if (self.allowed_tools is None or tool.name in self.allowed_tools)
            }

            # Check if any allowed tools were not loaded and warn if so to catch typos
            if self.allowed_tools is not None:
                for tool_name in self.allowed_tools:
                    if tool_name not in self.available_tools:
                        logger.warning(
                            f"'{tool_name}' specified as allowed tool, but it is not available. It may be a typo."
                        )

            logger.info(
                f"Discovered {len(self.available_tools)} tools: {list(self.available_tools.keys())}"
            )

        except Exception as e:
            logger.error(f"Failed to discover tools: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
            raise MCPSessionNotInitializedError()

        if tool_name not in self.available_tools:
            raise ValueError(
                f"Unknown tool: {tool_name}. Available tools: {list(self.available_tools.keys())}"
            )

        logger.info(f"Calling tool: {tool_name} with arguments: {arguments}")

        try:
            # Call the tool
            result = await self.session.call_tool(tool_name, arguments)

            # Extract text content from result
            if result.content and len(result.content) > 0:
                first_content = result.content[0]
                if not isinstance(first_content, TextContent):
                    print(first_content)
                    logger.warning(f"Tool {tool_name} returned non-text content")
                    return {}
                parsed_result = json.loads(first_content.text)

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

    def get_available_tools(self) -> list[str]:
        """
        Get list of available tool names.

        Returns:
            List of tool names
        """
        return list(self.available_tools.keys())

    def get_tool_info(self, tool_name: str) -> dict[str, Any] | None:
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
async def create_mcp_client(
    server_script_path: str = "mcp_server/server.py",
    agent_name: str | None = None,
    stderr_log_file: Path | None = None,
    allowed_tools: list[str] | None = None,
    persistent: bool = False,
):
    """
    Create and connect an MCP client.

    This is a convenience function for simple use cases.

    Usage:
        async with create_mcp_client() as client:
            result = await client.call_tool("tool_name", {...})

    For persistent mode, manage lifecycle explicitly instead:
        client = MCPClient(persistent=True)
        async with client.connect():
            result = await client.call_tool("tool_name", {...})
        await client.end_turn()   # close between turns

    Args:
        server_script_path: Path to the MCP server script
        agent_name: Name of the agent (used for log file naming)
        stderr_log_file: Optional explicit path for stderr log file
        allowed_tools: A list of local tools that are explicitly allowed
        persistent: If True, cache the MCP subprocess connection across calls.
            Note: with this convenience wrapper the connection is NOT automatically
            closed when the context exits — call ``client.disconnect()`` or
            ``client.end_turn()`` explicitly when done with the turn.

    Yields:
        Connected MCPClient instance
    """
    client = MCPClient(
        server_script_path,
        agent_name=agent_name,
        stderr_log_file=stderr_log_file,
        allowed_tools=allowed_tools,
        persistent=persistent,
    )
    async with client.connect():
        yield client
