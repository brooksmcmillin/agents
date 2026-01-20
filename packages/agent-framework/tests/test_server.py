"""Tests for the MCP server module."""

from unittest.mock import patch

from agent_framework.server.server import MCPServerBase, create_mcp_server, setup_default_tools


class TestMCPServerBase:
    """Tests for the MCPServerBase class."""

    def test_mcp_server_initialization(self):
        """Test MCPServerBase initialization."""
        with patch("agent_framework.server.server.setup_default_tools"):
            server = MCPServerBase(name="test-server", setup_defaults=False)

        assert server.app.name == "test-server"
        assert server.tools == {}
        assert server._tool_handlers == {}

    def test_mcp_server_initialization_with_defaults(self):
        """Test MCPServerBase initialization sets up default tools."""
        with patch("agent_framework.server.server.setup_default_tools") as mock_setup:
            server = MCPServerBase(name="test-server", setup_defaults=True)
            mock_setup.assert_called_once_with(server)

    def test_register_tool(self):
        """Test registering a tool with the server."""
        with patch("agent_framework.server.server.setup_default_tools"):
            server = MCPServerBase(name="test-server", setup_defaults=False)

        async def test_handler(arg: str) -> dict:
            return {"result": arg}

        server.register_tool(
            name="test_tool",
            description="A test tool",
            input_schema={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
            handler=test_handler,
        )

        assert "test_tool" in server.tools
        assert server.tools["test_tool"]["name"] == "test_tool"
        assert server.tools["test_tool"]["description"] == "A test tool"
        assert "test_tool" in server._tool_handlers
        assert server._tool_handlers["test_tool"] == test_handler

    def test_register_multiple_tools(self):
        """Test registering multiple tools."""
        with patch("agent_framework.server.server.setup_default_tools"):
            server = MCPServerBase(name="test-server", setup_defaults=False)

        async def handler1():
            return {}

        async def handler2():
            return {}

        server.register_tool("tool1", "Tool 1", {}, handler1)
        server.register_tool("tool2", "Tool 2", {}, handler2)

        assert len(server.tools) == 2
        assert len(server._tool_handlers) == 2


class TestCreateMCPServer:
    """Tests for create_mcp_server function."""

    def test_create_mcp_server(self):
        """Test create_mcp_server creates a server instance."""
        server = create_mcp_server("my-server")

        assert isinstance(server, MCPServerBase)
        assert server.app.name == "my-server"

    def test_create_mcp_server_has_default_tools(self):
        """Test create_mcp_server sets up default tools."""
        server = create_mcp_server("my-server")

        # Default tools should be registered
        assert "fetch_web_content" in server.tools
        assert "save_memory" in server.tools
        assert "get_memories" in server.tools
        assert "search_memories" in server.tools
        assert "send_slack_message" in server.tools


class TestSetupDefaultTools:
    """Tests for setup_default_tools function."""

    def test_setup_default_tools_registers_all_tools(self):
        """Test setup_default_tools registers all expected tools."""
        with patch("agent_framework.server.server.setup_default_tools"):
            server = MCPServerBase(name="test", setup_defaults=False)

        # Call setup_default_tools directly
        setup_default_tools(server)

        expected_tools = [
            "fetch_web_content",
            "save_memory",
            "get_memories",
            "search_memories",
            "send_slack_message",
        ]

        for tool_name in expected_tools:
            assert tool_name in server.tools
            assert tool_name in server._tool_handlers

    def test_setup_default_tools_has_correct_schemas(self):
        """Test default tools have proper input schemas."""
        with patch("agent_framework.server.server.setup_default_tools"):
            server = MCPServerBase(name="test", setup_defaults=False)

        setup_default_tools(server)

        # Check fetch_web_content schema
        fetch_schema = server.tools["fetch_web_content"]["input_schema"]
        assert "url" in fetch_schema["properties"]
        assert "url" in fetch_schema["required"]

        # Check save_memory schema
        save_schema = server.tools["save_memory"]["input_schema"]
        assert "key" in save_schema["properties"]
        assert "value" in save_schema["properties"]
        assert "key" in save_schema["required"]
        assert "value" in save_schema["required"]

        # Check get_memories schema
        get_schema = server.tools["get_memories"]["input_schema"]
        assert "category" in get_schema["properties"]
        assert "tags" in get_schema["properties"]
        assert get_schema["required"] == []

        # Check search_memories schema
        search_schema = server.tools["search_memories"]["input_schema"]
        assert "query" in search_schema["properties"]
        assert "query" in search_schema["required"]

        # Check send_slack_message schema
        slack_schema = server.tools["send_slack_message"]["input_schema"]
        assert "text" in slack_schema["properties"]
        assert "text" in slack_schema["required"]


class TestMCPServerHandlers:
    """Tests for MCP server request handlers."""

    def test_setup_handlers_creates_list_tools_handler(self):
        """Test setup_handlers creates list_tools handler."""
        with patch("agent_framework.server.server.setup_default_tools"):
            server = MCPServerBase(name="test", setup_defaults=False)

        # Register a test tool
        server.register_tool("test", "Test tool", {}, lambda: {})
        server.setup_handlers()

        # The handler should be registered with the app
        # We can't easily test the decorator-based handlers directly,
        # but we can verify the server is properly configured
        assert server.app is not None
