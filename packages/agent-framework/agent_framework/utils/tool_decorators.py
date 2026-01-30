"""Decorators for standardizing tool error handling."""

import functools
import logging
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def handle_tool_errors[F: Callable[..., Any]](func: F) -> F:
    """Standardize error handling for async tool functions.

    Catches common exceptions and returns consistent error format:
    {"status": "error", "message": "...", "error_type": "..."}

    On success, adds "status": "success" to the result if not already present.

    Example:
        @handle_tool_errors
        async def my_tool(param: str) -> dict[str, Any]:
            # If this raises, caller gets {"status": "error", "message": "...", ...}
            result = await do_something(param)
            return {"data": result}
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        tool_name = func.__name__
        try:
            result = await func(*args, **kwargs)
            if isinstance(result, dict) and "status" not in result:
                result["status"] = "success"
            return result
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            logger.error(f"Tool {tool_name} HTTP {status}: {e}")
            if status == 401:
                return {
                    "status": "error",
                    "message": "Authentication required",
                    "error_type": "AuthenticationError",
                }
            if status == 403:
                return {
                    "status": "error",
                    "message": "Access forbidden",
                    "error_type": "ForbiddenError",
                }
            if status == 404:
                return {
                    "status": "error",
                    "message": "Resource not found",
                    "error_type": "NotFoundError",
                }
            return {
                "status": "error",
                "message": f"HTTP {status}: {e}",
                "error_type": "HTTPError",
            }
        except httpx.RequestError as e:
            logger.error(f"Tool {tool_name} request failed: {e}")
            return {
                "status": "error",
                "message": f"Request failed: {e}",
                "error_type": "RequestError",
            }
        except ValueError as e:
            logger.error(f"Tool {tool_name} validation error: {e}")
            return {
                "status": "error",
                "message": str(e),
                "error_type": "ValidationError",
            }
        except Exception as e:
            logger.exception(f"Tool {tool_name} unexpected error: {e}")
            return {
                "status": "error",
                "message": f"Unexpected error: {e}",
                "error_type": type(e).__name__,
            }

    return wrapper  # type: ignore[return-value]
