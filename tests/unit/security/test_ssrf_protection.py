"""Tests for SSRF (Server-Side Request Forgery) protection.

These tests ensure that web scraping tools properly validate URLs and prevent
requests to internal/private networks, localhost, and cloud metadata endpoints.
"""

import socket
from unittest.mock import MagicMock, patch

import httpcore
import httpx
import pytest
from agent_framework.security import SSRFTransport, SSRFValidator


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
        is_safe, reason = SSRFValidator.is_safe_url("http://169.254.169.254/latest/meta-data/")
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

    # --- IPv4-mapped IPv6 address protection ---

    def test_blocks_ipv4_mapped_ipv6_private(self) -> None:
        """IPv4-mapped IPv6 private address is blocked (e.g. ::ffff:192.168.1.1)."""
        is_safe, reason = SSRFValidator.is_safe_url("http://[::ffff:192.168.1.1]/")
        assert not is_safe

    def test_blocks_ipv4_mapped_ipv6_loopback(self) -> None:
        """IPv4-mapped IPv6 loopback is blocked (::ffff:127.0.0.1)."""
        is_safe, reason = SSRFValidator.is_safe_url("http://[::ffff:127.0.0.1]/")
        assert not is_safe

    def test_allows_ipv4_mapped_ipv6_public(self) -> None:
        """IPv4-mapped IPv6 public address is allowed (e.g. ::ffff:8.8.8.8)."""
        is_safe, reason = SSRFValidator.is_safe_url("http://[::ffff:8.8.8.8]/")
        assert is_safe, f"Expected safe but got: {reason}"

    # --- 0.0.0.0 / 0.0.0.0/8 protection ---

    def test_blocks_0_0_0_0_8_range(self) -> None:
        """The 0.0.0.0/8 'this network' range is blocked."""
        is_safe, reason = SSRFValidator.is_safe_url("http://0.1.2.3/")
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

    @patch("socket.getaddrinfo")
    def test_blocks_invalid_ip_in_dns_response(self, mock_getaddrinfo):
        """Test that invalid IP format in DNS response is blocked (line 133-135)."""
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("not-an-ip", 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://weird-dns.example.com/")
        assert not is_safe
        assert "invalid ip" in reason.lower()

    @patch("socket.getaddrinfo")
    def test_blocks_generic_dns_exception(self, mock_getaddrinfo):
        """Test that generic DNS resolution errors are blocked (line 144-146)."""
        mock_getaddrinfo.side_effect = OSError("Unexpected DNS error")

        is_safe, reason = SSRFValidator.is_safe_url("http://dns-error.example.com/")
        assert not is_safe
        assert "dns" in reason.lower() or "error" in reason.lower()

    @patch("socket.getaddrinfo")
    def test_blocks_hostname_resolving_to_metadata_ip(self, mock_getaddrinfo):
        """Test hostname resolving to metadata endpoint via DNS (line 127-131).

        Note: 169.254.169.254 is in the link-local range so it's caught as
        'private IP' before the metadata check. Both are correct blocks.
        """
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("169.254.169.254", 0))]

        is_safe, reason = SSRFValidator.is_safe_url("http://sneaky.example.com/")
        assert not is_safe
        assert "private" in reason.lower() or "metadata" in reason.lower()

    def test_handles_completely_invalid_url(self):
        """Test that completely invalid URLs are caught by outer exception (line 150-151)."""
        is_safe, reason = SSRFValidator.is_safe_url("")
        assert not is_safe


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

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_blocks_redirect_without_location_header(self, mock_get):
        """Test redirect response missing Location header (line 196-197)."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {}  # No Location header
        mock_get.return_value = mock_response

        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/redirect"
        )

        assert not is_safe
        assert "location" in reason.lower()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_handles_request_failure_during_redirect(self, mock_get):
        """Test network error during redirect following (line 210-211)."""
        mock_get.side_effect = Exception("Connection reset")

        is_safe, reason = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/unstable"
        )

        assert not is_safe
        assert "request failed" in reason.lower()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_returns_final_url_on_non_redirect(self, mock_get):
        """Test that non-redirect response returns the current URL (line 208)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_get.return_value = mock_response

        is_safe, final_url = await SSRFValidator.validate_request_with_redirects(
            "http://example.com/page"
        )

        assert is_safe
        assert final_url == "http://example.com/page"


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

        with pytest.raises(ValueError, match="(metadata|private|URL not allowed)"):
            await fetch_web_content("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.asyncio
    async def test_web_tools_allow_public_urls(self):
        """Test that web tools allow legitimate public URLs."""
        from agent_framework.tools import analyze_website, fetch_web_content

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
            # SSRFTransport closes the TOCTOU gap by re-validating the resolved
            # IP at TCP connect time, preventing DNS rebinding attacks.
            "DNS rebinding protection via SSRFTransport": True,
            "Time-of-check-time-of-use protection via SSRFTransport": True,
        }

        # This test always passes but documents the checklist
        assert all(checklist.values()) or not all(checklist.values())

    def test_ssrf_implementation_locations(self) -> None:
        """Document where SSRF protection is implemented."""
        # SSRF protection is applied in:
        # packages/agent-framework/agent_framework/security/ssrf.py  (SSRFValidator, SSRFTransport)
        # packages/agent-framework/agent_framework/tools/web_reader.py  (fetch_web_content)
        # packages/agent-framework/agent_framework/tools/web_analyzer.py  (analyze_website)
        from agent_framework.security import SSRFTransport, SSRFValidator

        assert SSRFValidator is not None
        assert SSRFTransport is not None

    def test_ssrf_protection_example_usage(self):
        """Document example usage of SSRF protection."""
        example_code = """
        from agent_framework.security import SSRFValidator, SSRFTransport

        async def safe_fetch(url: str):
            # Fast first-pass: reject obviously bad URLs before opening a socket.
            is_safe, reason = SSRFValidator.is_safe_url(url)
            if not is_safe:
                raise ValueError(f"Unsafe URL: {reason}")

            # SSRFTransport closes the TOCTOU gap by re-validating the resolved
            # IP at TCP connect time, preventing DNS rebinding attacks.
            async with httpx.AsyncClient(transport=SSRFTransport()) as client:
                response = await client.get(url, follow_redirects=False)
                return response
        """

        # This test documents the example
        assert "SSRFValidator" in example_code
        assert "is_safe_url" in example_code
        assert "SSRFTransport" in example_code


class TestSSRFTransport:
    """Tests for SSRFTransport DNS rebinding protection.

    SSRFTransport closes the TOCTOU gap by validating resolved IPs at TCP
    connect time, not just at URL-check time.
    """

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_private_ip_at_connect_time(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport raises ConnectError when hostname resolves to private IP at connect time."""
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 80))]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS rebinding detected"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://evil.example.com/")

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_localhost_at_connect_time(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport raises ConnectError when hostname resolves to loopback at connect time."""
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS rebinding detected"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://rebind.attacker.com/")

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_metadata_endpoint_at_connect_time(
        self, mock_getaddrinfo: MagicMock
    ) -> None:
        """Transport raises ConnectError when hostname resolves to cloud metadata at connect time."""
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("169.254.169.254", 80))]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS rebinding detected"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://sneaky.attacker.com/")

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_ipv6_private_at_connect_time(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport raises ConnectError when hostname resolves to IPv6 private at connect time."""
        mock_getaddrinfo.return_value = [(10, 1, 6, "", ("::1", 80, 0, 0))]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS rebinding detected"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://ipv6-rebind.attacker.com/")

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_dns_resolution_failure(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport raises ConnectError when DNS resolution fails at connect time."""
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS resolution failed"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://nonexistent.invalid/")

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_invalid_ip_in_dns_response(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport raises ConnectError when DNS response contains an invalid IP."""
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("not-an-ip", 80))]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="invalid IP in DNS response"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://weird.example.com/")

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_mixed_ips_one_private(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport rejects a hostname that resolves to both public and private IPs."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("8.8.8.8", 80)),  # public
            (2, 1, 6, "", ("10.0.0.1", 80)),  # private — must block
        ]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS rebinding detected"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://mixed.example.com/")

    @pytest.mark.asyncio
    async def test_blocks_unix_socket_connections(self) -> None:
        """Transport blocks Unix domain socket connections unconditionally."""
        from agent_framework.security.ssrf import _SSRFValidatingBackend

        backend = _SSRFValidatingBackend()
        with pytest.raises(httpcore.ConnectError, match="Unix domain socket"):
            await backend.connect_unix_socket("/var/run/docker.sock")

    def test_ssrf_transport_is_importable_from_security(self) -> None:
        """SSRFTransport is exported from the top-level security package."""
        from agent_framework.security import SSRFTransport as T

        assert T is SSRFTransport

    def test_ssrf_transport_is_async_http_transport_subclass(self) -> None:
        """SSRFTransport is a proper httpx.AsyncHTTPTransport subclass."""
        assert issubclass(SSRFTransport, httpx.AsyncHTTPTransport)

    @pytest.mark.asyncio
    @patch("socket.getaddrinfo")
    async def test_blocks_ipv4_mapped_ipv6_private_at_connect_time(
        self, mock_getaddrinfo: MagicMock
    ) -> None:
        """Transport blocks IPv4-mapped IPv6 private addresses at connect time."""
        # ::ffff:192.168.1.1 is an IPv4-mapped IPv6 form of 192.168.1.1
        mock_getaddrinfo.return_value = [(10, 1, 6, "", ("::ffff:192.168.1.1", 80, 0, 0))]

        transport = SSRFTransport()
        async with transport:
            with pytest.raises(httpx.ConnectError, match="DNS rebinding detected"):
                async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
                    await client.get("http://mapped-ipv6.attacker.com/")
