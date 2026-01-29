"""Unit tests for tool error handling decorators."""

import httpx
import pytest
from agent_framework.utils.tool_decorators import handle_tool_errors


class TestHandleToolErrors:
    """Tests for the handle_tool_errors decorator."""

    @pytest.mark.asyncio
    async def test_success_adds_status(self):
        """Successful result should have status: success added."""

        @handle_tool_errors
        async def my_tool(x: int) -> dict:
            return {"value": x * 2}

        result = await my_tool(5)
        assert result["status"] == "success"
        assert result["value"] == 10

    @pytest.mark.asyncio
    async def test_success_preserves_existing_status(self):
        """Existing status in result should not be overwritten."""

        @handle_tool_errors
        async def my_tool() -> dict:
            return {"status": "custom", "data": 123}

        result = await my_tool()
        assert result["status"] == "custom"
        assert result["data"] == 123

    @pytest.mark.asyncio
    async def test_value_error_returns_validation_error(self):
        """ValueError should be caught and returned as ValidationError."""

        @handle_tool_errors
        async def my_tool(x: int) -> dict:
            if x < 0:
                raise ValueError("x must be positive")
            return {"value": x}

        result = await my_tool(-1)
        assert result["status"] == "error"
        assert result["error_type"] == "ValidationError"
        assert "x must be positive" in result["message"]

    @pytest.mark.asyncio
    async def test_http_401_returns_authentication_error(self):
        """HTTP 401 should be returned as AuthenticationError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(401, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("Unauthorized", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "AuthenticationError"
        assert "Authentication required" in result["message"]

    @pytest.mark.asyncio
    async def test_http_403_returns_forbidden_error(self):
        """HTTP 403 should be returned as ForbiddenError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(403, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("Forbidden", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "ForbiddenError"
        assert "forbidden" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_http_404_returns_not_found_error(self):
        """HTTP 404 should be returned as NotFoundError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(404, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("Not Found", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "NotFoundError"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_http_500_returns_http_error(self):
        """HTTP 500 should be returned as HTTPError with status code."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(500, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("Server Error", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "HTTPError"
        assert "500" in result["message"]

    @pytest.mark.asyncio
    async def test_request_error_returns_request_error(self):
        """Connection errors should be returned as RequestError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            raise httpx.ConnectError("Connection refused")

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "RequestError"
        assert "Request failed" in result["message"]

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_error_type(self):
        """Unexpected exceptions should include the exception type."""

        @handle_tool_errors
        async def my_tool() -> dict:
            raise RuntimeError("Something went wrong")

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "RuntimeError"
        assert "Something went wrong" in result["message"]

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        """Decorator should preserve the original function name."""

        @handle_tool_errors
        async def my_special_tool() -> dict:
            return {"ok": True}

        assert my_special_tool.__name__ == "my_special_tool"

    @pytest.mark.asyncio
    async def test_preserves_docstring(self):
        """Decorator should preserve the original docstring."""

        @handle_tool_errors
        async def documented_tool() -> dict:
            """This is a documented tool."""
            return {"ok": True}

        assert documented_tool.__doc__ == "This is a documented tool."

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        """Decorator should pass through args and kwargs correctly."""

        @handle_tool_errors
        async def tool_with_params(a: int, b: str, c: bool = False) -> dict:
            return {"a": a, "b": b, "c": c}

        result = await tool_with_params(1, "hello", c=True)
        assert result["a"] == 1
        assert result["b"] == "hello"
        assert result["c"] is True
        assert result["status"] == "success"
