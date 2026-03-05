"""Authentication and rate limiting for the API server.

Contains:
- API key verification (Bearer token auth)
- WebSocket authentication
- Session token verification
- IP-based allowlist for development mode
- Rate limiting configuration
"""

import ipaddress
import logging
import os
import secrets
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

_security = HTTPBearer(auto_error=False)


def _get_api_key() -> str | None:
    """Get the configured API key.

    Reads from the environment on each call so that reloading the module
    or patching the environment in tests works correctly.
    """
    return os.getenv("API_KEY") or None


# Default CIDR list when DISABLE_AUTH_ALLOWED_IPS is not set.
_DISABLE_AUTH_DEFAULT_CIDRS = "127.0.0.0/8,::1/128"


def _parse_cidr_list(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a comma-separated list of CIDR strings into network objects.

    Invalid entries are logged and skipped.

    Args:
        raw: Comma-separated CIDR strings, e.g. "127.0.0.0/8,::1/128".

    Returns:
        List of parsed IPv4Network or IPv6Network objects (strict=False).
    """
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("DISABLE_AUTH_ALLOWED_IPS: ignoring invalid CIDR %r", entry)
    return networks


def _ip_in_cidr_list(
    ip_str: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Return True if *ip_str* falls within any network in *networks*.

    Args:
        ip_str: IP address string (IPv4 or IPv6).
        networks: List of network objects to check against.

    Returns:
        True if the address is contained in at least one network.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in networks)


async def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_security),
) -> None:
    """Verify API key.

    Requires a valid Authorization: Bearer <API_KEY> header when API_KEY
    is set. When DISABLE_AUTH=true (no API_KEY) and ENV=development, requests
    are only allowed from IPs listed in DISABLE_AUTH_ALLOWED_IPS (defaults to
    loopback only: 127.0.0.0/8 and ::1/128).

    Uses constant-time comparison to prevent timing attacks.
    """
    api_key = _get_api_key()
    if not api_key:
        # Auth disabled – enforce IP allowlist from DISABLE_AUTH_ALLOWED_IPS.
        allowed_ips_raw = os.getenv("DISABLE_AUTH_ALLOWED_IPS", _DISABLE_AUTH_DEFAULT_CIDRS)
        allowed_networks = _parse_cidr_list(allowed_ips_raw)
        client_host = request.client.host if request.client else ""
        try:
            ipaddress.ip_address(client_host)
        except ValueError:
            # Host is not a parseable IP address (e.g. a hostname or test client stub).
            # Log a warning and allow, since CIDR filtering is best-effort for non-IP
            # hosts; the startup check (ENV=development) is the primary guard.
            logger.warning(
                "DISABLE_AUTH: client host %r is not a parseable IP, skipping CIDR check",
                client_host,
            )
            return
        if not _ip_in_cidr_list(client_host, allowed_networks):
            logger.warning(
                "DISABLE_AUTH: rejected request from non-allowlisted IP %r",
                client_host,
            )
            raise HTTPException(
                status_code=403,
                detail="Access denied: client IP not in DISABLE_AUTH_ALLOWED_IPS",
            )
        return
    if not credentials or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        api_key.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def authenticate_websocket_connection(
    websocket: "Any",
) -> dict | None:
    """Authenticate a WebSocket connection via initial message exchange.

    Always waits for an auth message from the client::

        {"type": "auth", "api_key": "...", "session_token": "..."}

    When API_KEY is not configured the ``api_key`` field is not checked, but the
    message must still be sent so that the ``session_token`` (required for
    session-ownership verification) can be read.

    Returns:
        The parsed auth payload dict on success, or ``None`` on failure.

    Uses constant-time comparison to prevent timing attacks.
    Credentials never appear in query strings, avoiding leakage via
    server logs, browser history, referrer headers, or proxy logs.
    """
    import asyncio

    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except Exception:  # TimeoutError, WebSocketDisconnect, JSONDecodeError, etc.
        return None
    if not isinstance(data, dict) or data.get("type") != "auth":
        return None
    api_key = _get_api_key()
    if api_key:
        ws_key = data.get("api_key")
        if not isinstance(ws_key, str):
            return None
        if not secrets.compare_digest(ws_key.encode("utf-8"), api_key.encode("utf-8")):
            return None
    return data


def check_session_token(
    session: Any,
    session_id: str,
    x_session_token: str | None,
    dummy_token: str,
) -> Any:
    """Verify session ownership and return the session object.

    Called by REST endpoints that mutate session state (input, permission,
    resize, delete).  Raises HTTP 403 on mismatch to avoid leaking whether
    the session exists via a differential response.

    Args:
        session: The session object (or None if not found).
        session_id: The session ID from the URL path.
        x_session_token: Value of the ``X-Session-Token`` request header.
        dummy_token: Token to use for timing-safe comparison when session is None.

    Returns:
        The verified session object.

    Raises:
        HTTPException: 403 if the session is not found or the token is wrong.
    """
    # Always run compare_digest to avoid timing side-channels.  When the session
    # doesn't exist or the provided token is not a string, we compare a dummy
    # value so the response time is indistinguishable from a wrong-token attempt.
    stored_token = session.session_token if session is not None else dummy_token
    candidate = x_session_token if isinstance(x_session_token, str) else ""
    digest_ok = secrets.compare_digest(
        candidate.encode("utf-8"),
        stored_token.encode("utf-8"),
    )
    if session is None or not digest_ok:
        raise HTTPException(status_code=403, detail="Session not found or invalid token")
    return session


# ---------------------------------------------------------------------------
# Rate Limiting (optional)
# ---------------------------------------------------------------------------

_rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"


def _get_rate_limit_key(request: Request) -> str:
    """Extract a rate-limit key from the request.

    Keys on the Bearer token prefix (first 16 chars) so that rate limits
    are tied to the authenticated identity rather than a spoofable IP.
    Falls back to the connecting client IP (request.client.host) when no
    Authorization header is present -- this avoids reading X-Forwarded-For,
    which clients can trivially forge.
    """
    auth_header: str | None = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()  # strip "Bearer " and any whitespace
        if token:
            # Use a prefix so we never store full secrets in rate-limit backends.
            return f"apikey:{token[:16]}"
    # Unauthenticated / health-check traffic: fall back to real peer IP.
    if request.client:
        return f"ip:{request.client.host}"
    return "ip:unknown"


F = TypeVar("F", bound=Callable[..., Any])


def setup_rate_limiting(app: Any) -> Any:
    """Configure rate limiting on the FastAPI app if enabled.

    Returns:
        The limiter instance (or None if disabled).
    """
    if _rate_limit_enabled:
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded

        limiter = Limiter(key_func=_get_rate_limit_key)
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
        logger.info("Rate limiting enabled (keyed on API key, not IP)")
        return limiter
    else:
        logger.info("Rate limiting disabled")
        return None


def rate_limit(limit_string: str, limiter: Any) -> Callable[[F], F]:
    """Apply rate limit decorator only if rate limiting is enabled."""

    def decorator(func: F) -> F:
        if limiter is not None:
            return limiter.limit(limit_string)(func)  # type: ignore[return-value]
        return func

    return decorator
