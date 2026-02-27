"""Security utilities for the agents project.

This module provides security utilities including SSRF (Server-Side Request Forgery)
protection for web scraping operations.

TOCTOU Gap and DNS Rebinding Risk
----------------------------------
The naive SSRF protection pattern has a Time-Of-Check Time-Of-Use (TOCTOU) race
condition:

1. SSRFValidator.is_safe_url() resolves the hostname at *check* time using
   socket.getaddrinfo() and validates the resolved IPs against the blocklist.
2. httpx then opens the actual TCP connection at *fetch* time, which triggers a
   second DNS resolution inside the OS resolver / anyio / httpcore.

An attacker who controls a DNS server can exploit this gap with a DNS rebinding
attack:
  - Step 1: The attacker's domain resolves to a public IP during the check. The
    validator sees a safe IP and grants permission.
  - Step 2: The TTL expires (or a very short TTL was used). Before httpx opens
    the socket, the domain now resolves to an internal IP (e.g. 169.254.169.254
    for cloud metadata, or 192.168.x.x for internal services).
  - Step 3: httpx connects to the internal address, bypassing the SSRF guard.

Mitigation: SSRFTransport
--------------------------
``SSRFTransport`` is a custom httpx ``AsyncHTTPTransport`` whose network
backend intercepts ``connect_tcp`` calls.  At connection time (fetch time) it
resolves the hostname again, validates every resolved address against the same
blocklist, and only then opens the TCP socket.

Because the transport performs the DNS lookup **and** the TCP connect
atomically (within a single OS call), the TOCTOU window is closed: even if DNS
returns a different address at fetch time, the transport will reject it before
any bytes are sent.

Production Recommendation
--------------------------
``SSRFTransport`` significantly reduces the DNS rebinding risk but cannot
eliminate it entirely in all network configurations (e.g., DNS-over-HTTPS
proxies that cache differently, or OS-level resolver caches beyond our control).
For high-security production deployments the recommended additional layer is a
network-level egress proxy (e.g., Squid, Envoy, or a cloud NAT gateway) that
enforces egress allowlists at the infrastructure level, independent of
application-level checks.
"""

import ipaddress
import socket
import typing
from urllib.parse import urlparse

import httpcore
import httpx


class SSRFValidator:
    """SSRF protection validator for web requests.

    This class provides validation to prevent Server-Side Request Forgery attacks
    by blocking requests to internal networks, localhost, and cloud metadata endpoints.

    Example:
        >>> is_safe, reason = SSRFValidator.is_safe_url("http://localhost/admin")
        >>> print(is_safe)
        False
        >>> print(reason)
        'Blocked hostname: localhost'

        >>> is_safe, reason = SSRFValidator.is_safe_url("https://example.com/")
        >>> print(is_safe)
        True
    """

    # Private IP ranges that should be blocked
    PRIVATE_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),  # Link-local
        ipaddress.ip_network("127.0.0.0/8"),  # Localhost
        ipaddress.ip_network("::1/128"),  # IPv6 localhost
        ipaddress.ip_network("fc00::/7"),  # IPv6 private
        ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ]

    # Blocked hostnames
    BLOCKED_HOSTS = {
        "localhost",
        "0.0.0.0",  # nosec B104 - This is a blocklist, not binding to all interfaces
        "metadata.google.internal",  # GCP metadata
    }

    # Cloud metadata endpoints
    METADATA_IPS = [
        "169.254.169.254",  # AWS/Azure/GCP metadata
        "169.254.170.2",  # AWS ECS metadata
        "fd00:ec2::254",  # AWS IPv6 metadata
    ]

    @classmethod
    def is_safe_url(cls, url: str) -> tuple[bool, str]:
        """Check if URL is safe from SSRF attacks.

        Validates that the URL doesn't target internal networks, localhost,
        or cloud metadata endpoints.

        Args:
            url: The URL to validate

        Returns:
            Tuple of (is_safe, reason). If unsafe, reason contains explanation.
            If safe, reason is an empty string.

        Example:
            >>> is_safe, reason = SSRFValidator.is_safe_url("http://192.168.1.1/")
            >>> print(is_safe)
            False
            >>> print(reason)
            'Private IP address: 192.168.1.1'
        """
        try:
            parsed = urlparse(url)

            # Check scheme
            if parsed.scheme not in ("http", "https"):
                return False, f"Invalid scheme: {parsed.scheme}"

            # Check for blocked hostnames
            hostname = parsed.hostname
            if not hostname:
                return False, "No hostname in URL"

            if hostname.lower() in cls.BLOCKED_HOSTS:
                return False, f"Blocked hostname: {hostname}"

            # Check for IP address
            try:
                ip = ipaddress.ip_address(hostname)

                # Check if it's a private IP
                if any(ip in net for net in cls.PRIVATE_RANGES):
                    return False, f"Private IP address: {ip}"

                # Check cloud metadata endpoints
                if str(ip) in cls.METADATA_IPS:
                    return False, f"Cloud metadata endpoint: {ip}"

            except ValueError:
                # Not an IP address, it's a hostname - resolve DNS and validate
                try:
                    # Resolve all IP addresses for this hostname
                    addr_info = socket.getaddrinfo(hostname, None)

                    for result in addr_info:
                        # result[4] is (address, port) tuple
                        resolved_ip_str = result[4][0]

                        try:
                            resolved_ip = ipaddress.ip_address(resolved_ip_str)

                            # Check if resolved IP is private
                            if any(resolved_ip in net for net in cls.PRIVATE_RANGES):
                                return (
                                    False,
                                    f"Hostname resolves to private IP: {resolved_ip}",
                                )

                            # Check if resolved IP is a metadata endpoint
                            if str(resolved_ip) in cls.METADATA_IPS:
                                return (
                                    False,
                                    f"Hostname resolves to metadata endpoint: {resolved_ip}",
                                )

                        except ValueError:
                            # Invalid IP format in DNS response - block it
                            return (
                                False,
                                f"Invalid IP in DNS response: {resolved_ip_str}",
                            )

                except socket.gaierror as e:
                    # DNS resolution failed - block to be safe
                    return False, f"Cannot resolve hostname: {hostname} ({e})"

                except Exception as e:
                    # Any other DNS error - block to be safe
                    return False, f"DNS resolution error: {e}"

            return True, ""

        except Exception as e:
            return False, f"Invalid URL: {e}"

    @classmethod
    async def validate_request_with_redirects(
        cls, url: str, max_redirects: int = 5
    ) -> tuple[bool, str]:
        """Validate URL and all redirect targets.

        This should be used instead of httpx's automatic redirect following
        to ensure redirects don't lead to internal addresses.

        Args:
            url: Initial URL to fetch
            max_redirects: Maximum number of redirects to follow

        Returns:
            Tuple of (is_safe, reason_or_final_url). If safe, returns
            (True, final_url). If unsafe, returns (False, reason).

        Example:
            >>> is_safe, result = await SSRFValidator.validate_request_with_redirects(
            ...     "http://example.com/redirect"
            ... )
            >>> if is_safe:
            ...     print(f"Safe to fetch: {result}")
            ... else:
            ...     print(f"Blocked: {result}")
        """
        current_url = url
        redirects_followed = 0

        # Validate initial URL
        is_safe, reason = cls.is_safe_url(current_url)
        if not is_safe:
            return False, reason

        while redirects_followed < max_redirects:
            try:
                # Don't follow redirects automatically
                async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
                    response = await client.get(current_url)

                # Check if this is a redirect
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_url = response.headers.get("Location")
                    if not redirect_url:
                        return False, "Redirect without Location header"

                    # Validate redirect target
                    is_safe, reason = cls.is_safe_url(redirect_url)
                    if not is_safe:
                        return False, f"Unsafe redirect: {reason}"

                    current_url = redirect_url
                    redirects_followed += 1
                else:
                    # Not a redirect, we're done
                    return True, current_url

            except Exception as e:
                return False, f"Request failed: {e}"

        return False, f"Too many redirects (>{max_redirects})"


class _SSRFValidatingBackend(httpcore.AsyncNetworkBackend):
    """Custom httpcore network backend that validates IPs at connect time.

    This backend intercepts ``connect_tcp`` calls and performs DNS resolution
    followed by SSRF validation *before* opening the TCP socket.  This closes
    the TOCTOU gap present in pre-connect validation: even if DNS returns a
    different address between the check-time lookup (SSRFValidator.is_safe_url)
    and the fetch-time connection, the transport will reject the new address
    before any data is sent.

    The backend delegates actual connection establishment to an
    ``httpcore.AnyIOBackend`` instance after the validation passes.
    """

    def __init__(self) -> None:
        # AnyIOBackend is the concrete httpcore implementation for anyio event
        # loops (asyncio, trio).  We call it via the AsyncNetworkBackend
        # interface (connect_tcp / sleep) to remain type-safe.
        self._backend = httpcore.AnyIOBackend()  # type: ignore[attr-defined]

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Resolve host, validate resolved IPs, then open TCP connection.

        Raises:
            httpcore.ConnectError: If the resolved IP is blocked by the SSRF
                policy or if DNS resolution fails.
        """
        # Resolve DNS at connect time (fetch time)
        try:
            addr_info = socket.getaddrinfo(host, port)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(
                f"SSRF transport: DNS resolution failed for {host!r}: {exc}"
            ) from exc
        except Exception as exc:
            raise httpcore.ConnectError(
                f"SSRF transport: unexpected DNS error for {host!r}: {exc}"
            ) from exc

        # Validate every resolved address against the SSRF blocklist.
        # We must reject the connection if *any* address is private, because
        # the OS may choose any of the returned addresses when connecting.
        for result in addr_info:
            resolved_ip_str = result[4][0]
            try:
                resolved_ip = ipaddress.ip_address(resolved_ip_str)
            except ValueError:
                raise httpcore.ConnectError(
                    f"SSRF transport: invalid IP in DNS response for {host!r}: {resolved_ip_str!r}"
                )

            if any(resolved_ip in net for net in SSRFValidator.PRIVATE_RANGES):
                raise httpcore.ConnectError(
                    f"SSRF transport: DNS rebinding detected — {host!r} resolved "
                    f"to private IP {resolved_ip} at connect time"
                )

            if str(resolved_ip) in SSRFValidator.METADATA_IPS:
                raise httpcore.ConnectError(
                    f"SSRF transport: DNS rebinding detected — {host!r} resolved "
                    f"to cloud metadata endpoint {resolved_ip} at connect time"
                )

        # All resolved IPs are safe; delegate to the real backend.
        return await self._backend.connect_tcp(  # type: ignore[attr-defined]
            host=host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Block Unix domain socket connections unconditionally.

        Unix sockets bypass network-level SSRF controls and could allow access
        to local services (e.g. Docker daemon, database sockets).
        """
        raise httpcore.ConnectError(
            f"SSRF transport: Unix domain socket connections are not permitted: {path!r}"
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)  # type: ignore[attr-defined]


class SSRFTransport(httpx.AsyncHTTPTransport):
    """An httpx transport that enforces SSRF protection at TCP connect time.

    Use this transport with ``httpx.AsyncClient`` when fetching user-supplied
    or externally-sourced URLs.  It closes the TOCTOU gap inherent in
    pre-connect URL validation by re-validating the resolved IP address at the
    moment the TCP socket is opened.

    Example::

        from agent_framework.security.ssrf import SSRFTransport

        async with httpx.AsyncClient(transport=SSRFTransport()) as client:
            response = await client.get(url)

    The transport still raises ``httpx.ConnectError`` (wrapping an
    ``httpcore.ConnectError``) when a DNS rebinding attack is detected, so
    callers should catch that exception class.

    Notes:
        - Pre-connect validation (SSRFValidator.is_safe_url) should still be
          used as a fast first pass to reject obviously bad URLs without
          incurring the cost of a transport round-trip.
        - This transport does *not* replace network-level egress controls.  In
          production, combine it with a restrictive egress proxy or firewall
          rules for defence in depth.
    """

    def __init__(
        self,
        verify: bool = True,
        http1: bool = True,
        http2: bool = False,
        retries: int = 0,
        local_address: str | None = None,
    ) -> None:
        """Initialise with a custom network backend that validates IPs at connect time.

        Args:
            verify: SSL certificate verification (passed to httpcore).
            http1: Enable HTTP/1.1 (default True).
            http2: Enable HTTP/2 (default False).
            retries: Number of connection retries.
            local_address: Local address to bind to for outgoing connections.
        """
        from httpx._config import create_ssl_context

        ssl_context = create_ssl_context(verify=verify, cert=None, trust_env=True)
        # Build the connection pool with our custom network backend that
        # validates resolved IPs at TCP connect time.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            http1=http1,
            http2=http2,
            retries=retries,
            local_address=local_address,
            network_backend=_SSRFValidatingBackend(),
        )
