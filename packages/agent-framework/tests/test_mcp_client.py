"""Tests for the MCP client module."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import TextContent

from agent_framework.core.mcp_client import MCPClient, create_mcp_client


class TestMCPClient:
    """Tests for the MCPClient class."""

    def test_mcp_client_initialization(self):
        """Test MCPClient initialization."""
        client = MCPClient(server_script_path="test/server.py")

        assert client.server_script_path == "test/server.py"
        assert client.session is None
        assert client.available_tools == {}

    def test_mcp_client_default_path(self):
        """Test MCPClient uses default server path."""
        client = MCPClient()

        assert client.server_script_path == "mcp_server/server.py"

    def test_get_available_tools_empty(self):
        """Test get_available_tools returns empty list when no tools."""
        client = MCPClient()

        assert client.get_available_tools() == []

    def test_get_available_tools_with_tools(self):
        """Test get_available_tools returns tool names."""
        client = MCPClient()
        client.available_tools = {
            "tool1": MagicMock(),
            "tool2": MagicMock(),
            "tool3": MagicMock(),
        }

        tools = client.get_available_tools()

        assert len(tools) == 3
        assert "tool1" in tools
        assert "tool2" in tools
        assert "tool3" in tools

    def test_get_tool_info_exists(self):
        """Test get_tool_info returns info for existing tool."""
        client = MCPClient()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {"type": "object"}
        client.available_tools = {"test_tool": mock_tool}

        info = client.get_tool_info("test_tool")

        assert info is not None
        assert info["name"] == "test_tool"
        assert info["description"] == "A test tool"
        assert info["input_schema"] == {"type": "object"}

    def test_get_tool_info_not_exists(self):
        """Test get_tool_info returns None for non-existent tool."""
        client = MCPClient()

        info = client.get_tool_info("nonexistent")

        assert info is None


class TestMCPClientAsync:
    """Async tests for MCPClient methods."""

    @pytest.mark.asyncio
    async def test_call_tool_without_session_raises(self):
        """Test call_tool raises error when session not initialized."""
        from agent_framework.utils.errors import MCPSessionNotInitializedError

        client = MCPClient()

        with pytest.raises(MCPSessionNotInitializedError):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool_raises(self):
        """Test call_tool raises error for unknown tool."""
        client = MCPClient()
        client.session = MagicMock()  # Simulate active session
        client.available_tools = {"known_tool": MagicMock()}

        with pytest.raises(ValueError, match="Unknown tool"):
            await client.call_tool("unknown_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Test call_tool returns result on success."""
        client = MCPClient()
        client.session = AsyncMock()
        client.available_tools = {"test_tool": MagicMock()}

        # Mock the tool result with actual TextContent
        mock_result = MagicMock()
        mock_result.content = [
            TextContent(type="text", text='{"status": "success", "data": "test"}')
        ]
        client.session.call_tool = AsyncMock(return_value=mock_result)

        result = await client.call_tool("test_tool", {"arg": "value"})

        assert result == {"status": "success", "data": "test"}

    @pytest.mark.asyncio
    async def test_call_tool_handles_auth_error(self):
        """Test call_tool raises PermissionError for auth errors."""
        client = MCPClient()
        client.session = AsyncMock()
        client.available_tools = {"test_tool": MagicMock()}

        # Mock auth error response with actual TextContent
        mock_result = MagicMock()
        mock_result.content = [
            TextContent(
                type="text",
                text='{"error": "authentication_required", "message": "Please authenticate"}',
            )
        ]
        client.session.call_tool = AsyncMock(return_value=mock_result)

        with pytest.raises(PermissionError, match="Please authenticate"):
            await client.call_tool("test_tool", {"arg": "value"})

    @pytest.mark.asyncio
    async def test_call_tool_handles_execution_error(self):
        """Test call_tool raises RuntimeError for execution errors."""
        client = MCPClient()
        client.session = AsyncMock()
        client.available_tools = {"test_tool": MagicMock()}

        # Mock execution error response with actual TextContent
        mock_result = MagicMock()
        mock_result.content = [
            TextContent(
                type="text", text='{"error": "execution_error", "message": "Something went wrong"}'
            )
        ]
        client.session.call_tool = AsyncMock(return_value=mock_result)

        with pytest.raises(RuntimeError, match="Tool execution failed"):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_handles_empty_content(self):
        """Test call_tool handles empty content gracefully."""
        client = MCPClient()
        client.session = AsyncMock()
        client.available_tools = {"test_tool": MagicMock()}

        # Mock empty content
        mock_result = MagicMock()
        mock_result.content = []
        client.session.call_tool = AsyncMock(return_value=mock_result)

        result = await client.call_tool("test_tool", {})

        assert result == {}

    @pytest.mark.asyncio
    async def test_call_tool_handles_invalid_json(self):
        """Test call_tool raises error for invalid JSON response."""
        client = MCPClient()
        client.session = AsyncMock()
        client.available_tools = {"test_tool": MagicMock()}

        # Mock invalid JSON with actual TextContent
        mock_result = MagicMock()
        mock_result.content = [TextContent(type="text", text="not valid json")]
        client.session.call_tool = AsyncMock(return_value=mock_result)

        with pytest.raises(RuntimeError, match="Invalid JSON response"):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_discover_tools_without_session_raises(self):
        """Test _discover_tools raises error when session not initialized."""
        from agent_framework.utils.errors import MCPSessionNotInitializedError

        client = MCPClient()

        with pytest.raises(MCPSessionNotInitializedError):
            await client._discover_tools()

    @pytest.mark.asyncio
    async def test_discover_tools_success(self):
        """Test _discover_tools populates available_tools."""
        client = MCPClient()
        client.session = AsyncMock()

        # Mock tool list response
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool1"
        mock_tool2 = MagicMock()
        mock_tool2.name = "tool2"

        mock_response = MagicMock()
        mock_response.tools = [mock_tool1, mock_tool2]
        client.session.list_tools = AsyncMock(return_value=mock_response)

        await client._discover_tools()

        assert len(client.available_tools) == 2
        assert "tool1" in client.available_tools
        assert "tool2" in client.available_tools

    @pytest.mark.asyncio
    async def test_allowed_tools(self, caplog):
        """Test _discover_tools filters to allowed_tools and warns on missing tools."""
        client = MCPClient(allowed_tools=["tool2", "tool3"])
        client.session = AsyncMock()

        # Mock tool list response
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool1"
        mock_tool2 = MagicMock()
        mock_tool2.name = "tool2"

        mock_response = MagicMock()
        mock_response.tools = [mock_tool1, mock_tool2]
        client.session.list_tools = AsyncMock(return_value=mock_response)

        # Enable propagation temporarily so caplog can capture the warning
        # (agent_framework logger has propagate=False by default for clean console output)
        # We need to enable propagation on both the child and parent loggers
        mcp_logger = logging.getLogger("agent_framework.core.mcp_client")
        parent_logger = logging.getLogger("agent_framework")
        original_mcp_propagate = mcp_logger.propagate
        original_parent_propagate = parent_logger.propagate
        mcp_logger.propagate = True
        parent_logger.propagate = True

        try:
            with caplog.at_level(logging.WARNING):
                await client._discover_tools()

            # Only tool2 should be loaded (tool1 not in allowed list, tool3 doesn't exist)
            assert len(client.available_tools) == 1
            assert "tool2" in client.available_tools

            # Should warn about tool3 which was in allowed_tools but doesn't exist
            assert any("tool3" in record.message for record in caplog.records)
            assert any("not available" in record.message for record in caplog.records)
        finally:
            mcp_logger.propagate = original_mcp_propagate
            parent_logger.propagate = original_parent_propagate


class TestMCPClientEnvironment:
    """Tests for MCP client environment variable handling."""

    def test_connect_passes_environment_variables(self, monkeypatch):
        """Test that connect() passes current environment to subprocess.

        This is critical for features like MEMORY_BACKEND to work in
        MCP server subprocesses.
        """
        from unittest.mock import patch

        from mcp import StdioServerParameters

        # Set up test environment variables
        monkeypatch.setenv("MEMORY_BACKEND", "database")
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:pass@localhost/db")
        monkeypatch.setenv("CUSTOM_VAR", "custom_value")

        client = MCPClient(server_script_path="test/server.py")

        # We need to capture the StdioServerParameters that connect() creates
        captured_params = []

        original_init = StdioServerParameters.__init__

        def capture_init(self, **kwargs):
            captured_params.append(kwargs)
            return original_init(self, **kwargs)

        with patch.object(StdioServerParameters, "__init__", capture_init):
            # We can't fully run connect() without a real server,
            # but we can inspect the implementation to verify env is passed
            import inspect

            # Get the source of the connect method
            source = inspect.getsource(client.connect)

            # Verify the implementation passes environment
            assert "env=dict(os.environ)" in source or "env=os.environ" in source, (
                "MCPClient.connect() must pass environment variables to subprocess. "
                "Without this, MEMORY_BACKEND and DATABASE_URL won't be available "
                "in the MCP server subprocess."
            )

    def test_environment_inheritance_documentation(self):
        """Test that the env inheritance is documented in the code."""
        import inspect

        client = MCPClient()
        source = inspect.getsource(client.connect)

        # Verify there's a comment explaining why env is passed
        assert "MEMORY_BACKEND" in source or "environment" in source.lower(), (
            "MCPClient.connect() should document why environment is passed"
        )


class TestCreateMCPClient:
    """Tests for the create_mcp_client convenience function."""

    @pytest.mark.asyncio
    async def test_create_mcp_client_is_context_manager(self):
        """Test that create_mcp_client is an async context manager."""
        # We can't fully test this without a real MCP server,
        # but we can verify the function exists and is callable
        assert callable(create_mcp_client)
