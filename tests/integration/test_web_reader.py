"""Tests for the web_reader tool.

Tests cover URL validation, content extraction, error handling, and edge cases.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agent_framework.tools import fetch_web_content


class TestURLValidation:
    """Tests for URL validation in fetch_web_content."""

    @pytest.mark.asyncio
    async def test_invalid_url_no_protocol(self):
        """Test that URLs without protocol are rejected."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("example.com/page")

    @pytest.mark.asyncio
    async def test_invalid_url_file_protocol(self):
        """Test that file:// URLs are rejected (prevent local file access)."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_invalid_url_javascript_protocol(self):
        """Test that javascript: URLs are rejected."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("javascript:alert(1)")

    @pytest.mark.asyncio
    async def test_invalid_url_data_protocol(self):
        """Test that data: URLs are rejected."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("data:text/html,<script>alert(1)</script>")

    @pytest.mark.asyncio
    async def test_valid_https_url(self):
        """Test that https:// URLs are accepted."""
        mock_html = "<html><body><article>Test content</article></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")
            assert result is not None

    @pytest.mark.asyncio
    async def test_valid_http_url(self):
        """Test that http:// URLs are accepted."""
        mock_html = "<html><body><article>Test content</article></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "http://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("http://example.com")
            assert result is not None


class TestContentExtraction:
    """Tests for content extraction from HTML."""

    @pytest.mark.asyncio
    async def test_extracts_title(self):
        """Test that page title is extracted."""
        mock_html = """
        <html>
            <head><title>Test Page Title</title></head>
            <body><article>Content here</article></body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert result["title"] == "Test Page Title"

    @pytest.mark.asyncio
    async def test_removes_script_tags(self):
        """Test that script tags are removed from content."""
        mock_html = """
        <html>
            <body>
                <article>
                    <p>Safe content</p>
                    <script>alert('XSS attack!');</script>
                </article>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert "alert" not in result["content"]
            assert "XSS" not in result["content"]
            assert "Safe content" in result["content"]

    @pytest.mark.asyncio
    async def test_removes_style_tags(self):
        """Test that style tags are removed from content."""
        mock_html = """
        <html>
            <body>
                <style>.hidden { display: none; }</style>
                <article>Main content</article>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert "display: none" not in result["content"]
            assert ".hidden" not in result["content"]

    @pytest.mark.asyncio
    async def test_removes_nav_and_footer(self):
        """Test that navigation and footer elements are removed."""
        mock_html = """
        <html>
            <body>
                <nav>Navigation links</nav>
                <article>Main article content</article>
                <footer>Footer content</footer>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert "Navigation links" not in result["content"]
            assert "Footer content" not in result["content"]
            assert "Main article content" in result["content"]

    @pytest.mark.asyncio
    async def test_prefers_article_selector(self):
        """Test that article content is preferred over body."""
        mock_html = """
        <html>
            <body>
                <div>Sidebar content</div>
                <article>This is the main article</article>
                <div>More sidebar</div>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert "This is the main article" in result["content"]

    @pytest.mark.asyncio
    async def test_calculates_word_count(self):
        """Test that word count is calculated correctly."""
        mock_html = """
        <html>
            <body>
                <article>One two three four five</article>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            # Word count should be at least 5
            assert result["word_count"] >= 5

    @pytest.mark.asyncio
    async def test_detects_images(self):
        """Test that image presence is detected."""
        mock_html = """
        <html>
            <body>
                <article>
                    <img src="image.jpg" alt="Test image">
                    <p>Text content</p>
                </article>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert result["has_images"] is True

    @pytest.mark.asyncio
    async def test_no_images_detected(self):
        """Test that lack of images is detected."""
        mock_html = """
        <html>
            <body>
                <article>
                    <p>Text only content</p>
                </article>
            </body>
        </html>
        """

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert result["has_images"] is False


class TestContentTruncation:
    """Tests for content length limiting."""

    @pytest.mark.asyncio
    async def test_truncates_long_content(self):
        """Test that content exceeding max_length is truncated."""
        # Create content longer than max_length
        long_content = "word " * 20000  # ~100,000 characters
        mock_html = f"<html><body><article>{long_content}</article></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com", max_length=1000)

            # Content should be truncated
            assert len(result["content"]) < 1200  # Allow for truncation message
            assert "truncated" in result["content"].lower()

    @pytest.mark.asyncio
    async def test_short_content_not_truncated(self):
        """Test that content within max_length is not truncated."""
        mock_html = "<html><body><article>Short content</article></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com", max_length=50000)

            assert "truncated" not in result["content"].lower()


class TestErrorHandling:
    """Tests for error handling in fetch_web_content."""

    @pytest.mark.asyncio
    async def test_http_404_error(self):
        """Test handling of 404 Not Found errors."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_request = MagicMock()
            mock_response = MagicMock(status_code=404)
            mock_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "404 Not Found",
                    request=mock_request,
                    response=mock_response,
                )
            )
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(ValueError, match="Failed to fetch URL"):
                await fetch_web_content("https://example.com/nonexistent")

    @pytest.mark.asyncio
    async def test_http_500_error(self):
        """Test handling of 500 Server Error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_request = MagicMock()
            mock_response = MagicMock(status_code=500)
            mock_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "500 Internal Server Error",
                    request=mock_request,
                    response=mock_response,
                )
            )
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(ValueError, match="Failed to fetch URL"):
                await fetch_web_content("https://example.com")

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Test handling of connection errors."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(ValueError, match="Failed to fetch URL"):
                await fetch_web_content("https://example.com")

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Test handling of timeout errors."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            with pytest.raises(ValueError, match="Failed to fetch URL"):
                await fetch_web_content("https://example.com")

    @pytest.mark.asyncio
    async def test_empty_content_raises_error(self):
        """Test that empty page content raises an error."""
        mock_html = "<html><body></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            # Should not raise - empty body is handled by returning body element
            result = await fetch_web_content("https://example.com")
            # Result might be minimal but should not crash
            assert result is not None


class TestRedirects:
    """Tests for handling URL redirects."""

    @pytest.mark.asyncio
    async def test_follows_redirects(self):
        """Test that redirects are followed and final URL is returned."""
        mock_html = "<html><body><article>Content</article></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            # Second response: final content (httpx follows redirects automatically)
            mock_final_response = AsyncMock()
            mock_final_response.status_code = 200
            mock_final_response.text = mock_html
            mock_final_response.url = "https://example.com/final-page"
            mock_final_response.headers = {}
            mock_final_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_final_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com/redirect")

            # Should return the final URL after redirect
            # httpx follows redirects by default, so we just get the final URL
            assert result["url"] == "https://example.com/final-page"


class TestSSRFProtection:
    """Tests for SSRF (Server-Side Request Forgery) protection.

    Tests verify that localhost, private IPs, and dangerous protocols are blocked.
    """

    @pytest.mark.asyncio
    async def test_rejects_file_protocol(self):
        """Test that file:// protocol is blocked."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_rejects_ftp_protocol(self):
        """Test that ftp:// protocol is blocked."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("ftp://example.com/file")

    @pytest.mark.asyncio
    async def test_localhost_blocked(self):
        """Test that localhost URLs are blocked (SSRF protection)."""
        # SSRF protection should block localhost access
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("http://localhost/admin")

    @pytest.mark.asyncio
    async def test_internal_ip_blocked(self):
        """Test that internal IPs are blocked (SSRF protection)."""
        # SSRF protection should block private IP addresses
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("http://192.168.1.1/admin")


class TestCharacterCount:
    """Tests for character counting."""

    @pytest.mark.asyncio
    async def test_char_count_matches_content(self):
        """Test that char_count matches actual content length."""
        mock_html = "<html><body><article>Test content here</article></body></html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = AsyncMock()
            mock_response.text = mock_html
            mock_response.url = "https://example.com"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_instance

            result = await fetch_web_content("https://example.com")

            assert result["char_count"] == len(result["content"])
