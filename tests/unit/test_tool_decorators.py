"""Unit tests for tool error handling decorators."""

import httpx
import pytest
from agent_framework.utils.errors import (
    AuthenticationError,
    ConfigurationError,
    ServerError,
    ValidationError,
)
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
    async def test_http_500_returns_server_error(self):
        """HTTP 500 should be returned as ServerError with status code."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(500, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("Server Error", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "ServerError"
        assert result["status_code"] == 500
        assert "server error" in result["message"].lower()

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


class TestHandleToolErrorsWithParameters:
    """Tests for handle_tool_errors decorator with parameters."""

    @pytest.mark.asyncio
    async def test_custom_operation_name(self):
        """Custom operation name should be used in error context."""

        @handle_tool_errors(operation="fetch user emails")
        async def get_emails() -> dict:
            raise ValueError("Invalid mailbox")

        result = await get_emails()
        assert result["status"] == "error"
        assert result["error_type"] == "ValidationError"
        # The operation name is used in logging, not in the response
        assert "Invalid mailbox" in result["message"]

    @pytest.mark.asyncio
    async def test_include_traceback_false_by_default(self):
        """Traceback should not be included by default."""

        @handle_tool_errors
        async def my_tool() -> dict:
            raise RuntimeError("Boom")

        result = await my_tool()
        assert "traceback" not in result

    @pytest.mark.asyncio
    async def test_include_traceback_true(self):
        """Traceback should be included when requested."""

        @handle_tool_errors(include_traceback=True)
        async def my_tool() -> dict:
            raise RuntimeError("Boom")

        result = await my_tool()
        assert "traceback" in result
        assert "RuntimeError" in result["traceback"]
        assert "Boom" in result["traceback"]

    @pytest.mark.asyncio
    async def test_with_all_parameters(self):
        """Both operation and include_traceback can be used together."""

        @handle_tool_errors(operation="process data", include_traceback=True)
        async def process() -> dict:
            raise ValueError("Bad data")

        result = await process()
        assert result["status"] == "error"
        assert result["error_type"] == "ValidationError"
        assert "traceback" in result


class TestFileSystemErrors:
    """Tests for file system error handling."""

    @pytest.mark.asyncio
    async def test_file_not_found_error(self):
        """FileNotFoundError should be returned as NotFoundError."""

        @handle_tool_errors
        async def read_file() -> dict:
            raise FileNotFoundError(2, "No such file", "/path/to/file.txt")

        result = await read_file()
        assert result["status"] == "error"
        assert result["error_type"] == "NotFoundError"
        assert "/path/to/file.txt" in result["message"]

    @pytest.mark.asyncio
    async def test_file_exists_error(self):
        """FileExistsError should be returned as ConflictError."""

        @handle_tool_errors
        async def create_file() -> dict:
            raise FileExistsError(17, "File exists", "/path/to/file.txt")

        result = await create_file()
        assert result["status"] == "error"
        assert result["error_type"] == "ConflictError"
        assert "/path/to/file.txt" in result["message"]

    @pytest.mark.asyncio
    async def test_permission_error(self):
        """PermissionError should be returned as ForbiddenError."""

        @handle_tool_errors
        async def write_file() -> dict:
            raise PermissionError("Cannot write to /etc/passwd")

        result = await write_file()
        assert result["status"] == "error"
        assert result["error_type"] == "ForbiddenError"
        assert "Permission denied" in result["message"]


class TestTimeoutErrors:
    """Tests for timeout error handling."""

    @pytest.mark.asyncio
    async def test_builtin_timeout_error(self):
        """Built-in TimeoutError should be handled."""

        @handle_tool_errors
        async def slow_operation() -> dict:
            raise TimeoutError("Operation timed out after 30s")

        result = await slow_operation()
        assert result["status"] == "error"
        assert result["error_type"] == "TimeoutError"
        assert "timed out" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_asyncio_timeout_error(self):
        """asyncio.TimeoutError should be handled."""

        @handle_tool_errors
        async def async_operation() -> dict:
            raise TimeoutError("Async timeout")

        result = await async_operation()
        assert result["status"] == "error"
        assert result["error_type"] == "TimeoutError"


class TestFrameworkErrors:
    """Tests for framework-specific error handling."""

    @pytest.mark.asyncio
    async def test_framework_validation_error(self):
        """Framework ValidationError should be handled."""

        @handle_tool_errors
        async def validate() -> dict:
            raise ValidationError("Input validation failed")

        result = await validate()
        assert result["status"] == "error"
        assert result["error_type"] == "ValidationError"
        assert "Input validation failed" in result["message"]

    @pytest.mark.asyncio
    async def test_framework_authentication_error(self):
        """Framework AuthenticationError should be handled."""

        @handle_tool_errors
        async def authenticate() -> dict:
            raise AuthenticationError("Token expired")

        result = await authenticate()
        assert result["status"] == "error"
        assert result["error_type"] == "AuthenticationError"
        assert "Token expired" in result["message"]

    @pytest.mark.asyncio
    async def test_framework_configuration_error(self):
        """Framework ConfigurationError should be handled."""

        @handle_tool_errors
        async def configure() -> dict:
            raise ConfigurationError("Missing API key")

        result = await configure()
        assert result["status"] == "error"
        assert result["error_type"] == "ConfigurationError"
        assert "Missing API key" in result["message"]

    @pytest.mark.asyncio
    async def test_framework_server_error(self):
        """Framework ServerError should be handled."""

        @handle_tool_errors
        async def call_api() -> dict:
            raise ServerError("JMAP error: Invalid method")

        result = await call_api()
        assert result["status"] == "error"
        assert result["error_type"] == "ServerError"
        assert "JMAP error" in result["message"]


class TestAdditionalHTTPStatusCodes:
    """Tests for additional HTTP status code handling."""

    @pytest.mark.asyncio
    async def test_http_400_returns_bad_request(self):
        """HTTP 400 should be returned as BadRequestError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(400, request=httpx.Request("POST", "http://test"))
            raise httpx.HTTPStatusError("Bad Request", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "BadRequestError"
        assert result["status_code"] == 400

    @pytest.mark.asyncio
    async def test_http_409_returns_conflict(self):
        """HTTP 409 should be returned as ConflictError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(409, request=httpx.Request("PUT", "http://test"))
            raise httpx.HTTPStatusError("Conflict", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "ConflictError"
        assert result["status_code"] == 409

    @pytest.mark.asyncio
    async def test_http_429_returns_rate_limit(self):
        """HTTP 429 should be returned as RateLimitError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(429, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError(
                "Too Many Requests", request=response.request, response=response
            )

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "RateLimitError"
        assert result["status_code"] == 429

    @pytest.mark.asyncio
    async def test_http_503_returns_service_unavailable(self):
        """HTTP 503 should be returned as ServiceUnavailableError."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(503, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError(
                "Service Unavailable", request=response.request, response=response
            )

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "ServiceUnavailableError"
        assert result["status_code"] == 503

    @pytest.mark.asyncio
    async def test_unmapped_http_status_returns_generic(self):
        """Unmapped HTTP status codes should return HTTPError with status code."""

        @handle_tool_errors
        async def my_tool() -> dict:
            response = httpx.Response(418, request=httpx.Request("GET", "http://test"))
            raise httpx.HTTPStatusError("I'm a teapot", request=response.request, response=response)

        result = await my_tool()
        assert result["status"] == "error"
        assert result["error_type"] == "HTTPError"
        assert result["status_code"] == 418
        assert "418" in result["message"]


class TestKeyAndTypeErrors:
    """Tests for KeyError and TypeError handling."""

    @pytest.mark.asyncio
    async def test_key_error(self):
        """KeyError should be handled with descriptive message."""

        @handle_tool_errors
        async def access_dict() -> dict:
            data: dict = {}
            return {"value": data["missing_key"]}

        result = await access_dict()
        assert result["status"] == "error"
        assert result["error_type"] == "KeyError"
        assert "missing_key" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_type_error(self):
        """TypeError should be handled."""

        @handle_tool_errors
        async def wrong_type() -> dict:
            raise TypeError("Expected str, got int")

        result = await wrong_type()
        assert result["status"] == "error"
        assert result["error_type"] == "TypeError"
        assert "Expected str" in result["message"]
