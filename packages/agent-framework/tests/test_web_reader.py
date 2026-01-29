"""Tests for the web reader tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.tools.web_reader import fetch_web_content


class TestFetchWebContent:
    """Tests for fetch_web_content function."""

    @pytest.mark.asyncio
    async def test_fetch_web_content_success(self):
        """Test fetch_web_content successfully fetches and parses content."""
        html_content = """
        <html>
            <head><title>Test Page Title</title></head>
            <body>
                <main>
                    <h1>Main Heading</h1>
                    <p>This is test content.</p>
                </main>
            </body>
        </html>
        """

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com/page"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await fetch_web_content("https://example.com/page")

        assert result["url"] == "https://example.com/page"
        assert result["title"] == "Test Page Title"
        assert "Main Heading" in result["content"]
        assert "test content" in result["content"]
        assert result["word_count"] > 0
        assert result["char_count"] > 0
        assert isinstance(result["has_images"], bool)
        assert isinstance(result["has_links"], bool)

    @pytest.mark.asyncio
    async def test_fetch_web_content_invalid_url(self):
        """Test fetch_web_content raises error for invalid URL."""
        with pytest.raises(ValueError, match="URL not allowed"):
            await fetch_web_content("not-a-valid-url")

    @pytest.mark.asyncio
    async def test_fetch_web_content_ftp_url(self):
        """Test fetch_web_content raises error for non-http URLs."""
        with pytest.raises(ValueError, match="URL not allowed.*Invalid scheme"):
            await fetch_web_content("ftp://example.com/file")

    @pytest.mark.asyncio
    async def test_fetch_web_content_removes_unwanted_elements(self):
        """Test fetch_web_content removes script, style, nav, etc."""
        html_content = """
        <html>
            <head>
                <title>Test</title>
                <style>.test { color: red; }</style>
            </head>
            <body>
                <nav>Navigation</nav>
                <header>Header Content</header>
                <main>
                    <p>Main content here</p>
                </main>
                <footer>Footer Content</footer>
                <script>alert('test');</script>
            </body>
        </html>
        """

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await fetch_web_content("https://example.com")

        content = result["content"]
        assert "Main content here" in content
        assert "Navigation" not in content
        assert "Footer Content" not in content
        assert "alert" not in content
        assert "color: red" not in content

    @pytest.mark.asyncio
    async def test_fetch_web_content_truncates_long_content(self):
        """Test fetch_web_content truncates content exceeding max_length."""
        # Create content longer than max_length
        long_content = "A" * 60000
        html_content = (
            f"<html><head><title>Test</title></head><body><main>{long_content}</main></body></html>"
        )

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await fetch_web_content("https://example.com", max_length=1000)

        assert len(result["content"]) <= 1100  # max_length + truncation message
        assert "[Content truncated" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_web_content_handles_no_title(self):
        """Test fetch_web_content handles pages without title."""
        html_content = "<html><body><main>Content</main></body></html>"

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await fetch_web_content("https://example.com")

        assert result["title"] == "No title"

    @pytest.mark.asyncio
    async def test_fetch_web_content_finds_article_content(self):
        """Test fetch_web_content extracts article content."""
        html_content = """
        <html>
            <head><title>Test</title></head>
            <body>
                <div>Sidebar content</div>
                <article>
                    <h1>Article Title</h1>
                    <p>Article content here.</p>
                </article>
            </body>
        </html>
        """

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await fetch_web_content("https://example.com")

        assert "Article Title" in result["content"]
        assert "Article content here" in result["content"]

    @pytest.mark.asyncio
    async def test_fetch_web_content_detects_images(self):
        """Test fetch_web_content detects images in content."""
        html_content = """
        <html>
            <head><title>Test</title></head>
            <body>
                <main>
                    <img src="image.jpg" alt="Test image">
                    <p>Content with image.</p>
                </main>
            </body>
        </html>
        """

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            result = await fetch_web_content("https://example.com")

        assert result["has_images"] is True

    @pytest.mark.asyncio
    async def test_fetch_web_content_http_error(self):
        """Test fetch_web_content handles HTTP errors."""
        import httpx

        # Need to mock both the SSRFValidator's httpx client and the fetch client
        # since SSRFValidator.validate_request_with_redirects makes HTTP requests
        with patch(
            "agent_framework.security.ssrf.SSRFValidator.validate_request_with_redirects",
            new_callable=AsyncMock,
            return_value=(True, "https://example.com"),
        ):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))

                with pytest.raises(ValueError, match="Failed to fetch URL"):
                    await fetch_web_content("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_web_content_no_body(self):
        """Test fetch_web_content handles pages without body."""
        html_content = "<html><head><title>Test</title></head></html>"

        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.url = "https://example.com"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)

            with pytest.raises(ValueError, match="Could not extract content"):
                await fetch_web_content("https://example.com")
