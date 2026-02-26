"""HTTP client tools for security testing.

Provides 7 MCP tools for making authenticated HTTP requests during
authorized penetration testing.

Target allowlist is enforced via REDTEAM_ALLOWED_TARGETS env var (fail-secure:
requests are denied when the env var is not set).

Session state (cookies) is stored module-level so it survives MCP reconnections.
Sessions are keyed by agent_name to provide isolation in multi-tenant deployments,
and expire after a configurable TTL.
"""

import asyncio
import base64
import binascii
import logging
import os
import posixpath
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Max file upload size (10 MB)
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# Max response body to read before truncation (5 MB)
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Default session TTL in seconds (1 hour)
_SESSION_TTL_SECONDS = 3600

# Credential field names to redact in responses.
# All matching is done after normalizing hyphens to underscores and lowercasing,
# so "api-key", "API_KEY", and "Api-Key" all match "api_key".
_SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "auth_token",
        "private_key",
        "session_token",
        "client_secret",
        "cookie",
        "set_cookie",
        "x_api_key",
        "x_auth_token",
        "bearer",
    }
)

# ---------------------------------------------------------------------------
# Session state (module-level, survives MCP reconnects)
#
# Sessions are keyed by "{agent_name}:{session_name}". In stdio MCP mode
# (default), each agent instance runs its own MCP server process, so
# module-level state is inherently isolated per user/conversation.
#
# Limitation: In shared remote MCP deployments, agents with the same
# agent_name (e.g., multiple users using "RedTeamAgent") will share
# session state. Full multi-tenant isolation requires the MCP framework
# to inject a unique caller ID (e.g., conversation_id) in addition to
# agent_name.
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}


def _session_key(agent_name: str, name: str) -> str:
    """Build an isolated session key scoped to the agent/user context."""
    return f"{agent_name}:{name}"


def _get_session(agent_name: str, name: str) -> dict[str, Any]:
    """Get or create a named session's state, scoped to agent_name.

    Note: If a session was just expired by _expire_sessions(), this will
    create a fresh empty session. This is intentional -- expired sessions
    should not retain stale cookies. The caller gets a clean session and
    will need to re-authenticate.
    """
    key = _session_key(agent_name, name)
    now = time.monotonic()
    if key not in _sessions:
        _sessions[key] = {"cookies": {}, "created_at": now, "last_used": now}
    sess = _sessions[key]
    # Refresh last_used atomically with access (prevents expiry race)
    sess["last_used"] = now
    return sess


def _expire_sessions() -> None:
    """Remove sessions older than TTL."""
    now = time.monotonic()
    expired = [
        k for k, v in _sessions.items() if (now - v.get("last_used", 0)) > _SESSION_TTL_SECONDS
    ]
    for k in expired:
        del _sessions[k]


# ---------------------------------------------------------------------------
# Target allowlist
# ---------------------------------------------------------------------------


def _check_target_allowed(url: str) -> None:
    """Raise ValueError if the URL is not in the allowed targets list.

    Fail-secure: denies all requests when REDTEAM_ALLOWED_TARGETS is not set.
    Uses proper URL parsing to prevent subdomain bypass attacks.
    """
    allowed = os.getenv("REDTEAM_ALLOWED_TARGETS", "")
    if not allowed:
        raise ValueError(
            "REDTEAM_ALLOWED_TARGETS is not set. "
            "Configure it with comma-separated URL prefixes to allow requests."
        )

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid URL: {url!r}")

    prefixes = [p.strip() for p in allowed.split(",") if p.strip()]
    for prefix in prefixes:
        prefix_parsed = urlparse(prefix)
        if not prefix_parsed.scheme or not prefix_parsed.hostname:
            continue
        # Scheme must match
        if parsed.scheme != prefix_parsed.scheme:
            continue
        # Hostname must match exactly (no subdomain bypass)
        if parsed.hostname != prefix_parsed.hostname:
            continue
        # Port must match (urlparse returns None for default ports)
        if parsed.port != prefix_parsed.port:
            continue
        # Path must start with allowed prefix path (default '/')
        # Normalize to prevent traversal bypass (e.g. /api/../admin)
        prefix_path = posixpath.normpath(prefix_parsed.path or "/")
        request_path = posixpath.normpath(parsed.path or "/")
        # Exact match or proper sub-path (boundary check prevents
        # /api/v1 matching /api/v1admin)
        if request_path == prefix_path or request_path.startswith(prefix_path + "/"):
            return

    raise ValueError(f"URL {url!r} not in REDTEAM_ALLOWED_TARGETS. Allowed prefixes: {prefixes}")


_MAX_REDIRECTS = 10


async def _safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    follow_redirects: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    """Make a request with pre-validated redirect following.

    Instead of letting httpx auto-follow redirects (which makes the request
    before we can validate the Location), this follows redirects manually,
    validating each hop's target against the allowlist BEFORE making the
    request to it.

    Returns the final response with a populated ``history`` list matching
    the httpx convention.
    """
    if not follow_redirects:
        return await client.request(method, url, **kwargs)

    history: list[httpx.Response] = []
    current_url = url
    current_method = method

    for _ in range(_MAX_REDIRECTS):
        resp = await client.request(current_method, current_url, **kwargs)

        if resp.status_code not in (301, 302, 303, 307, 308):
            resp.history = history  # type: ignore[attr-defined]
            return resp

        location = resp.headers.get("location")
        if not location:
            resp.history = history  # type: ignore[attr-defined]
            return resp

        # Resolve relative redirects
        next_url = str(resp.url.join(location))

        # Validate BEFORE following
        _check_target_allowed(next_url)

        history.append(resp)

        # 303 always becomes GET; 301/302 become GET for POST (browser behavior)
        if resp.status_code == 303 or (resp.status_code in (301, 302) and current_method == "POST"):
            current_method = "GET"
            kwargs.pop("content", None)
            kwargs.pop("json", None)
            kwargs.pop("data", None)
            kwargs.pop("files", None)

        current_url = next_url

    raise httpx.TooManyRedirects(
        f"Exceeded {_MAX_REDIRECTS} redirects",
        request=httpx.Request(method, url),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_cookies(jar: httpx.Cookies) -> dict[str, str]:
    """Convert httpx cookie jar to a plain dict."""
    return {c.name: c.value for c in jar.jar if c.value is not None}


def _serialize_headers(headers: httpx.Headers) -> dict[str, str]:
    """Convert httpx headers to a plain dict (lowercase keys)."""
    return dict(headers.items())


def _redact_sensitive(data: dict[str, Any]) -> dict[str, str]:
    """Redact values of sensitive fields (passwords, tokens, etc.).

    Normalizes hyphens to underscores before matching, so "api-key",
    "Api-Key", and "API_KEY" all match the canonical "api_key".
    """
    redacted: dict[str, str] = {}
    for k, v in data.items():
        normalized = k.lower().replace("-", "_")
        if normalized in _SENSITIVE_FIELDS:
            redacted[k] = "[REDACTED]"
        else:
            redacted[k] = str(v)
    return redacted


def _build_client(
    agent_name: str,
    session_name: str | None = None,
    extra_headers: dict[str, str] | None = None,
    extra_cookies: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    """Build an httpx client with session state applied.

    Always disables httpx auto-redirects. Redirect following is handled
    by ``_safe_request()`` which validates each hop against the allowlist
    before making the request.
    """
    _expire_sessions()

    headers: dict[str, str] = {}
    cookies: dict[str, str] = {}

    if session_name:
        sess = _get_session(agent_name, session_name)
        cookies.update(sess.get("cookies", {}))

    if extra_headers:
        headers.update(extra_headers)
    if extra_cookies:
        cookies.update(extra_cookies)

    return httpx.AsyncClient(
        headers=headers,
        cookies=cookies,
        follow_redirects=False,
        timeout=timeout,
        verify=True,
    )


async def _safe_read_response(response: httpx.Response, max_len: int = 10000) -> str:
    """Read response text with size guard to prevent memory exhaustion.

    Reads at most _MAX_RESPONSE_BYTES before decoding, then truncates to max_len.
    """
    # If response is already read (not streaming), use it directly but guard size
    body_bytes = response.content
    if len(body_bytes) > _MAX_RESPONSE_BYTES:
        text = body_bytes[:_MAX_RESPONSE_BYTES].decode(
            response.encoding or "utf-8", errors="replace"
        )
        return text[:max_len] + f"\n\n[... truncated, response was {len(body_bytes)} bytes]"

    text = response.text
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n[... truncated, {len(text)} total chars]"


def _parse_cookie_header(cookie_header: str) -> dict[str, Any]:
    """Safely parse a Set-Cookie header into structured analysis.

    Handles malformed cookies without raising exceptions.
    """
    parts = cookie_header.split(";")

    # Parse cookie name from "name=value" (first part)
    cookie_name = "unknown"
    if parts:
        name_value = parts[0].strip()
        eq_idx = name_value.find("=")
        if eq_idx > 0:
            cookie_name = name_value[:eq_idx].strip()
        elif name_value:
            cookie_name = name_value

    # Parse attributes - use exact matching, not substring
    attrs_raw = [p.strip() for p in parts[1:]]
    attrs_lower = [a.lower() for a in attrs_raw]

    httponly = False
    secure = False
    samesite = None

    for attr in attrs_lower:
        attr_stripped = attr.strip()
        if attr_stripped == "httponly":
            httponly = True
        elif attr_stripped == "secure":
            secure = True
        elif attr_stripped.startswith("samesite="):
            eq_idx = attr_stripped.find("=")
            if eq_idx >= 0 and eq_idx + 1 < len(attr_stripped):
                samesite = attr_stripped[eq_idx + 1 :].strip()

    return {
        "name": cookie_name,
        "httponly": httponly,
        "secure": secure,
        "samesite": samesite,
        "raw": cookie_header,
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

# All tools accept agent_name as their first parameter. This is injected
# by the Agent class automatically and is used for session isolation.


async def http_request(
    agent_name: str,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, str] | None = None,
    raw_body: str | None = None,
    follow_redirects: bool = True,
    session: str | None = None,
    timeout: float = 30.0,
    max_response_length: int = 10000,
) -> dict[str, Any]:
    """Make an HTTP request with full control over method, headers, body, and cookies.

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        url: Target URL
        method: HTTP method (GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD)
        headers: Extra request headers
        cookies: Extra cookies to send
        json_body: JSON request body (sets Content-Type: application/json)
        form_body: Form-encoded request body
        raw_body: Raw string request body
        follow_redirects: Whether to follow redirects (default: true)
        session: Named session to use/update cookies
        timeout: Request timeout in seconds
        max_response_length: Max response body length to return

    Returns:
        Dict with status, headers, body, timing, cookies_set, redirect_history
    """
    _check_target_allowed(url)

    async with _build_client(
        agent_name=agent_name,
        session_name=session,
        extra_headers=headers,
        extra_cookies=cookies,
        timeout=timeout,
    ) as client:
        kwargs: dict[str, Any] = {}
        if json_body is not None:
            kwargs["json"] = json_body
        elif form_body is not None:
            kwargs["data"] = form_body
        elif raw_body is not None:
            kwargs["content"] = raw_body

        start = time.monotonic()
        response = await _safe_request(
            client, method.upper(), url, follow_redirects=follow_redirects, **kwargs
        )
        elapsed = round(time.monotonic() - start, 3)

    # Update session cookies
    if session:
        sess = _get_session(agent_name, session)
        sess["cookies"].update(_serialize_cookies(response.cookies))

    # Build redirect history
    redirect_history = []
    if response.history:
        for r in response.history:
            redirect_history.append(
                {
                    "status": r.status_code,
                    "url": str(r.url),
                    "location": r.headers.get("location", ""),
                }
            )

    return {
        "status": response.status_code,
        "headers": _serialize_headers(response.headers),
        "body": await _safe_read_response(response, max_response_length),
        "elapsed_seconds": elapsed,
        "cookies_set": _serialize_cookies(response.cookies),
        "redirect_history": redirect_history,
        "final_url": str(response.url),
    }


async def http_session_login(
    agent_name: str,
    url: str,
    credentials: dict[str, str],
    session: str = "default",
    method: str = "POST",
    content_type: str = "json",
) -> dict[str, Any]:
    """POST credentials to a login endpoint and store session cookies.

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        url: Login endpoint URL
        credentials: Dict of credential fields (e.g. {"username": "x", "password": "y"})
        session: Named session to store cookies in (default: "default")
        method: HTTP method (default: POST)
        content_type: "json" or "form" (default: "json")

    Returns:
        Dict with status, cookies_stored, session_name, response body snippet.
        Credential values are redacted in the response.
    """
    _check_target_allowed(url)

    async with _build_client(
        agent_name=agent_name,
        session_name=session,
        timeout=30.0,
    ) as client:
        kwargs: dict[str, Any] = {}
        if content_type == "form":
            kwargs["data"] = credentials
        else:
            kwargs["json"] = credentials

        start = time.monotonic()
        response = await _safe_request(client, method.upper(), url, **kwargs)
        elapsed = round(time.monotonic() - start, 3)

    # Store all cookies in the session
    sess = _get_session(agent_name, session)
    new_cookies = _serialize_cookies(response.cookies)
    sess["cookies"].update(new_cookies)

    return {
        "status": response.status_code,
        "session_name": session,
        "credentials_sent": _redact_sensitive(credentials),
        "cookies_stored": new_cookies,
        "total_session_cookies": len(sess["cookies"]),
        "body_snippet": await _safe_read_response(response, 2000),
        "elapsed_seconds": elapsed,
    }


async def http_upload_file(
    agent_name: str,
    url: str,
    file_content_base64: str,
    filename: str,
    content_type: str = "application/octet-stream",
    field_name: str = "file",
    extra_fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Upload a file via multipart form data.

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        url: Upload endpoint URL
        file_content_base64: Base64-encoded file content (max 10 MB decoded)
        filename: Name of the file to upload
        content_type: MIME type of the file
        field_name: Form field name for the file (default: "file")
        extra_fields: Additional form fields to include
        headers: Extra request headers
        session: Named session for cookies

    Returns:
        Dict with status, headers, body snippet
    """
    _check_target_allowed(url)

    try:
        file_bytes = base64.b64decode(file_content_base64)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"Invalid base64 content: {e}")

    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise ValueError(
            f"File too large: {len(file_bytes)} bytes (max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)"
        )

    # Sanitize filename: strip null bytes and limit length
    filename = filename.replace("\x00", "")
    if len(filename) > 255:
        raise ValueError(f"Filename too long: {len(filename)} chars (max 255)")
    if not filename:
        raise ValueError("Filename cannot be empty")

    files = {field_name: (filename, file_bytes, content_type)}
    data = extra_fields or {}

    async with _build_client(
        agent_name=agent_name,
        session_name=session,
        extra_headers=headers,
        timeout=60.0,
    ) as client:
        start = time.monotonic()
        response = await _safe_request(client, "POST", url, files=files, data=data)
        elapsed = round(time.monotonic() - start, 3)

    if session:
        sess = _get_session(agent_name, session)
        sess["cookies"].update(_serialize_cookies(response.cookies))

    return {
        "status": response.status_code,
        "headers": _serialize_headers(response.headers),
        "body": await _safe_read_response(response, 5000),
        "elapsed_seconds": elapsed,
    }


async def http_inspect_headers(
    agent_name: str,
    url: str,
    method: str = "GET",
    origin: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Analyze response headers for security configuration.

    Checks security headers (CSP, HSTS, X-Frame-Options), CORS configuration,
    and cookie attributes (HttpOnly, Secure, SameSite).

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        url: Target URL
        method: HTTP method (default: GET). Use OPTIONS for CORS preflight.
        origin: Custom Origin header for CORS testing
        session: Named session for cookies

    Returns:
        Dict with security_headers, cors_headers, cookie_analysis, all_headers
    """
    _check_target_allowed(url)

    extra_headers: dict[str, str] = {}
    if origin:
        extra_headers["Origin"] = origin
    if method.upper() == "OPTIONS":
        extra_headers["Access-Control-Request-Method"] = "POST"
        extra_headers["Access-Control-Request-Headers"] = "Content-Type, Authorization"

    async with _build_client(
        agent_name=agent_name,
        session_name=session,
        extra_headers=extra_headers,
        timeout=15.0,
    ) as client:
        response = await _safe_request(client, method.upper(), url)

    h = response.headers

    # Security headers check
    security_header_names = [
        "content-security-policy",
        "strict-transport-security",
        "x-frame-options",
        "x-content-type-options",
        "x-xss-protection",
        "referrer-policy",
        "permissions-policy",
    ]
    security_headers: dict[str, str | None] = {}
    for name in security_header_names:
        security_headers[name] = h.get(name)

    # CORS headers
    cors_header_names = [
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "access-control-allow-credentials",
        "access-control-expose-headers",
        "access-control-max-age",
    ]
    cors_headers: dict[str, str | None] = {}
    for name in cors_header_names:
        cors_headers[name] = h.get(name)

    # Cookie analysis - safe parsing
    cookie_analysis = []
    for cookie_header in h.get_list("set-cookie"):
        cookie_analysis.append(_parse_cookie_header(cookie_header))

    return {
        "status": response.status_code,
        "security_headers": security_headers,
        "cors_headers": cors_headers,
        "cookie_analysis": cookie_analysis,
        "all_headers": _serialize_headers(h),
    }


async def http_fuzz_parameter(
    agent_name: str,
    url: str,
    method: str = "GET",
    parameter: str = "",
    payloads: list[str] | None = None,
    inject_in: str = "query",
    base_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    session: str | None = None,
    delay_ms: int = 100,
    max_response_snippet: int = 500,
) -> dict[str, Any]:
    """Send variations of a parameter to detect injection vulnerabilities.

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        url: Target URL
        method: HTTP method
        parameter: Parameter name to fuzz
        payloads: List of payload strings to inject
        inject_in: Where to inject - "query", "body_json", or "body_form"
        base_params: Other parameters to include alongside the fuzzed one
        headers: Extra request headers
        session: Named session for cookies
        delay_ms: Delay between requests in milliseconds (default: 100)
        max_response_snippet: Max chars of response body per result

    Returns:
        Dict with results list (per-payload status, snippet, timing) and summary
    """
    _check_target_allowed(url)

    if not payloads:
        payloads = []

    results = []
    for i, payload in enumerate(payloads):
        if i > 0 and delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        params = dict(base_params or {})
        params[parameter] = payload

        async with _build_client(
            agent_name=agent_name,
            session_name=session,
            extra_headers=headers,
            timeout=15.0,
        ) as client:
            kwargs: dict[str, Any] = {}
            if inject_in == "query":
                kwargs["params"] = params
            elif inject_in == "body_json":
                kwargs["json"] = params
            elif inject_in == "body_form":
                kwargs["data"] = params

            start = time.monotonic()
            try:
                response = await _safe_request(client, method.upper(), url, **kwargs)
                elapsed = round(time.monotonic() - start, 3)
                results.append(
                    {
                        "payload": payload,
                        "status": response.status_code,
                        "body_snippet": await _safe_read_response(response, max_response_snippet),
                        "elapsed_seconds": elapsed,
                        "content_length": len(response.content),
                    }
                )
            except Exception as e:
                elapsed = round(time.monotonic() - start, 3)
                results.append(
                    {
                        "payload": payload,
                        "error": str(e),
                        "elapsed_seconds": elapsed,
                    }
                )

    # Summary
    status_counts: dict[int, int] = {}
    for r in results:
        s = r.get("status", 0)
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "parameter": parameter,
        "inject_in": inject_in,
        "total_payloads": len(payloads),
        "results": results,
        "status_distribution": status_counts,
    }


async def http_check_rate_limit(
    agent_name: str,
    url: str,
    method: str = "GET",
    num_requests: int = 20,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Send rapid identical requests to test rate limiting.

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        url: Target URL
        method: HTTP method
        num_requests: Number of requests to send (default: 20, max: 100)
        headers: Extra request headers
        body: JSON body to send with each request
        session: Named session for cookies

    Returns:
        Dict with per-request status/timing, first_limited (request number),
        and rate_limit_headers found
    """
    _check_target_allowed(url)

    num_requests = min(num_requests, 100)

    results = []
    first_limited = None
    rate_limit_headers_found: dict[str, str] = {}

    for i in range(num_requests):
        async with _build_client(
            agent_name=agent_name,
            session_name=session,
            extra_headers=headers,
            timeout=10.0,
        ) as client:
            kwargs: dict[str, Any] = {}
            if body is not None:
                kwargs["json"] = body

            start = time.monotonic()
            try:
                response = await _safe_request(client, method.upper(), url, **kwargs)
                elapsed = round(time.monotonic() - start, 3)

                result: dict[str, Any] = {
                    "request_number": i + 1,
                    "status": response.status_code,
                    "elapsed_seconds": elapsed,
                }

                # Check for rate limiting indicators
                if response.status_code == 429:
                    if first_limited is None:
                        first_limited = i + 1
                    result["rate_limited"] = True

                # Capture rate limit headers
                for header_name in [
                    "retry-after",
                    "x-ratelimit-limit",
                    "x-ratelimit-remaining",
                    "x-ratelimit-reset",
                    "ratelimit-limit",
                    "ratelimit-remaining",
                    "ratelimit-reset",
                ]:
                    val = response.headers.get(header_name)
                    if val:
                        rate_limit_headers_found[header_name] = val

                results.append(result)

            except Exception as e:
                elapsed = round(time.monotonic() - start, 3)
                results.append(
                    {
                        "request_number": i + 1,
                        "error": str(e),
                        "elapsed_seconds": elapsed,
                    }
                )

    return {
        "url": url,
        "method": method.upper(),
        "total_requests": num_requests,
        "first_rate_limited_at": first_limited,
        "rate_limit_headers": rate_limit_headers_found,
        "results": results,
    }


async def http_clear_session(
    agent_name: str,
    session: str = "default",
) -> dict[str, Any]:
    """Clear a named session's cookies and state.

    Args:
        agent_name: Injected by framework - agent/user context for session isolation
        session: Named session to clear (default: "default")

    Returns:
        Dict with cleared session name and status
    """
    key = _session_key(agent_name, session)
    had_session = key in _sessions
    if had_session:
        del _sessions[key]
    return {
        "session_name": session,
        "cleared": had_session,
        "active_sessions": len([k for k in _sessions if k.startswith(f"{agent_name}:")]),
    }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "http_request",
        "description": (
            "Make an HTTP request with full control over method, headers, cookies, "
            "and body format (JSON, form, raw). Returns status code, response headers, "
            "body, timing, cookies set, and redirect history. Use a named session to "
            "persist cookies across requests. Redirects are validated against the "
            "target allowlist."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
                    "default": "GET",
                    "description": "HTTP method",
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Extra request headers",
                },
                "cookies": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Extra cookies to send",
                },
                "json_body": {
                    "type": "object",
                    "description": "JSON request body",
                },
                "form_body": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Form-encoded request body",
                },
                "raw_body": {
                    "type": "string",
                    "description": "Raw string request body",
                },
                "follow_redirects": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether to follow redirects",
                },
                "session": {
                    "type": "string",
                    "description": "Named session for cookie persistence across requests",
                },
                "timeout": {
                    "type": "number",
                    "default": 30.0,
                    "description": "Request timeout in seconds",
                },
                "max_response_length": {
                    "type": "integer",
                    "default": 10000,
                    "description": "Max response body length to return",
                },
            },
            "required": ["url"],
        },
        "handler": http_request,
    },
    {
        "name": "http_session_login",
        "description": (
            "POST credentials to a login endpoint and store the resulting session "
            "cookies in a named session for reuse in subsequent requests. Supports "
            "JSON and form-encoded credential submission. Credential values are "
            "automatically redacted in the response."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Login endpoint URL",
                },
                "credentials": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": 'Credential fields (e.g. {"username": "x", "password": "y"})',
                },
                "session": {
                    "type": "string",
                    "default": "default",
                    "description": "Named session to store cookies in",
                },
                "method": {
                    "type": "string",
                    "default": "POST",
                    "description": "HTTP method",
                },
                "content_type": {
                    "type": "string",
                    "enum": ["json", "form"],
                    "default": "json",
                    "description": "Credential encoding format",
                },
            },
            "required": ["url", "credentials"],
        },
        "handler": http_session_login,
    },
    {
        "name": "http_upload_file",
        "description": (
            "Upload a file via multipart form data. Accepts base64-encoded file content "
            "(max 10 MB) with configurable filename, MIME type, and form field name. "
            "Can include additional form fields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Upload endpoint URL",
                },
                "file_content_base64": {
                    "type": "string",
                    "description": "Base64-encoded file content (max 10 MB decoded)",
                },
                "filename": {
                    "type": "string",
                    "description": "Name of the file to upload",
                },
                "content_type": {
                    "type": "string",
                    "default": "application/octet-stream",
                    "description": "MIME type of the file",
                },
                "field_name": {
                    "type": "string",
                    "default": "file",
                    "description": "Form field name for the file upload",
                },
                "extra_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Additional form fields to include",
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Extra request headers",
                },
                "session": {
                    "type": "string",
                    "description": "Named session for cookies",
                },
            },
            "required": ["url", "file_content_base64", "filename"],
        },
        "handler": http_upload_file,
    },
    {
        "name": "http_inspect_headers",
        "description": (
            "Analyze response headers for security configuration. Checks security "
            "headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options), CORS "
            "configuration (with custom Origin for testing), and cookie attributes "
            "(HttpOnly, Secure, SameSite)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL",
                },
                "method": {
                    "type": "string",
                    "default": "GET",
                    "description": "HTTP method (use OPTIONS for CORS preflight)",
                },
                "origin": {
                    "type": "string",
                    "description": "Custom Origin header for CORS testing",
                },
                "session": {
                    "type": "string",
                    "description": "Named session for cookies",
                },
            },
            "required": ["url"],
        },
        "handler": http_inspect_headers,
    },
    {
        "name": "http_fuzz_parameter",
        "description": (
            "Send N variations of a single parameter to detect injection vulnerabilities. "
            "Returns per-payload status codes, response snippets, and timing. Supports "
            "injection in query string, JSON body, or form body with configurable delay."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL",
                },
                "method": {
                    "type": "string",
                    "default": "GET",
                    "description": "HTTP method",
                },
                "parameter": {
                    "type": "string",
                    "description": "Parameter name to fuzz",
                },
                "payloads": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of payload strings to inject",
                },
                "inject_in": {
                    "type": "string",
                    "enum": ["query", "body_json", "body_form"],
                    "default": "query",
                    "description": "Where to inject the parameter",
                },
                "base_params": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Other parameters to include alongside the fuzzed one",
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Extra request headers",
                },
                "session": {
                    "type": "string",
                    "description": "Named session for cookies",
                },
                "delay_ms": {
                    "type": "integer",
                    "default": 100,
                    "description": "Delay between requests in milliseconds",
                },
                "max_response_snippet": {
                    "type": "integer",
                    "default": 500,
                    "description": "Max chars of response body per result",
                },
            },
            "required": ["url", "parameter", "payloads"],
        },
        "handler": http_fuzz_parameter,
    },
    {
        "name": "http_check_rate_limit",
        "description": (
            "Send N identical requests rapidly to test rate limiting. Reports which "
            "request number first triggered a 429, and extracts rate-limit headers "
            "(Retry-After, X-RateLimit-*)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL",
                },
                "method": {
                    "type": "string",
                    "default": "GET",
                    "description": "HTTP method",
                },
                "num_requests": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 100,
                    "description": "Number of requests to send",
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Extra request headers",
                },
                "body": {
                    "type": "object",
                    "description": "JSON body to send with each request",
                },
                "session": {
                    "type": "string",
                    "description": "Named session for cookies",
                },
            },
            "required": ["url"],
        },
        "handler": http_check_rate_limit,
    },
    {
        "name": "http_clear_session",
        "description": (
            "Clear a named session's cookies and state. Use this to log out, "
            "reset test state, or free resources. Returns the number of "
            "remaining active sessions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session": {
                    "type": "string",
                    "default": "default",
                    "description": "Named session to clear",
                },
            },
        },
        "handler": http_clear_session,
    },
]
