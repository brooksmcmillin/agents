"""HTTP middleware for the API server.

Contains:
- CORS configuration
- Correlation ID middleware for distributed tracing
"""

import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from agent_framework.logging import correlation_id_var
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------


def _validate_cors_origin(origin: str) -> bool:
    """Validate a CORS origin string.

    Rejects wildcards, empty strings, and non-http(s) schemes.
    """
    if not origin or origin == "*":
        return False
    return origin.startswith(("http://", "https://"))


def setup_cors(app: Any) -> list[str]:
    """Configure CORS middleware on the FastAPI app.

    Returns:
        The list of allowed origins.
    """
    allow_origins = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:8080",  # Production (same origin)
        "http://127.0.0.1:5173",  # Vite dev server (IP)
        "http://127.0.0.1:8080",  # Production (IP)
    ]
    if extra_origins := os.getenv("CORS_ALLOWED_ORIGINS"):
        for origin in extra_origins.split(","):
            origin = origin.strip()
            if origin and _validate_cors_origin(origin):
                allow_origins.append(origin)
            elif origin:
                logger.warning("Ignoring invalid CORS origin: %s", origin)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return allow_origins


# ---------------------------------------------------------------------------
# Correlation ID Middleware (for distributed tracing)
# ---------------------------------------------------------------------------

# Allow alphanumeric characters and hyphens, 1-64 chars.
# Rejects header injection / log forgery payloads.
_CORRELATION_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


def setup_correlation_id_middleware(app: Any) -> None:
    """Register the correlation ID middleware on the FastAPI app."""

    @app.middleware("http")
    async def add_correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Add correlation ID to each request for distributed tracing.

        If X-Correlation-ID header is present and passes validation, use it.
        Otherwise, generate a new UUID. The correlation ID is stored in a
        ContextVar for use by logging throughout the request lifecycle.
        """
        raw_id = request.headers.get("X-Correlation-ID")
        if raw_id and _CORRELATION_ID_RE.match(raw_id):
            correlation_id = raw_id
        else:
            correlation_id = str(uuid.uuid4())

        # Set correlation ID in context var for logging
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
            # Add correlation ID to response headers for tracing
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            # Reset to prevent context leaking between requests
            correlation_id_var.reset(token)
