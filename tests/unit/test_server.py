"""Unit tests for MCP server tool registration (agent_framework.server.server).

Target: bring Server coverage from 0% to 85%.
"""

import json
import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import mcp.types as mcp_types
import pytest
from agent_framework.server import MCPServerBase, create_mcp_server
from agent_framework.tools import ALL_TOOL_SCHEMAS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(return_value: dict | None = None, raise_exc: Exception | None = None) -> Callable:
    """Return an async handler that either returns a value or raises."""

    async def handler(**kwargs: Any) -> dict:
        if raise_exc is not None:
            raise raise_exc
        return return_value or {"status": "ok"}

    return handler


def _make_schema(
    name: str = "test_tool",
    description: str = "A test tool",
    input_schema: dict | None = None,
    handler: Callable | None = None,
) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": input_schema or {"type": "object", "properties": {}},
        "handler": handler or _make_handler(),
    }


async def _list_tools(server: MCPServerBase) -> list[mcp_types.Tool]:
    """Invoke the list_tools handler via the mcp request_handlers dict."""
    handler = server.app.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list", params=None)
    result = await handler(req)
    return result.root.tools


async def _call_tool(
    server: MCPServerBase, name: str, arguments: dict
) -> list[mcp_types.TextContent | mcp_types.ImageContent | mcp_types.EmbeddedResource]:
    """Invoke the call_tool handler via the mcp request_handlers dict."""
    handler = server.app.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=name, arguments=arguments),
    )
    result = await handler(req)
    return result.root.content


# ---------------------------------------------------------------------------
# MCPServerBase: initialization
# ---------------------------------------------------------------------------


class TestMCPServerBaseInit:
    """Tests for MCPServerBase.__init__."""

    def test_init_creates_empty_tools_when_no_defaults(self) -> None:
        """Server with setup_defaults=False should have no registered tools."""
        server = MCPServerBase("test-server", setup_defaults=False)
        assert server.tools == {}
        assert server._tool_handlers == {}

    def test_init_registers_all_tools_with_defaults(self) -> None:
        """Server with setup_defaults=True should auto-register ALL_TOOL_SCHEMAS."""
        server = MCPServerBase("test-server", setup_defaults=True)
        assert len(server.tools) == len(ALL_TOOL_SCHEMAS)
        for schema in ALL_TOOL_SCHEMAS:
            assert schema["name"] in server.tools

    def test_init_default_is_setup_defaults_true(self) -> None:
        """Default constructor should register tools."""
        server = MCPServerBase("test-server")
        assert len(server.tools) > 0

    def test_init_creates_mcp_app(self) -> None:
        """Server should create an underlying mcp.server.Server instance."""
        server = MCPServerBase("my-agent", setup_defaults=False)
        assert server.app is not None
        assert server.app.name == "my-agent"

    def test_init_server_name_stored(self) -> None:
        """Server name must be passed through to the mcp app."""
        for name in ("agent-alpha", "pr-agent", "code-review"):
            s = MCPServerBase(name, setup_defaults=False)
            assert s.app.name == name


# ---------------------------------------------------------------------------
# MCPServerBase: register_tool
# ---------------------------------------------------------------------------


class TestRegisterTool:
    """Tests for MCPServerBase.register_tool."""

    def test_register_single_tool(self) -> None:
        """Registering a tool adds it to self.tools and self._tool_handlers."""
        server = MCPServerBase("test", setup_defaults=False)
        handler = _make_handler()
        server.register_tool("my_tool", "Does something", {"type": "object"}, handler)

        assert "my_tool" in server.tools
        assert "my_tool" in server._tool_handlers
        assert server._tool_handlers["my_tool"] is handler

    def test_register_tool_stores_metadata(self) -> None:
        """Tool metadata is stored verbatim in self.tools."""
        server = MCPServerBase("test", setup_defaults=False)
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        server.register_tool("search", "Search the web", schema, _make_handler())

        info = server.tools["search"]
        assert info["name"] == "search"
        assert info["description"] == "Search the web"
        assert info["input_schema"] is schema

    def test_register_multiple_tools(self) -> None:
        """All registered tools should be present after multiple registrations."""
        server = MCPServerBase("test", setup_defaults=False)
        for i in range(5):
            server.register_tool(f"tool_{i}", f"Tool {i}", {}, _make_handler())

        assert len(server.tools) == 5

    def test_register_tool_overwrites_existing(self) -> None:
        """Re-registering a tool by the same name replaces the old handler."""
        server = MCPServerBase("test", setup_defaults=False)
        handler_a = _make_handler({"version": "a"})
        handler_b = _make_handler({"version": "b"})

        server.register_tool("my_tool", "desc", {}, handler_a)
        server.register_tool("my_tool", "desc updated", {}, handler_b)

        assert server._tool_handlers["my_tool"] is handler_b
        assert server.tools["my_tool"]["description"] == "desc updated"

    def test_register_tool_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        """register_tool should emit an INFO log."""
        server = MCPServerBase("test", setup_defaults=False)
        with caplog.at_level(logging.INFO, logger="agent_framework.server.server"):
            server.register_tool("logged_tool", "d", {}, _make_handler())
        assert "logged_tool" in caplog.text


# ---------------------------------------------------------------------------
# MCPServerBase: register_tools_from_schemas
# ---------------------------------------------------------------------------


class TestRegisterToolsFromSchemas:
    """Tests for MCPServerBase.register_tools_from_schemas."""

    def test_register_from_empty_list(self) -> None:
        """Calling with an empty list should leave the server unchanged."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tools_from_schemas([])
        assert server.tools == {}

    def test_register_from_single_schema(self) -> None:
        schema = _make_schema("alpha", "Alpha tool")
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tools_from_schemas([schema])

        assert "alpha" in server.tools
        assert server.tools["alpha"]["description"] == "Alpha tool"

    def test_register_from_multiple_schemas(self) -> None:
        schemas = [_make_schema(f"tool_{i}") for i in range(10)]
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tools_from_schemas(schemas)
        assert len(server.tools) == 10

    def test_register_from_real_all_tool_schemas(self) -> None:
        """ALL_TOOL_SCHEMAS should register without error."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tools_from_schemas(ALL_TOOL_SCHEMAS)
        assert len(server.tools) == len(ALL_TOOL_SCHEMAS)

    def test_schema_handler_is_callable(self) -> None:
        """Every handler stored via register_tools_from_schemas must be callable."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tools_from_schemas(ALL_TOOL_SCHEMAS)
        for name, handler in server._tool_handlers.items():
            assert callable(handler), f"Handler for {name!r} is not callable"


# ---------------------------------------------------------------------------
# MCPServerBase: setup_handlers / list_tools
# ---------------------------------------------------------------------------


class TestSetupHandlersListTools:
    """Tests for the list_tools handler wired up by setup_handlers."""

    @pytest.mark.asyncio
    async def test_list_tools_empty_server(self) -> None:
        """list_tools on an empty server returns an empty list."""
        server = MCPServerBase("test", setup_defaults=False)
        server.setup_handlers()

        tools = await _list_tools(server)
        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_returns_registered_tools(self) -> None:
        """list_tools returns Tool objects for each registered tool."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("alpha", "Alpha", {"type": "object"}, _make_handler())
        server.register_tool("beta", "Beta", {"type": "object"}, _make_handler())
        server.setup_handlers()

        tools = await _list_tools(server)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"alpha", "beta"}
        for t in tools:
            assert isinstance(t, mcp_types.Tool)

    @pytest.mark.asyncio
    async def test_list_tools_metadata_preserved(self) -> None:
        """Tool objects returned by list_tools carry description and inputSchema."""
        input_schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("search", "Search docs", input_schema, _make_handler())
        server.setup_handlers()

        (tool,) = await _list_tools(server)
        assert tool.name == "search"
        assert tool.description == "Search docs"
        assert tool.inputSchema == input_schema

    @pytest.mark.asyncio
    async def test_list_tools_with_all_default_tools(self) -> None:
        """list_tools with default setup returns correct count of tools."""
        server = MCPServerBase("test", setup_defaults=True)
        server.setup_handlers()

        tools = await _list_tools(server)
        assert len(tools) == len(ALL_TOOL_SCHEMAS)

    @pytest.mark.asyncio
    async def test_list_tools_handler_registered(self) -> None:
        """setup_handlers must register a ListToolsRequest handler."""
        server = MCPServerBase("test", setup_defaults=False)
        server.setup_handlers()
        assert mcp_types.ListToolsRequest in server.app.request_handlers


# ---------------------------------------------------------------------------
# MCPServerBase: setup_handlers / call_tool – success path
# ---------------------------------------------------------------------------


class TestCallToolSuccess:
    """Tests for successful tool invocation via call_tool."""

    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self) -> None:
        """A successful tool call wraps the result in TextContent."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("echo", "Echoes input", {}, _make_handler({"echo": "hello"}))
        server.setup_handlers()

        results = await _call_tool(server, "echo", {})
        assert len(results) == 1
        assert isinstance(results[0], mcp_types.TextContent)

    @pytest.mark.asyncio
    async def test_call_tool_result_is_valid_json(self) -> None:
        """The TextContent text must be valid JSON."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("data", "Returns data", {}, _make_handler({"a": 1, "b": "two"}))
        server.setup_handlers()

        results = await _call_tool(server, "data", {})
        parsed = json.loads(results[0].text)
        assert parsed == {"a": 1, "b": "two"}

    @pytest.mark.asyncio
    async def test_call_tool_passes_arguments_to_handler(self) -> None:
        """Arguments supplied to call_tool are forwarded to the handler."""

        received: dict = {}

        async def capture_handler(**kwargs: Any) -> dict:
            received.update(kwargs)
            return {"ok": True}

        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("capture", "Captures args", {}, capture_handler)
        server.setup_handlers()

        await _call_tool(server, "capture", {"name": "Alice", "count": 3})
        assert received == {"name": "Alice", "count": 3}

    @pytest.mark.asyncio
    async def test_call_tool_with_empty_arguments(self) -> None:
        """Passing an empty arguments dict should not raise."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("no_args", "No args", {}, _make_handler({"done": True}))
        server.setup_handlers()

        results = await _call_tool(server, "no_args", {})
        assert len(results) == 1
        assert json.loads(results[0].text) == {"done": True}

    @pytest.mark.asyncio
    async def test_call_tool_handler_registered(self) -> None:
        """setup_handlers must register a CallToolRequest handler."""
        server = MCPServerBase("test", setup_defaults=False)
        server.setup_handlers()
        assert mcp_types.CallToolRequest in server.app.request_handlers


# ---------------------------------------------------------------------------
# MCPServerBase: setup_handlers / call_tool – error paths
# ---------------------------------------------------------------------------


class TestCallToolErrors:
    """Tests for error handling in the call_tool handler."""

    @pytest.mark.asyncio
    async def test_call_unknown_tool_returns_validation_error(self) -> None:
        """Calling an unregistered tool name should return validation_error."""
        server = MCPServerBase("test", setup_defaults=False)
        server.setup_handlers()

        results = await _call_tool(server, "nonexistent", {})
        assert len(results) == 1
        parsed = json.loads(results[0].text)
        assert parsed["error"] == "validation_error"
        assert parsed["tool"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_call_tool_value_error_returns_validation_error(self) -> None:
        """ValueError raised by handler should return validation_error."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("bad", "Bad", {}, _make_handler(raise_exc=ValueError("bad input")))
        server.setup_handlers()

        results = await _call_tool(server, "bad", {})
        parsed = json.loads(results[0].text)
        assert parsed["error"] == "validation_error"
        assert "bad input" in parsed["message"]
        assert parsed["tool"] == "bad"

    @pytest.mark.asyncio
    async def test_call_tool_permission_error_returns_auth_error(self) -> None:
        """PermissionError raised by handler should return authentication_required."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool(
            "auth", "Auth", {}, _make_handler(raise_exc=PermissionError("no token"))
        )
        server.setup_handlers()

        results = await _call_tool(server, "auth", {})
        parsed = json.loads(results[0].text)
        assert parsed["error"] == "authentication_required"
        assert parsed["tool"] == "auth"
        assert "action_required" in parsed

    @pytest.mark.asyncio
    async def test_call_tool_generic_exception_returns_execution_error(self) -> None:
        """Unexpected exceptions should return execution_error."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool(
            "boom", "Boom", {}, _make_handler(raise_exc=RuntimeError("unexpected"))
        )
        server.setup_handlers()

        results = await _call_tool(server, "boom", {})
        parsed = json.loads(results[0].text)
        assert parsed["error"] == "execution_error"
        assert "unexpected" in parsed["message"]
        assert parsed["tool"] == "boom"

    @pytest.mark.asyncio
    async def test_call_tool_error_response_is_text_content(self) -> None:
        """Error responses must always be TextContent, not some other type."""
        server = MCPServerBase("test", setup_defaults=False)
        server.setup_handlers()

        results = await _call_tool(server, "does_not_exist", {})
        assert isinstance(results[0], mcp_types.TextContent)

    @pytest.mark.asyncio
    async def test_call_tool_error_text_is_valid_json(self) -> None:
        """Error responses must always be valid JSON."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("err", "Err", {}, _make_handler(raise_exc=Exception("oops")))
        server.setup_handlers()

        results = await _call_tool(server, "err", {})
        # Should not raise
        parsed = json.loads(results[0].text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool_includes_tool_name(self) -> None:
        """Error dict must include the 'tool' key with the attempted name."""
        server = MCPServerBase("test", setup_defaults=False)
        server.setup_handlers()

        results = await _call_tool(server, "missing_tool", {})
        parsed = json.loads(results[0].text)
        assert parsed["tool"] == "missing_tool"

    @pytest.mark.asyncio
    async def test_call_tool_permission_error_includes_action_required(self) -> None:
        """PermissionError response must include 'action_required' field."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool(
            "locked", "Locked", {}, _make_handler(raise_exc=PermissionError("OAuth needed"))
        )
        server.setup_handlers()

        results = await _call_tool(server, "locked", {})
        parsed = json.loads(results[0].text)
        assert "action_required" in parsed
        assert "OAuth" in parsed["action_required"] or "oauth" in parsed["action_required"].lower()


# ---------------------------------------------------------------------------
# MCPServerBase: telemetry / log_tool_invocation is called
# ---------------------------------------------------------------------------


class TestCallToolTelemetry:
    """Tests that call_tool invokes log_tool_invocation in the finally block."""

    @pytest.mark.asyncio
    async def test_log_tool_invocation_called_on_success(self) -> None:
        """log_tool_invocation must be called even on a successful call."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("ping", "Ping", {}, _make_handler({"pong": True}))
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await _call_tool(server, "ping", {})
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_tool_invocation_called_on_error(self) -> None:
        """log_tool_invocation must be called even when the handler raises."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("fail", "Fail", {}, _make_handler(raise_exc=RuntimeError("boom")))
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await _call_tool(server, "fail", {})
            mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_tool_invocation_receives_duration(self) -> None:
        """duration_ms passed to log_tool_invocation must be a non-negative number."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("timer", "Timer", {}, _make_handler({"t": 1}))
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await _call_tool(server, "timer", {"x": 1})
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_log_tool_invocation_error_arg_is_none_on_success(self) -> None:
        """error kwarg passed to log_tool_invocation must be None on success."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("ok", "Ok", {}, _make_handler({"ok": True}))
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await _call_tool(server, "ok", {})
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["error"] is None

    @pytest.mark.asyncio
    async def test_log_tool_invocation_error_arg_is_exception_on_failure(self) -> None:
        """error kwarg passed to log_tool_invocation must be the raised exception."""
        exc = RuntimeError("kaboom")
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("err", "Err", {}, _make_handler(raise_exc=exc))
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await _call_tool(server, "err", {})
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["error"] is exc

    @pytest.mark.asyncio
    async def test_log_tool_invocation_receives_tool_name(self) -> None:
        """tool_name kwarg must match the called tool name."""
        server = MCPServerBase("test", setup_defaults=False)
        server.register_tool("specific_tool", "T", {}, _make_handler({"r": 1}))
        server.setup_handlers()

        with patch("agent_framework.server.server.log_tool_invocation") as mock_log:
            await _call_tool(server, "specific_tool", {})
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["tool_name"] == "specific_tool"


# ---------------------------------------------------------------------------
# create_mcp_server factory
# ---------------------------------------------------------------------------


class TestCreateMcpServer:
    """Tests for the create_mcp_server convenience factory."""

    def test_returns_mcp_server_base_instance(self) -> None:
        server = create_mcp_server("factory-test")
        assert isinstance(server, MCPServerBase)

    def test_name_is_passed_through(self) -> None:
        server = create_mcp_server("my-special-agent")
        assert server.app.name == "my-special-agent"

    def test_default_tools_are_registered(self) -> None:
        """Factory always enables setup_defaults=True."""
        server = create_mcp_server("full-server")
        assert len(server.tools) == len(ALL_TOOL_SCHEMAS)

    def test_all_tools_have_handlers(self) -> None:
        server = create_mcp_server("handler-check")
        for name in server.tools:
            assert name in server._tool_handlers
            assert callable(server._tool_handlers[name])


# ---------------------------------------------------------------------------
# ALL_TOOL_SCHEMAS shape validation
# ---------------------------------------------------------------------------


class TestAllToolSchemasShape:
    """Validate the structure of ALL_TOOL_SCHEMAS itself."""

    REQUIRED_KEYS = {"name", "description", "input_schema", "handler"}

    def test_all_schemas_have_required_keys(self) -> None:
        for schema in ALL_TOOL_SCHEMAS:
            missing = self.REQUIRED_KEYS - schema.keys()
            assert not missing, f"Schema {schema.get('name')!r} missing keys: {missing}"

    def test_all_schema_names_are_strings(self) -> None:
        for schema in ALL_TOOL_SCHEMAS:
            assert isinstance(schema["name"], str), f"Non-string name: {schema['name']!r}"

    def test_all_schema_names_are_unique(self) -> None:
        names = [s["name"] for s in ALL_TOOL_SCHEMAS]
        assert len(names) == len(set(names)), "Duplicate tool names detected"

    def test_all_schema_descriptions_are_non_empty_strings(self) -> None:
        for schema in ALL_TOOL_SCHEMAS:
            assert isinstance(schema["description"], str)
            assert len(schema["description"]) > 0, f"Empty description for {schema['name']!r}"

    def test_all_schema_input_schemas_are_dicts(self) -> None:
        for schema in ALL_TOOL_SCHEMAS:
            assert isinstance(schema["input_schema"], dict), (
                f"input_schema for {schema['name']!r} is not a dict"
            )

    def test_all_handlers_are_callable(self) -> None:
        for schema in ALL_TOOL_SCHEMAS:
            assert callable(schema["handler"]), f"handler for {schema['name']!r} is not callable"

    def test_schemas_is_a_list(self) -> None:
        assert isinstance(ALL_TOOL_SCHEMAS, list)

    def test_schemas_is_non_empty(self) -> None:
        assert len(ALL_TOOL_SCHEMAS) > 0
