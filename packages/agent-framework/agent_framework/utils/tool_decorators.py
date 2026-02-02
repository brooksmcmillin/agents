"""Decorators for standardizing tool error handling.

This module provides the `handle_tool_errors` decorator for consistent error handling
across all MCP tools. It catches common exceptions and returns a standardized error
format that agents can easily parse and respond to.

Usage:
    # Basic usage (no parameters)
    @handle_tool_errors
    async def my_tool(param: str) -> dict[str, Any]:
        result = await do_something(param)
        return {"data": result}

    # With custom operation name for clearer logs
    @handle_tool_errors(operation="fetch user profile")
    async def get_user(user_id: str) -> dict[str, Any]:
        ...

    # With traceback for debugging
    @handle_tool_errors(include_traceback=True)
    async def debug_tool() -> dict[str, Any]:
        ...
"""

import functools
import logging
import traceback
from collections.abc import Callable
from typing import Any, overload

import httpx

from .errors import (
    AgentError,
    AuthenticationError,
    ConfigurationError,
    ServerError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def _build_error_response(
    message: str,
    error_type: str,
    *,
    include_traceback: bool = False,
    status_code: int | None = None,
) -> dict[str, Any]:
    """Build a standardized error response dictionary.

    Args:
        message: Human-readable error message
        error_type: Error classification (e.g., "ValidationError", "HTTPError")
        include_traceback: Whether to include full traceback in response
        status_code: HTTP status code if applicable

    Returns:
        Standardized error dictionary with status, message, and error_type
    """
    response: dict[str, Any] = {
        "status": "error",
        "message": message,
        "error_type": error_type,
    }
    if status_code is not None:
        response["status_code"] = status_code
    if include_traceback:
        response["traceback"] = traceback.format_exc()
    return response


def _handle_exception(
    e: Exception,
    operation: str,
    include_traceback: bool,
) -> dict[str, Any]:
    """Handle an exception and return appropriate error response.

    Args:
        e: The caught exception
        operation: Operation name for logging context
        include_traceback: Whether to include traceback in response

    Returns:
        Standardized error dictionary
    """
    # HTTP errors with specific status code handling
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        logger.error(f"{operation} HTTP {status}: {e}")

        # Map common HTTP status codes to semantic error types
        http_error_map: dict[int, tuple[str, str]] = {
            400: ("Bad request", "BadRequestError"),
            401: ("Authentication required", "AuthenticationError"),
            403: ("Access forbidden", "ForbiddenError"),
            404: ("Resource not found", "NotFoundError"),
            409: ("Conflict - resource already exists", "ConflictError"),
            422: ("Validation failed", "ValidationError"),
            429: ("Rate limit exceeded", "RateLimitError"),
            500: ("Internal server error", "ServerError"),
            502: ("Bad gateway", "GatewayError"),
            503: ("Service unavailable", "ServiceUnavailableError"),
            504: ("Gateway timeout", "TimeoutError"),
        }

        if status in http_error_map:
            message, error_type = http_error_map[status]
            return _build_error_response(
                message,
                error_type,
                include_traceback=include_traceback,
                status_code=status,
            )

        return _build_error_response(
            f"HTTP {status}: {e}",
            "HTTPError",
            include_traceback=include_traceback,
            status_code=status,
        )

    # Network/connection errors
    if isinstance(e, httpx.RequestError):
        logger.error(f"{operation} request failed: {e}")
        return _build_error_response(
            f"Request failed: {e}",
            "RequestError",
            include_traceback=include_traceback,
        )

    # Timeout errors (async operations)
    # Note: asyncio.TimeoutError is an alias for TimeoutError in Python 3.11+
    if isinstance(e, TimeoutError):
        logger.error(f"{operation} timed out: {e}")
        return _build_error_response(
            f"Operation timed out: {e}",
            "TimeoutError",
            include_traceback=include_traceback,
        )

    # File system errors
    if isinstance(e, FileNotFoundError):
        logger.error(f"{operation} file not found: {e}")
        return _build_error_response(
            f"File not found: {e.filename if e.filename else e}",
            "NotFoundError",
            include_traceback=include_traceback,
        )

    if isinstance(e, FileExistsError):
        logger.error(f"{operation} file exists: {e}")
        return _build_error_response(
            f"File already exists: {e.filename if e.filename else e}",
            "ConflictError",
            include_traceback=include_traceback,
        )

    if isinstance(e, PermissionError):
        logger.error(f"{operation} permission denied: {e}")
        return _build_error_response(
            f"Permission denied: {e}",
            "ForbiddenError",
            include_traceback=include_traceback,
        )

    # Framework-specific errors
    if isinstance(e, ValidationError):
        logger.error(f"{operation} validation error: {e}")
        return _build_error_response(
            str(e),
            "ValidationError",
            include_traceback=include_traceback,
        )

    if isinstance(e, AuthenticationError):
        logger.error(f"{operation} authentication error: {e}")
        return _build_error_response(
            str(e),
            "AuthenticationError",
            include_traceback=include_traceback,
        )

    if isinstance(e, ServerError):
        logger.error(f"{operation} server error: {e}")
        return _build_error_response(
            str(e),
            "ServerError",
            include_traceback=include_traceback,
        )

    if isinstance(e, ConfigurationError):
        logger.error(f"{operation} configuration error: {e}")
        return _build_error_response(
            str(e),
            "ConfigurationError",
            include_traceback=include_traceback,
        )

    if isinstance(e, AgentError):
        logger.error(f"{operation} agent error: {e}")
        return _build_error_response(
            str(e),
            type(e).__name__,
            include_traceback=include_traceback,
        )

    # Built-in validation errors
    if isinstance(e, ValueError):
        logger.error(f"{operation} validation error: {e}")
        return _build_error_response(
            str(e),
            "ValidationError",
            include_traceback=include_traceback,
        )

    if isinstance(e, TypeError):
        logger.error(f"{operation} type error: {e}")
        return _build_error_response(
            str(e),
            "TypeError",
            include_traceback=include_traceback,
        )

    if isinstance(e, KeyError):
        logger.error(f"{operation} key error: {e}")
        return _build_error_response(
            f"Missing key: {e}",
            "KeyError",
            include_traceback=include_traceback,
        )

    # Catch-all for unexpected errors
    logger.exception(f"{operation} unexpected error: {e}")
    return _build_error_response(
        f"Unexpected error: {e}",
        type(e).__name__,
        include_traceback=include_traceback,
    )


@overload
def handle_tool_errors[F: Callable[..., Any]](func: F) -> F: ...


@overload
def handle_tool_errors(
    *,
    operation: str | None = None,
    include_traceback: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


def handle_tool_errors[F: Callable[..., Any]](
    func: F | None = None,
    *,
    operation: str | None = None,
    include_traceback: bool = False,
) -> F | Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Standardize error handling for async tool functions.

    Catches common exceptions and returns a consistent error format:
    {"status": "error", "message": "...", "error_type": "..."}

    On success, adds "status": "success" to the result if not already present.

    Can be used with or without arguments:

        @handle_tool_errors
        async def my_tool(param: str) -> dict[str, Any]:
            ...

        @handle_tool_errors(operation="fetch emails")
        async def get_emails() -> dict[str, Any]:
            ...

    Args:
        func: The function to decorate (when used without parentheses)
        operation: Custom operation name for log messages. Defaults to function name.
            Use a descriptive verb phrase like "fetch user profile" or "send email".
        include_traceback: Include full stack trace in error response. Useful for
            debugging but should be False in production. Default: False.

    Returns:
        Decorated function that catches exceptions and returns error dictionaries.

    Error Types Handled:
        - httpx.HTTPStatusError: HTTP errors with semantic status code mapping
        - httpx.RequestError: Network/connection failures
        - TimeoutError: Async operation timeouts
        - FileNotFoundError: File system errors (maps to NotFoundError)
        - FileExistsError: File conflicts (maps to ConflictError)
        - PermissionError: Access denied (maps to ForbiddenError)
        - ValidationError: Input validation failures (framework or ValueError)
        - AuthenticationError: Auth failures
        - ConfigurationError: Missing/invalid configuration
        - AgentError: Base framework errors
        - TypeError, KeyError: Programming errors
        - Exception: Catch-all for unexpected errors

    Example:
        @handle_tool_errors(operation="list mailboxes")
        async def list_mailboxes(api_token: str | None = None) -> dict[str, Any]:
            client = get_client(api_token)
            mailboxes = await client.list_mailboxes()
            return {"mailboxes": mailboxes, "count": len(mailboxes)}

        # On success: {"status": "success", "mailboxes": [...], "count": 5}
        # On 401 error: {"status": "error", "message": "Authentication required",
        #                "error_type": "AuthenticationError", "status_code": 401}
        # On ValueError: {"status": "error", "message": "Invalid input",
        #                 "error_type": "ValidationError"}
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        op_name = operation or fn.__name__

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                result = await fn(*args, **kwargs)
                # Auto-add success status if missing
                if isinstance(result, dict) and "status" not in result:
                    result["status"] = "success"
                return result
            except Exception as e:
                return _handle_exception(e, op_name, include_traceback)

        return wrapper

    # Support both @handle_tool_errors and @handle_tool_errors(...)
    if func is not None:
        return decorator(func)  # type: ignore[return-value]
    return decorator
