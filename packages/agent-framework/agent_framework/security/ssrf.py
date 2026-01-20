"""Security utilities for the agents project.

This module provides security utilities including SSRF (Server-Side Request Forgery)
protection for web scraping operations.
"""

import ipaddress
import socket
from urllib.parse import urlparse

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
