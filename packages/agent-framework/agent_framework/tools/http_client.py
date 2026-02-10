"""HTTP client tools for security testing.

Provides 6 MCP tools for making authenticated HTTP requests during
authorized penetration testing. No SSRF validation -- these are
intentionally unrestricted pentesting tools.

Target allowlist is enforced via REDTEAM_ALLOWED_TARGETS env var.
Session state (cookies, headers) is stored module-level so it survives
MCP reconnections.
"""

import asyncio
import base64
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session state (module-level, survives MCP reconnects)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}


def _get_session(name: str) -> dict[str, Any]:
    """Get or create a named session's state."""
    if name not in _sessions:
        _sessions[name] = {"cookies": {}, "headers": {}}
    return _sessions[name]


# ---------------------------------------------------------------------------
# Target allowlist
# ---------------------------------------------------------------------------


def _check_target_allowed(url: str) -> None:
    """Raise ValueError if the URL is not in the allowed targets list."""
    allowed = os.getenv("REDTEAM_ALLOWED_TARGETS", "")
    if not allowed:
        return  # empty = allow all
    prefixes = [p.strip() for p in allowed.split(",") if p.strip()]
    for prefix in prefixes:
        if url.startswith(prefix):
            return
    raise ValueError(f"URL {url!r} not in REDTEAM_ALLOWED_TARGETS. Allowed prefixes: {prefixes}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_cookies(jar: httpx.Cookies) -> dict[str, str]:
    """Convert httpx cookie jar to a plain dict."""
    return {c.name: c.value for c in jar.jar if c.value is not None}


def _serialize_headers(headers: httpx.Headers) -> dict[str, str]:
    """Convert httpx headers to a plain dict (lowercase keys)."""
    return dict(headers.items())


def _build_client(
    session_name: str | None = None,
    extra_headers: dict[str, str] | None = None,
    extra_cookies: dict[str, str] | None = None,
    follow_redirects: bool = True,
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    """Build an httpx client with session state applied."""
    headers = {}
    cookies = {}

    if session_name:
        sess = _get_session(session_name)
        headers.update(sess.get("headers", {}))
        cookies.update(sess.get("cookies", {}))

    if extra_headers:
        headers.update(extra_headers)
    if extra_cookies:
        cookies.update(extra_cookies)

    return httpx.AsyncClient(
        headers=headers,
        cookies=cookies,
        follow_redirects=follow_redirects,
        timeout=timeout,
        verify=True,
    )


def _truncate(text: str, max_len: int = 10000) -> str:
    """Truncate response body to keep tool results reasonable."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n[... truncated, {len(text)} total chars]"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def http_request(
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
        session_name=session,
        extra_headers=headers,
        extra_cookies=cookies,
        follow_redirects=follow_redirects,
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
        response = await client.request(method.upper(), url, **kwargs)
        elapsed = round(time.monotonic() - start, 3)

    # Update session cookies
    if session:
        sess = _get_session(session)
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
        "body": _truncate(response.text, max_response_length),
        "elapsed_seconds": elapsed,
        "cookies_set": _serialize_cookies(response.cookies),
        "redirect_history": redirect_history,
        "final_url": str(response.url),
    }


async def http_session_login(
    url: str,
    credentials: dict[str, str],
    session: str = "default",
    method: str = "POST",
    content_type: str = "json",
) -> dict[str, Any]:
    """POST credentials to a login endpoint and store session cookies.

    Args:
        url: Login endpoint URL
        credentials: Dict of credential fields (e.g. {"username": "x", "password": "y"})
        session: Named session to store cookies in (default: "default")
        method: HTTP method (default: POST)
        content_type: "json" or "form" (default: "json")

    Returns:
        Dict with status, cookies_stored, session_name, response body snippet
    """
    _check_target_allowed(url)

    async with _build_client(
        session_name=session,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        kwargs: dict[str, Any] = {}
        if content_type == "form":
            kwargs["data"] = credentials
        else:
            kwargs["json"] = credentials

        start = time.monotonic()
        response = await client.request(method.upper(), url, **kwargs)
        elapsed = round(time.monotonic() - start, 3)

    # Store all cookies in the session
    sess = _get_session(session)
    new_cookies = _serialize_cookies(response.cookies)
    sess["cookies"].update(new_cookies)

    return {
        "status": response.status_code,
        "session_name": session,
        "cookies_stored": new_cookies,
        "total_session_cookies": dict(sess["cookies"]),
        "body_snippet": _truncate(response.text, 2000),
        "elapsed_seconds": elapsed,
    }


async def http_upload_file(
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
        url: Upload endpoint URL
        file_content_base64: Base64-encoded file content
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

    file_bytes = base64.b64decode(file_content_base64)

    files = {field_name: (filename, file_bytes, content_type)}
    data = extra_fields or {}

    async with _build_client(
        session_name=session,
        extra_headers=headers,
        follow_redirects=True,
        timeout=60.0,
    ) as client:
        start = time.monotonic()
        response = await client.post(url, files=files, data=data)
        elapsed = round(time.monotonic() - start, 3)

    if session:
        sess = _get_session(session)
        sess["cookies"].update(_serialize_cookies(response.cookies))

    return {
        "status": response.status_code,
        "headers": _serialize_headers(response.headers),
        "body": _truncate(response.text, 5000),
        "elapsed_seconds": elapsed,
    }


async def http_inspect_headers(
    url: str,
    method: str = "GET",
    origin: str | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Analyze response headers for security configuration.

    Checks security headers (CSP, HSTS, X-Frame-Options), CORS configuration,
    and cookie attributes (HttpOnly, Secure, SameSite).

    Args:
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
        session_name=session,
        extra_headers=extra_headers,
        follow_redirects=True,
        timeout=15.0,
    ) as client:
        response = await client.request(method.upper(), url)

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

    # Cookie analysis
    cookie_analysis = []
    for cookie_header in h.get_list("set-cookie"):
        parts = cookie_header.split(";")
        cookie_name = parts[0].split("=")[0].strip() if parts else "unknown"
        attrs = [p.strip().lower() for p in parts[1:]]
        cookie_analysis.append(
            {
                "name": cookie_name,
                "httponly": any("httponly" in a for a in attrs),
                "secure": any("secure" in a for a in attrs),
                "samesite": next(
                    (a.split("=")[1].strip() for a in attrs if "samesite" in a),
                    None,
                ),
                "raw": cookie_header,
            }
        )

    return {
        "status": response.status_code,
        "security_headers": security_headers,
        "cors_headers": cors_headers,
        "cookie_analysis": cookie_analysis,
        "all_headers": _serialize_headers(h),
    }


async def http_fuzz_parameter(
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
            session_name=session,
            extra_headers=headers,
            follow_redirects=True,
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
                response = await client.request(method.upper(), url, **kwargs)
                elapsed = round(time.monotonic() - start, 3)
                results.append(
                    {
                        "payload": payload,
                        "status": response.status_code,
                        "body_snippet": _truncate(response.text, max_response_snippet),
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
    url: str,
    method: str = "GET",
    num_requests: int = 20,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Send rapid identical requests to test rate limiting.

    Args:
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
            session_name=session,
            extra_headers=headers,
            follow_redirects=True,
            timeout=10.0,
        ) as client:
            kwargs: dict[str, Any] = {}
            if body is not None:
                kwargs["json"] = body

            start = time.monotonic()
            try:
                response = await client.request(method.upper(), url, **kwargs)
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
            "persist cookies across requests."
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
            "JSON and form-encoded credential submission."
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
            "with configurable filename, MIME type, and form field name. Can include "
            "additional form fields."
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
                    "description": "Base64-encoded file content",
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
]
