"""Unit tests for MCP server tool registration and initialization.

Tests cover:
- MCPServerBase initialization and tool registration
- create_mcp_server factory function
- Tool listing and calling handlers
- Error handling in tool execution
- mcp_server.server module initialization
"""

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_framework.server.server import MCPServerBase, create_mcp_server

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tool_schema(
    name: str = "test_tool",
    description: str = "A test tool",
    input_schema: dict[str, Any] | None = None,
    handler: Callable | None = None,
) -> dict[str, Any]:
    """Build a minimal tool schema dict."""
    if input_schema is None:
        input_schema = {"type": "object", "properties": {}, "required": []}
    if handler is None:

        async def default_handler(**kwargs: Any) -> dict[str, Any]:
            return {"result": "ok"}

        handler = default_handler
    return {
        "name": name,
        "description": description,
        "input_schema": input_schema,
        "handler": handler,
    }


def _capture_call_tool_fn(server: MCPServerBase) -> list[Callable]:
    """
    Capture the inner call_tool closure registered by setup_handlers.

    We intercept the server.app.call_tool decorator factory, record the
    function passed to it, then still invoke the real decorator so the
    server remains fully functional.

    Returns:
        A list that will be populated with the captured handler function
        after setup_handlers() is called on the server.
    """
    captured: list[Callable] = []
    original_call_tool = server.app.call_tool  # bound method

    def capturing_call_tool(**kw: Any):
        real_decorator = original_call_tool(**kw)

        def wrapper(fn: Callable) -> Callable:
            captured.append(fn)
            return real_decorator(fn)

        return wrapper

    server.app.call_tool = capturing_call_tool  # type: ignore[method-assign]
    return captured


def _capture_list_tools_fn(server: MCPServerBase) -> list[Callable]:
    """
    Capture the inner list_tools closure registered by setup_handlers.

    Returns:
        A list that will be populated with the captured handler function
        after setup_handlers() is called on the server.
    """
    captured: list[Callable] = []
    original_list_tools = server.app.list_tools  # bound method

    def capturing_list_tools():
        real_decorator = original_list_tools()

        def wrapper(fn: Callable) -> Callable:
            captured.append(fn)
            return real_decorator(fn)

        return wrapper

    server.app.list_tools = capturing_list_tools  # type: ignore[method-assign]
    return captured


def _make_bare_server() -> MCPServerBase:
    """Return an MCPServerBase with no default tools registered."""
    with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
        return MCPServerBase("test", setup_defaults=False)


# ---------------------------------------------------------------------------
# MCPServerBase – initialization
# ---------------------------------------------------------------------------


class TestMCPServerBaseInit:
    """Tests for MCPServerBase constructor."""

    def test_creates_server_with_name(self) -> None:
        """Server should expose the given name via app.name."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("my-agent")
        assert server.app.name == "my-agent"

    def test_default_tools_registered_when_setup_defaults_true(self) -> None:
        """When setup_defaults=True, all schemas in ALL_TOOL_SCHEMAS are registered."""
        fake_schema = make_tool_schema("fake_tool")
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", [fake_schema]):
            server = MCPServerBase("agent", setup_defaults=True)
        assert "fake_tool" in server.tools

    def test_no_tools_registered_when_setup_defaults_false(self) -> None:
        """When setup_defaults=False, tools dict should be empty."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", [make_tool_schema()]):
            server = MCPServerBase("agent", setup_defaults=False)
        assert server.tools == {}
        assert server._tool_handlers == {}

    def test_tools_and_handlers_dicts_are_separate(self) -> None:
        """tools and _tool_handlers should be independent dict objects."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("agent")
        assert server.tools is not server._tool_handlers


# ---------------------------------------------------------------------------
# MCPServerBase – register_tool
# ---------------------------------------------------------------------------


class TestRegisterTool:
    """Tests for MCPServerBase.register_tool."""

    def test_register_single_tool(self) -> None:
        """Registering a tool should add it to self.tools."""
        server = _make_bare_server()
        handler = AsyncMock(return_value={"ok": True})
        server.register_tool("my_tool", "does stuff", {}, handler)

        assert "my_tool" in server.tools
        assert server.tools["my_tool"]["name"] == "my_tool"
        assert server.tools["my_tool"]["description"] == "does stuff"

    def test_register_tool_stores_handler(self) -> None:
        """Handler should be stored in _tool_handlers under the tool name."""
        server = _make_bare_server()
        handler = AsyncMock(return_value={})
        server.register_tool("tool_a", "desc", {}, handler)

        assert server._tool_handlers["tool_a"] is handler

    def test_register_tool_stores_input_schema(self) -> None:
        """Input schema should be preserved exactly as provided."""
        server = _make_bare_server()
        schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }
        server.register_tool("fetch", "fetch a URL", schema, AsyncMock())

        assert server.tools["fetch"]["input_schema"] == schema

    def test_register_multiple_tools(self) -> None:
        """All registered tools should be independently accessible."""
        server = _make_bare_server()
        for name in ("tool_1", "tool_2", "tool_3"):
            server.register_tool(name, f"{name} desc", {}, AsyncMock())

        assert set(server.tools.keys()) == {"tool_1", "tool_2", "tool_3"}

    def test_registering_same_name_overwrites(self) -> None:
        """Re-registering a tool by the same name replaces the previous entry."""
        server = _make_bare_server()
        first_handler = AsyncMock(return_value={"v": 1})
        second_handler = AsyncMock(return_value={"v": 2})
        server.register_tool("dup", "first", {}, first_handler)
        server.register_tool("dup", "second", {}, second_handler)

        assert server.tools["dup"]["description"] == "second"
        assert server._tool_handlers["dup"] is second_handler


# ---------------------------------------------------------------------------
# MCPServerBase – register_tools_from_schemas
# ---------------------------------------------------------------------------


class TestRegisterToolsFromSchemas:
    """Tests for MCPServerBase.register_tools_from_schemas."""

    def test_registers_all_schemas(self) -> None:
        """All schemas passed to the method should be registered."""
        server = _make_bare_server()
        schemas = [make_tool_schema(f"tool_{i}") for i in range(5)]
        server.register_tools_from_schemas(schemas)

        assert len(server.tools) == 5
        for i in range(5):
            assert f"tool_{i}" in server.tools

    def test_empty_list_leaves_tools_unchanged(self) -> None:
        """Passing an empty list should not affect existing tools."""
        server = _make_bare_server()
        server.register_tool("existing", "desc", {}, AsyncMock())
        server.register_tools_from_schemas([])

        assert "existing" in server.tools
        assert len(server.tools) == 1

    def test_schema_dict_fields_are_forwarded(self) -> None:
        """name, description, and input_schema from each schema should be stored."""
        server = _make_bare_server()
        schema = make_tool_schema(
            name="special",
            description="special tool",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        server.register_tools_from_schemas([schema])

        assert server.tools["special"]["name"] == "special"
        assert server.tools["special"]["description"] == "special tool"
        assert "x" in server.tools["special"]["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# MCPServerBase – setup_handlers (list_tools)
# ---------------------------------------------------------------------------


class TestSetupHandlersListTools:
    """Tests for the list_tools handler installed by setup_handlers."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_correct_tool_count(self) -> None:
        """list_tools closure should return one Tool per registered tool."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("test", setup_defaults=False)

        for name in ("alpha", "beta", "gamma"):
            server.register_tool(name, f"{name} desc", {}, AsyncMock())

        captured: list[Callable] = _capture_list_tools_fn(server)
        server.setup_handlers()

        assert len(captured) == 1
        tools = await captured[0]()
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_names(self) -> None:
        """list_tools closure should include the tool names."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("test", setup_defaults=False)

        server.register_tool("my_tool", "does things", {}, AsyncMock())

        captured: list[Callable] = _capture_list_tools_fn(server)
        server.setup_handlers()

        tools = await captured[0]()
        names = [t.name for t in tools]
        assert "my_tool" in names

    @pytest.mark.asyncio
    async def test_list_tools_includes_description(self) -> None:
        """list_tools closure should include each tool's description."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("test", setup_defaults=False)

        server.register_tool("described_tool", "My great description", {}, AsyncMock())

        captured: list[Callable] = _capture_list_tools_fn(server)
        server.setup_handlers()

        tools = await captured[0]()
        tool = next(t for t in tools if t.name == "described_tool")
        assert tool.description == "My great description"

    @pytest.mark.asyncio
    async def test_list_tools_empty_when_no_tools_registered(self) -> None:
        """list_tools should return an empty list if no tools are registered."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("test", setup_defaults=False)

        captured: list[Callable] = _capture_list_tools_fn(server)
        server.setup_handlers()

        tools = await captured[0]()
        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_includes_input_schema(self) -> None:
        """list_tools closure should include the inputSchema for each tool."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("test", setup_defaults=False)

        input_schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        server.register_tool("search", "Search docs", input_schema, AsyncMock())

        captured: list[Callable] = _capture_list_tools_fn(server)
        server.setup_handlers()

        tools = await captured[0]()
        tool = next(t for t in tools if t.name == "search")
        assert tool.inputSchema == input_schema


# ---------------------------------------------------------------------------
# MCPServerBase – setup_handlers (call_tool)
# ---------------------------------------------------------------------------


class TestSetupHandlersCallTool:
    """Tests for the call_tool handler installed by setup_handlers."""

    def _make_server_with_capture(self) -> tuple[MCPServerBase, list[Callable]]:
        """Create a bare server with the call_tool closure captured."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("test", setup_defaults=False)
        captured = _capture_call_tool_fn(server)
        return server, captured

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_validation_error(self) -> None:
        """Calling an unregistered tool should return a validation_error response."""
        server, captured = self._make_server_with_capture()
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            result = await captured[0]("nonexistent_tool", {})

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["error"] == "validation_error"
        assert "nonexistent_tool" in data["message"]
        assert data["tool"] == "nonexistent_tool"

    @pytest.mark.asyncio
    async def test_successful_tool_call_returns_json(self) -> None:
        """A tool that returns a dict should produce TextContent with JSON."""
        server, captured = self._make_server_with_capture()
        handler = AsyncMock(return_value={"status": "ok", "count": 7})
        server.register_tool("count_things", "counts stuff", {}, handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            result = await captured[0]("count_things", {"limit": 10})

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["status"] == "ok"
        assert data["count"] == 7
        handler.assert_called_once_with(limit=10)

    @pytest.mark.asyncio
    async def test_tool_call_passes_arguments_as_kwargs(self) -> None:
        """The handler should receive arguments dict unpacked as kwargs."""
        server, captured = self._make_server_with_capture()
        received: list[dict] = []

        async def spy_handler(**kwargs: Any) -> dict[str, Any]:
            received.append(kwargs)
            return {"echo": kwargs}

        server.register_tool("spy", "spy tool", {}, spy_handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            await captured[0]("spy", {"x": 1, "y": "hello"})

        assert len(received) == 1
        assert received[0] == {"x": 1, "y": "hello"}

    @pytest.mark.asyncio
    async def test_permission_error_returns_authentication_required(self) -> None:
        """PermissionError from a tool handler should return authentication_required."""
        server, captured = self._make_server_with_capture()
        handler = AsyncMock(side_effect=PermissionError("Need OAuth token"))
        server.register_tool("protected_op", "needs auth", {}, handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            result = await captured[0]("protected_op", {})

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["error"] == "authentication_required"
        assert data["tool"] == "protected_op"
        assert "action_required" in data

    @pytest.mark.asyncio
    async def test_generic_exception_returns_execution_error(self) -> None:
        """Unexpected exceptions from a tool handler should return execution_error."""
        server, captured = self._make_server_with_capture()
        handler = AsyncMock(side_effect=RuntimeError("internal boom"))
        server.register_tool("boom_tool", "explodes", {}, handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            result = await captured[0]("boom_tool", {})

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["error"] == "execution_error"
        assert "internal boom" in data["message"]
        assert data["tool"] == "boom_tool"

    @pytest.mark.asyncio
    async def test_value_error_returns_validation_error_response(self) -> None:
        """ValueError from a tool handler should return a validation_error response."""
        server, captured = self._make_server_with_capture()
        handler = AsyncMock(side_effect=ValueError("bad param value"))
        server.register_tool("validate_tool", "validates", {}, handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            result = await captured[0]("validate_tool", {})

        data = json.loads(result[0].text)
        assert data["error"] == "validation_error"
        assert "bad param value" in data["message"]
        assert data["tool"] == "validate_tool"

    @pytest.mark.asyncio
    async def test_tool_invocation_logging_is_called_on_success(self) -> None:
        """log_tool_invocation should be called after a successful tool call."""
        server, captured = self._make_server_with_capture()
        handler = AsyncMock(return_value={"ok": True})
        server.register_tool("logged_tool", "logs", {}, handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await captured[0]("logged_tool", {"x": 1})

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["tool_name"] == "logged_tool"
        assert "duration_ms" in call_kwargs
        assert call_kwargs["error"] is None

    @pytest.mark.asyncio
    async def test_tool_invocation_logging_on_error(self) -> None:
        """log_tool_invocation should be called even when a tool raises an exception."""
        server, captured = self._make_server_with_capture()
        handler = AsyncMock(side_effect=ValueError("bad input"))
        server.register_tool("failing_tool", "fails", {}, handler)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await captured[0]("failing_tool", {})

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["tool_name"] == "failing_tool"
        assert "duration_ms" in call_kwargs
        assert isinstance(call_kwargs["error"], ValueError)
        assert "bad input" in str(call_kwargs["error"])

    @pytest.mark.asyncio
    async def test_call_tool_with_empty_arguments(self) -> None:
        """A tool called with an empty arguments dict should work correctly."""
        server, captured = self._make_server_with_capture()

        async def no_arg_tool() -> dict[str, Any]:
            return {"result": "done"}

        server.register_tool("no_args", "no arguments needed", {}, no_arg_tool)
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation"):
            result = await captured[0]("no_args", {})

        data = json.loads(result[0].text)
        assert data["result"] == "done"


# ---------------------------------------------------------------------------
# create_mcp_server factory
# ---------------------------------------------------------------------------


class TestCreateMCPServer:
    """Tests for the create_mcp_server factory function."""

    def test_returns_mcp_server_base_instance(self) -> None:
        """Factory should return an MCPServerBase instance."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = create_mcp_server("factory-test")
        assert isinstance(server, MCPServerBase)

    def test_server_has_correct_name(self) -> None:
        """The created server should expose the provided name."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = create_mcp_server("my-named-server")
        assert server.app.name == "my-named-server"

    def test_default_tools_are_registered(self) -> None:
        """Factory-created server should have tools registered from ALL_TOOL_SCHEMAS."""
        fake_schemas = [make_tool_schema("schema_tool_1"), make_tool_schema("schema_tool_2")]
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", fake_schemas):
            server = create_mcp_server("tool-test")
        assert "schema_tool_1" in server.tools
        assert "schema_tool_2" in server.tools

    def test_tools_and_handlers_populated(self) -> None:
        """Both .tools and ._tool_handlers should be populated by the factory."""
        fake_schema = make_tool_schema("factory_tool")
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", [fake_schema]):
            server = create_mcp_server("agent")
        assert "factory_tool" in server.tools
        assert "factory_tool" in server._tool_handlers

    def test_different_names_produce_different_servers(self) -> None:
        """Each call to create_mcp_server should produce a distinct server instance."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            s1 = create_mcp_server("server-a")
            s2 = create_mcp_server("server-b")
        assert s1 is not s2
        assert s1.app.name == "server-a"
        assert s2.app.name == "server-b"

    def test_server_tools_are_independent_between_instances(self) -> None:
        """Tools registered on one server should not appear on another."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            s1 = create_mcp_server("s1")
            s2 = create_mcp_server("s2")

        s1.register_tool("only_on_s1", "desc", {}, AsyncMock())
        assert "only_on_s1" not in s2.tools


# ---------------------------------------------------------------------------
# mcp_server.server module-level initialization
# ---------------------------------------------------------------------------


class TestMCPServerModuleInit:
    """Tests for module-level objects in mcp_server.server."""

    def test_module_exports_token_store(self) -> None:
        """mcp_server.server should expose a token_store attribute."""
        import mcp_server.server as srv_module

        assert hasattr(srv_module, "token_store")

    def test_module_exports_oauth_handler(self) -> None:
        """mcp_server.server should expose an oauth_handler attribute."""
        import mcp_server.server as srv_module

        assert hasattr(srv_module, "oauth_handler")

    def test_module_exports_logger(self) -> None:
        """mcp_server.server should expose a logger attribute."""
        import logging

        import mcp_server.server as srv_module

        assert hasattr(srv_module, "logger")
        assert isinstance(srv_module.logger, logging.Logger)

    def test_token_store_type(self) -> None:
        """token_store should be an instance of TokenStore."""
        from agent_framework.storage.token_store import TokenStore

        import mcp_server.server as srv_module

        assert isinstance(srv_module.token_store, TokenStore)

    def test_oauth_handler_type(self) -> None:
        """oauth_handler should be an instance of OAuthHandler."""
        import mcp_server.server as srv_module
        from mcp_server.auth.oauth_handler import OAuthHandler

        assert isinstance(srv_module.oauth_handler, OAuthHandler)

    def test_logger_name(self) -> None:
        """Logger should be named after the mcp_server.server module."""
        import mcp_server.server as srv_module

        assert srv_module.logger.name == "mcp_server.server"


# ---------------------------------------------------------------------------
# MCPServerBase – run (smoke test, no actual stdio)
# ---------------------------------------------------------------------------


class TestMCPServerRun:
    """Smoke tests for MCPServerBase.run."""

    @pytest.mark.asyncio
    async def test_run_uses_stdio_server(self) -> None:
        """run() should call stdio_server context manager and app.run."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("run-test", setup_defaults=False)

        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio_cm = MagicMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=None)

        server.app.run = AsyncMock()
        server.app.create_initialization_options = MagicMock(return_value={})

        with patch("agent_framework.server.server.stdio_server", return_value=mock_stdio_cm):
            await server.run()

        server.app.run.assert_called_once_with(mock_read, mock_write, {})

    @pytest.mark.asyncio
    async def test_run_passes_server_name_to_log(self) -> None:
        """run() should log the server name before starting."""
        with patch("agent_framework.server.server.ALL_TOOL_SCHEMAS", []):
            server = MCPServerBase("log-name-test", setup_defaults=False)

        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio_cm = MagicMock()
        mock_stdio_cm.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio_cm.__aexit__ = AsyncMock(return_value=None)

        server.app.run = AsyncMock()
        server.app.create_initialization_options = MagicMock(return_value={})

        with patch("agent_framework.server.server.stdio_server", return_value=mock_stdio_cm):
            with patch("agent_framework.server.server.logger") as mock_logger:
                await server.run()

        # Should have logged with the server name - check actual message strings
        logged_messages = [
            call.args[0] if call.args else "" for call in mock_logger.info.call_args_list
        ]
        assert any("log-name-test" in msg for msg in logged_messages)


# ---------------------------------------------------------------------------
# ALL_TOOL_SCHEMAS integrity
# ---------------------------------------------------------------------------


class TestAllToolSchemas:
    """Tests that ALL_TOOL_SCHEMAS is well-formed."""

    def test_all_tool_schemas_is_a_list(self) -> None:
        """ALL_TOOL_SCHEMAS should be a list."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        assert isinstance(ALL_TOOL_SCHEMAS, list)

    def test_all_schemas_have_required_keys(self) -> None:
        """Every schema in ALL_TOOL_SCHEMAS must have name, description, input_schema, handler."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        required_keys = {"name", "description", "input_schema", "handler"}
        for schema in ALL_TOOL_SCHEMAS:
            missing = required_keys - set(schema.keys())
            assert not missing, f"Schema {schema.get('name', '?')} missing keys: {missing}"

    def test_all_schema_names_are_strings(self) -> None:
        """Every schema name should be a non-empty string."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        for schema in ALL_TOOL_SCHEMAS:
            assert isinstance(schema["name"], str)
            assert len(schema["name"]) > 0

    def test_all_schema_handlers_are_callable(self) -> None:
        """Every schema handler should be callable."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        for schema in ALL_TOOL_SCHEMAS:
            assert callable(schema["handler"]), f"Handler for {schema['name']} is not callable"

    def test_schema_names_are_unique(self) -> None:
        """No two schemas should share the same tool name."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        names = [s["name"] for s in ALL_TOOL_SCHEMAS]
        assert len(names) == len(set(names)), "Duplicate tool names found in ALL_TOOL_SCHEMAS"

    def test_all_tool_schemas_not_empty(self) -> None:
        """ALL_TOOL_SCHEMAS should contain at least one tool."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        assert len(ALL_TOOL_SCHEMAS) > 0

    def test_server_registers_all_tool_schemas(self) -> None:
        """A default MCPServerBase should register every schema in ALL_TOOL_SCHEMAS."""
        from agent_framework.tools import ALL_TOOL_SCHEMAS

        server = create_mcp_server("schema-check")
        expected_names = {s["name"] for s in ALL_TOOL_SCHEMAS}
        assert set(server.tools.keys()) == expected_names
