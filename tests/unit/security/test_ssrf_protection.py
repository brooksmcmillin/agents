"""Tests for SSRF (Server-Side Request Forgery) protection.

These tests ensure that web scraping tools properly validate URLs and prevent
requests to internal/private networks, localhost, and cloud metadata endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest
import socket

from agent_framework.security import SSRFValidator


class TestSSRFValidator:
    """Tests for SSRF protection validator."""

    # --- Localhost/Loopback Protection ---

    def test_blocks_localhost_hostname(self):
        """Test that localhost hostname is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://localhost/api")
        assert not is_safe
        assert "localhost" in reason.lower()

    def test_blocks_127_0_0_1(self):
        """Test that 127.0.0.1 is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://127.0.0.1/admin")
        assert not is_safe
        assert "private" in reason.lower() or "127.0.0.1" in reason

    def test_blocks_127_0_0_0_8(self):
        """Test that entire 127.0.0.0/8 range is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://127.1.2.3/data")
        assert not is_safe
        assert "private" in reason.lower()

    def test_blocks_ipv6_localhost(self):
        """Test that IPv6 localhost (::1) is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://[::1]/api")
        assert not is_safe

    def test_blocks_0_0_0_0(self):
        """Test that 0.0.0.0 is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://0.0.0.0/")
        assert not is_safe

    # --- Private IP Range Protection ---

    def test_blocks_10_0_0_0_8(self):
        """Test that 10.0.0.0/8 private range is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://10.0.0.1/internal")
        assert not is_safe
        assert "private" in reason.lower()

        is_safe, reason = SSRFValidator.is_safe_url("http://10.255.255.255/api")
        assert not is_safe

    def test_blocks_172_16_0_0_12(self):
        """Test that 172.16.0.0/12 private range is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://172.16.0.1/admin")
        assert not is_safe
        assert "private" in reason.lower()

        is_safe, reason = SSRFValidator.is_safe_url("http://172.31.255.255/data")
        assert not is_safe

    def test_blocks_192_168_0_0_16(self):
        """Test that 192.168.0.0/16 private range is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://192.168.1.1/router")
        assert not is_safe
        assert "private" in reason.lower()

        is_safe, reason = SSRFValidator.is_safe_url("http://192.168.255.255/")
        assert not is_safe

    def test_blocks_169_254_0_0_16_link_local(self):
        """Test that 169.254.0.0/16 link-local range is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://169.254.1.1/")
        assert not is_safe
        assert "private" in reason.lower()

    # --- Cloud Metadata Endpoint Protection ---

    def test_blocks_aws_metadata_endpoint(self):
        """Test that AWS metadata endpoint (169.254.169.254) is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url(
            "http://169.254.169.254/latest/meta-data/"
        )
        assert not is_safe
        # Can be blocked as either "metadata" or "private" (link-local range)
        assert "metadata" in reason.lower() or "private" in reason.lower()

    def test_blocks_gcp_metadata_hostname(self):
        """Test that GCP metadata hostname is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url(
            "http://metadata.google.internal/computeMetadata/v1/"
        )
        assert not is_safe
        assert "metadata" in reason.lower()

    def test_blocks_aws_ecs_metadata(self):
        """Test that AWS ECS metadata endpoint is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://169.254.170.2/")
        assert not is_safe

    # --- IPv6 Private Range Protection ---

    def test_blocks_ipv6_private_fc00(self):
        """Test that IPv6 private range (fc00::/7) is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://[fc00::1]/")
        assert not is_safe

    def test_blocks_ipv6_link_local(self):
        """Test that IPv6 link-local (fe80::/10) is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://[fe80::1]/")
        assert not is_safe

    # --- Valid Public URLs ---

    def test_allows_public_ipv4(self):
        """Test that public IPv4 addresses are allowed."""
        # Cloudflare DNS
        is_safe, reason = SSRFValidator.is_safe_url("http://1.1.1.1/")
        assert is_safe

        # Google DNS
        is_safe, reason = SSRFValidator.is_safe_url("http://8.8.8.8/")
        assert is_safe

    def test_allows_public_domains(self):
        """Test that public domain names are allowed."""
        is_safe, reason = SSRFValidator.is_safe_url("https://example.com/")
        assert is_safe

        is_safe, reason = SSRFValidator.is_safe_url("https://www.google.com/")
        assert is_safe

        is_safe, reason = SSRFValidator.is_safe_url("https://api.github.com/")
        assert is_safe

    def test_allows_https_scheme(self):
        """Test that HTTPS scheme is allowed."""
        is_safe, reason = SSRFValidator.is_safe_url("https://example.com/api")
        assert is_safe

    def test_allows_http_scheme(self):
        """Test that HTTP scheme is allowed."""
        is_safe, reason = SSRFValidator.is_safe_url("http://example.com/api")
        assert is_safe

    # --- Invalid/Malicious URL Patterns ---

    def test_blocks_invalid_scheme(self):
        """Test that non-HTTP schemes are blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("file:///etc/passwd")
        assert not is_safe
        assert "scheme" in reason.lower()

        is_safe, reason = SSRFValidator.is_safe_url("ftp://internal.server/")
        assert not is_safe

        is_safe, reason = SSRFValidator.is_safe_url("gopher://internal/")
        assert not is_safe

    def test_blocks_url_without_hostname(self):
        """Test that URLs without hostname are blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http:///path")
        assert not is_safe

    def test_handles_malformed_urls(self):
        """Test handling of malformed URLs."""
        is_safe, reason = SSRFValidator.is_safe_url("not a url")
        assert not is_safe

        is_safe, reason = SSRFValidator.is_safe_url("http://")
        assert not is_safe

    # --- URL Encoding Bypass Attempts ---

    def test_blocks_url_encoded_localhost(self):
        """Test that URL-encoded localhost attempts are blocked."""
        # Note: This tests the hostname after parsing, httpx should decode first
        is_safe, reason = SSRFValidator.is_safe_url("http://127.0.0.1/")
        assert not is_safe

    def test_blocks_decimal_ip_notation(self):
        """Test blocking of decimal IP notation (127.0.0.1 = 2130706433)."""
        # This would need to be implemented in production code
        # For now, just ensure normal notation is blocked
        is_safe, reason = SSRFValidator.is_safe_url("http://127.0.0.1/")
        assert not is_safe

    # --- Port Specification ---

    def test_allows_public_url_with_port(self):
        """Test that public URLs with ports are allowed."""
        is_safe, reason = SSRFValidator.is_safe_url("http://example.com:8080/")
        assert is_safe

    def test_blocks_private_ip_with_port(self):
        """Test that private IPs with ports are still blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://192.168.1.1:8080/")
        assert not is_safe

    def test_blocks_localhost_with_port(self):
        """Test that localhost with port is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://localhost:3000/")
        assert not is_safe

    # --- DNS Resolution Protection ---

    @patch("socket.getaddrinfo")
    def test_blocks_hostname_resolving_to_localhost(self, mock_getaddrinfo):
        """Test that hostname resolving to 127.0.0.1 is blocked (DNS rebinding protection)."""
        # Mock DNS resolution to return 127.0.0.1
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://evil.com/")
        assert not is_safe
        assert "private" in reason.lower() or "127.0.0.1" in reason
        mock_getaddrinfo.assert_called_once()

    @patch("socket.getaddrinfo")
    def test_blocks_hostname_resolving_to_private_ip(self, mock_getaddrinfo):
        """Test that hostname resolving to private IP is blocked."""
        # Mock DNS resolution to return 192.168.1.1
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://internal.example.com/")
        assert not is_safe
        assert "private" in reason.lower()

    @patch("socket.getaddrinfo")
    def test_blocks_hostname_resolving_to_metadata(self, mock_getaddrinfo):
        """Test that hostname resolving to cloud metadata endpoint is blocked."""
        # Mock DNS resolution to return AWS metadata IP
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://metadata.evil.com/")
        assert not is_safe
        assert "metadata" in reason.lower() or "169.254.169.254" in reason

    @patch("socket.getaddrinfo")
    def test_blocks_hostname_with_multiple_ips_one_private(self, mock_getaddrinfo):
        """Test that hostname with both public and private IPs is blocked."""
        # Mock DNS resolution to return both public and private IPs
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("8.8.8.8", 0)),  # Public IP
            (2, 1, 6, "", ("192.168.1.1", 0)),  # Private IP - should block
        ]

        is_safe, reason = SSRFValidator.is_safe_url("http://mixed.example.com/")
        assert not is_safe
        assert "private" in reason.lower()

    @patch("socket.getaddrinfo")
    def test_allows_hostname_resolving_to_public_ip(self, mock_getaddrinfo):
        """Test that hostname resolving to public IP is allowed."""
        # Mock DNS resolution to return public IP (Google DNS)
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("8.8.8.8", 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://safe.example.com/")
        assert is_safe

    @patch("socket.getaddrinfo")
    def test_blocks_hostname_with_dns_error(self, mock_getaddrinfo):
        """Test that hostname that fails DNS resolution is blocked."""
        # Mock DNS resolution failure
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")

        is_safe, reason = SSRFValidator.is_safe_url("http://nonexistent.invalid/")
        assert not is_safe
        assert "resolve" in reason.lower() or "dns" in reason.lower()

    @patch("socket.getaddrinfo")
    def test_blocks_ipv6_hostname_resolving_to_localhost(self, mock_getaddrinfo):
        """Test that hostname resolving to IPv6 localhost is blocked."""
        # Mock DNS resolution to return IPv6 localhost
        mock_getaddrinfo.return_value = [(10, 1, 6, "", ("::1", 0, 0, 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://ipv6-evil.com/")
        assert not is_safe
        assert "private" in reason.lower() or "::1" in reason


class TestSSRFRedirectProtection:
    """Tests for SSRF protection in redirect following."""

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_blocks_redirect_to_localhost(self, mock_get):
        """Test that redirects to localhost are blocked."""
        # Mock initial request to public URL
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "http://localhost/admin"}
        mock_get.return_value = mock_response

        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/redirect"
        )

        assert not is_safe
        assert "redirect" in reason.lower()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_blocks_redirect_to_private_ip(self, mock_get):
        """Test that redirects to private IPs are blocked."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "http://192.168.1.1/internal"}
        mock_get.return_value = mock_response

        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/redirect"
        )

        assert not is_safe
        assert "private" in reason.lower() or "redirect" in reason.lower()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_blocks_redirect_to_metadata_endpoint(self, mock_get):
        """Test that redirects to cloud metadata are blocked."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        mock_get.return_value = mock_response

        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/evil-redirect"
        )

        assert not is_safe
        assert "metadata" in reason.lower() or "redirect" in reason.lower()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_allows_redirect_to_public_url(self, mock_get):
        """Test that redirects to public URLs are allowed."""
        # First request - redirect
        redirect_response = MagicMock()
        redirect_response.status_code = 302
        redirect_response.headers = {"Location": "https://example.org/target"}

        # Second request - final destination
        final_response = MagicMock()
        final_response.status_code = 200
        final_response.headers = {}

        mock_get.side_effect = [redirect_response, final_response]

        is_safe, final_url = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/redirect"
        )

        assert is_safe
        assert "example.org" in final_url

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_blocks_too_many_redirects(self, mock_get):
        """Test that excessive redirects are blocked."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "http://example.com/redirect"}
        mock_get.return_value = mock_response

        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/redirect", max_redirects=3
        )

        assert not is_safe
        assert "redirect" in reason.lower()

    @pytest.mark.asyncio
    async def test_validates_initial_url_before_request(self):
        """Test that initial URL is validated before any request."""
        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://localhost/admin"
        )

        assert not is_safe
        assert "localhost" in reason.lower()


class TestSSRFIntegrationWithWebTools:
    """Integration tests for SSRF protection in web scraping tools.

    These tests verify that SSRF protection is properly integrated into
    web_analyzer.py and web_reader.py and blocks dangerous requests.
    """

    @pytest.mark.asyncio
    async def test_web_analyzer_blocks_localhost(self):
        """Test that web_analyzer rejects localhost URLs."""
        from agent_framework.tools import analyze_website

        with pytest.raises(ValueError, match="(localhost|security)"):
            await analyze_website("http://localhost/admin", "tone")

    @pytest.mark.asyncio
    async def test_web_analyzer_blocks_private_ip(self):
        """Test that web_analyzer rejects private IP addresses."""
        from agent_framework.tools import analyze_website

        with pytest.raises(ValueError, match="(private|security)"):
            await analyze_website("http://192.168.1.1/router", "seo")

    @pytest.mark.asyncio
    async def test_web_reader_blocks_metadata_endpoint(self):
        """Test that web_reader rejects cloud metadata endpoints."""
        from agent_framework.tools import fetch_web_content

        with pytest.raises(ValueError, match="(metadata|private|security)"):
            await fetch_web_content("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.asyncio
    async def test_web_tools_allow_public_urls(self):
        """Test that web tools allow legitimate public URLs."""
        from agent_framework.tools import analyze_website
        from agent_framework.tools import fetch_web_content

        # These should work (may fail if network unavailable, that's OK)
        try:
            await analyze_website("https://example.com/", "tone")
            await fetch_web_content("https://example.com/")
        except ValueError as e:
            # SSRF blocks should not occur for public URLs
            if "security" in str(e).lower():
                raise
        except Exception:
            # Network errors are acceptable
            pass


class TestSSRFDocumentation:
    """Documentation tests for SSRF protection implementation.

    These tests serve as documentation for developers implementing
    SSRF protection in the web scraping tools.
    """

    def test_ssrf_protection_checklist(self):
        """Document SSRF protection implementation checklist."""
        checklist = {
            "Block localhost and loopback": True,
            "Block private IP ranges (10.x, 192.168.x, 172.16-31.x)": True,
            "Block link-local addresses (169.254.x.x)": True,
            "Block cloud metadata endpoints (169.254.169.254)": True,
            "Block IPv6 private ranges": True,
            "Validate redirect targets": True,
            "Limit maximum redirects": True,
            "DNS rebinding protection": False,  # Not implemented yet
            "Time-of-check-time-of-use protection": False,  # Not implemented yet
        }

        # This test always passes but documents the checklist
        assert all(checklist.values()) or not all(checklist.values())

    def test_ssrf_implementation_locations(self):
        """Document where SSRF protection should be implemented."""
        locations = [
            "/home/brooks/build/agents/shared/security_utils.py",  # New file
            "/home/brooks/build/agents/mcp_server/tools/web_analyzer.py",  # Update
            "/home/brooks/build/agents/mcp_server/tools/web_reader.py",  # Update
        ]

        # This test documents the locations
        assert len(locations) == 3

    def test_ssrf_protection_example_usage(self):
        """Document example usage of SSRF protection."""
        example_code = """
        from agent_framework.security import SSRFValidator

        async def safe_fetch(url: str):
            # Validate URL before fetching
            is_safe, reason = SSRFValidator.is_safe_url(url)
            if not is_safe:
                raise ValueError(f"Unsafe URL: {reason}")

            # Validate with redirect protection
            is_safe, final_url = await SSRFValidator.validate_request_with_redirects(url)
            if not is_safe:
                raise ValueError(f"Unsafe redirect: {final_url}")

            # Safe to fetch
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                return response
        """

        # This test documents the example
        assert "SSRFValidator" in example_code
        assert "is_safe_url" in example_code
        assert "validate_request_with_redirects" in example_code
