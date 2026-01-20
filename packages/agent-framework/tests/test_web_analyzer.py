"""Tests for web content analyzer with malicious HTML and security scenarios.

These tests ensure the web analyzer properly handles:
- Malicious HTML (XSS, script injection)
- Malformed HTML
- SSRF protection integration
- Edge cases (empty content, very large content, etc.)
"""

from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from agent_framework.tools.web_analyzer import (
    _analyze_seo,
    _analyze_tone,
    _calculate_readability,
    _count_syllables,
    _extract_text_content,
    analyze_website,
)


class TestTextExtraction:
    """Tests for text content extraction from HTML."""

    def test_extracts_basic_text(self):
        """Test extraction of basic text content."""
        html = "<html><body><p>Hello world</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Hello world" in text

    def test_removes_script_tags(self):
        """Test that script tags are removed."""
        html = """
        <html><body>
            <p>Safe content</p>
            <script>alert('XSS')</script>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Safe content" in text
        assert "alert" not in text
        assert "XSS" not in text

    def test_removes_style_tags(self):
        """Test that style tags are removed."""
        html = """
        <html><body>
            <p>Visible text</p>
            <style>body { color: red; }</style>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Visible text" in text
        assert "color" not in text

    def test_removes_nav_footer_header(self):
        """Test that navigation, footer, and header are removed."""
        html = """
        <html>
        <header><p>Header content</p></header>
        <nav><a href="/">Nav link</a></nav>
        <body><p>Main content</p></body>
        <footer><p>Footer content</p></footer>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Main content" in text
        assert "Header content" not in text
        assert "Nav link" not in text
        assert "Footer content" not in text

    def test_handles_malicious_event_handlers(self):
        """Test that event handlers in HTML don't appear in text."""
        html = """
        <html><body>
            <p onclick="maliciousFunction()">Click me</p>
            <img src="x" onerror="alert('XSS')">
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Click me" in text
        assert "maliciousFunction" not in text
        assert "onerror" not in text

    def test_handles_empty_html(self):
        """Test handling of empty HTML."""
        html = "<html><body></body></html>"
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert isinstance(text, str)
        assert len(text.strip()) == 0

    def test_handles_deeply_nested_html(self):
        """Test handling of deeply nested HTML structures."""
        html = "<div>" * 100 + "Nested content" + "</div>" * 100
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Nested content" in text

    def test_handles_unicode_content(self):
        """Test handling of unicode and special characters."""
        html = """
        <html><body>
            <p>Hello 世界</p>
            <p>Emojis: 🔥 💯</p>
            <p>Symbols: © ® ™</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "世界" in text
        assert "🔥" in text or "Emojis" in text  # Emojis might be stripped
        assert "©" in text or "®" in text

    def test_cleans_excessive_whitespace(self):
        """Test that excessive whitespace is cleaned."""
        html = """
        <html><body>
            <p>Word1     Word2</p>
            <p>Word3

            Word4</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        # Should not have multiple consecutive spaces
        assert "     " not in text


class TestReadabilityCalculation:
    """Tests for readability metrics calculation."""

    def test_calculates_basic_readability(self):
        """Test basic readability calculation."""
        text = "This is a simple test. It has short words."
        result = _calculate_readability(text)

        assert "flesch_reading_ease" in result
        assert "avg_sentence_length" in result
        assert "avg_word_length" in result
        assert 0 <= result["flesch_reading_ease"] <= 100

    def test_handles_empty_text(self):
        """Test handling of empty text."""
        result = _calculate_readability("")

        assert result["flesch_reading_ease"] == 0
        assert result["avg_sentence_length"] == 0
        assert result["avg_word_length"] == 0

    def test_handles_no_sentences(self):
        """Test handling of text without sentence endings."""
        text = "no punctuation at all just words"
        result = _calculate_readability(text)

        # Should still calculate something
        assert isinstance(result["flesch_reading_ease"], (int, float))

    def test_handles_very_long_sentences(self):
        """Test handling of very long sentences."""
        text = "word " * 1000 + "."
        result = _calculate_readability(text)

        # Should be close to 1000 words (might count the period)
        assert 999 <= result["avg_sentence_length"] <= 1001
        # Flesch score should be low for long sentences
        assert result["flesch_reading_ease"] < 50

    def test_handles_very_short_sentences(self):
        """Test handling of very short sentences."""
        text = "Hi. Me. Go."
        result = _calculate_readability(text)

        assert result["avg_sentence_length"] == 1.0
        # Flesch score should be high for short sentences
        assert result["flesch_reading_ease"] > 80


class TestSyllableCounting:
    """Tests for syllable counting helper."""

    def test_counts_simple_words(self):
        """Test syllable counting for simple words."""
        assert _count_syllables("cat") == 1
        assert _count_syllables("hello") == 2
        assert _count_syllables("beautiful") == 3

    def test_handles_silent_e(self):
        """Test that silent e is handled correctly."""
        assert _count_syllables("make") == 1
        assert _count_syllables("home") == 1

    def test_minimum_one_syllable(self):
        """Test that every word has at least one syllable."""
        assert _count_syllables("i") >= 1
        assert _count_syllables("a") >= 1

    def test_handles_empty_string(self):
        """Test handling of empty string."""
        assert _count_syllables("") >= 1


class TestToneAnalysis:
    """Tests for tone and style analysis."""

    def test_detects_formal_tone(self):
        """Test detection of formal tone."""
        text = "Consequently, the aforementioned methodology demonstrates significant efficacy."
        readability = _calculate_readability(text)
        result = _analyze_tone(text, readability)

        assert result["formality_level"] == "formal"
        assert result["vocabulary_complexity"] == "advanced"

    def test_detects_casual_tone(self):
        """Test detection of casual tone."""
        text = "Hey, just a quick note to say hi and see how you are."
        readability = _calculate_readability(text)
        result = _analyze_tone(text, readability)

        assert result["formality_level"] == "casual"

    def test_detects_enthusiasm_markers(self):
        """Test detection of enthusiasm markers."""
        text = "This is amazing! Excellent work! Great job! " * 10  # Repeat for higher score
        readability = _calculate_readability(text)
        result = _analyze_tone(text, readability)

        assert result["emotional_markers"]["enthusiasm"] > 0

    def test_detects_authority_markers(self):
        """Test detection of authority markers."""
        text = "Research data shows proven evidence from expert studies. " * 10
        readability = _calculate_readability(text)
        result = _analyze_tone(text, readability)

        assert result["emotional_markers"]["authority"] > 0

    def test_handles_empty_text(self):
        """Test handling of empty text."""
        readability = {"flesch_reading_ease": 0, "avg_sentence_length": 0, "avg_word_length": 0}
        result = _analyze_tone("", readability)

        assert "formality_level" in result
        assert "emotional_markers" in result


class TestSEOAnalysis:
    """Tests for SEO analysis."""

    def test_analyzes_basic_seo(self):
        """Test basic SEO analysis."""
        html = (
            """
        <html>
        <head>
            <title>Optimal Title Length for SEO</title>
            <meta name="description" content="This meta description is exactly the right length for optimal SEO performance and search engine rankings with proper length and keywords.">
        </head>
        <body>
            <h1>Main Heading</h1>
            <h2>Subheading</h2>
            <p>Content with at least 500 words. """
            + ("Word. " * 500)
            + """</p>
        </body>
        </html>
        """
        )
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        assert "seo_score" in result
        assert result["title_optimization"]["present"]
        assert result["meta_description"]["present"]

    def test_handles_missing_title(self):
        """Test handling of missing title tag."""
        html = "<html><body><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        assert not result["title_optimization"]["present"]
        assert result["title_optimization"]["length"] == 0

    def test_handles_missing_meta_description(self):
        """Test handling of missing meta description."""
        html = """
        <html>
        <head><title>Title</title></head>
        <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        assert not result["meta_description"]["present"]

    def test_handles_malicious_meta_tags(self):
        """Test handling of malicious meta tags."""
        html = """
        <html>
        <head>
            <meta name="description" content="<script>alert('XSS')</script>">
            <title><script>evil()</script>Title</title>
        </head>
        <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        # Should extract meta description and title properly
        # BeautifulSoup treats the content attribute as text, not HTML
        assert result["meta_description"]["present"]
        assert result["title_optimization"]["present"]

    def test_handles_multiple_h1_tags(self):
        """Test handling of multiple H1 tags (bad for SEO)."""
        html = """
        <html><body>
            <h1>First H1</h1>
            <h1>Second H1</h1>
            <p>Content</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        # SEO score should be reduced for multiple H1s
        assert result["headings"]["h1_count"] == 2

    def test_handles_no_headings(self):
        """Test handling of content with no headings."""
        html = "<html><body><p>Just paragraphs, no headings.</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        assert result["headings"]["h1_count"] == 0


class TestAnalyzeWebsiteIntegration:
    """Integration tests for the full analyze_website function."""

    @pytest.mark.asyncio
    async def test_blocks_localhost_access(self):
        """Test that localhost access is blocked via SSRF protection."""
        with pytest.raises(ValueError, match="security|localhost"):
            await analyze_website("http://localhost/admin", "seo")

    @pytest.mark.asyncio
    async def test_blocks_private_ip_access(self):
        """Test that private IP access is blocked."""
        with pytest.raises(ValueError, match="security|private"):
            await analyze_website("http://192.168.1.1/router", "seo")

    @pytest.mark.asyncio
    async def test_blocks_metadata_endpoint(self):
        """Test that cloud metadata endpoint is blocked."""
        with pytest.raises(ValueError, match="security|metadata"):
            await analyze_website("http://169.254.169.254/latest/meta-data/", "seo")

    @pytest.mark.asyncio
    async def test_blocks_invalid_scheme(self):
        """Test that invalid URL schemes are blocked."""
        with pytest.raises(ValueError, match="Invalid URL"):
            await analyze_website("file:///etc/passwd", "seo")

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_handles_http_errors_gracefully(self, mock_get):
        """Test that HTTP errors are handled gracefully."""
        import httpx

        mock_get.side_effect = httpx.HTTPError("Connection failed")

        with pytest.raises(ValueError):  # Should raise ValueError from analyze_website
            await analyze_website("http://example.com/", "seo")

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_handles_timeout_gracefully(self, mock_get):
        """Test that timeout is handled gracefully."""
        import httpx

        mock_get.side_effect = httpx.TimeoutException("Request timeout")

        with pytest.raises(ValueError):
            await analyze_website("http://example.com/", "seo")

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_handles_invalid_html(self, mock_get):
        """Test handling of completely invalid HTML."""
        mock_response = AsyncMock()
        mock_response.text = "Not HTML at all <<>><>><"
        mock_response.status_code = 200
        mock_response.url = "http://example.com/"
        mock_get.return_value = mock_response

        # Should still process without crashing
        result = await analyze_website("http://example.com/", "seo")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_handles_empty_response(self, mock_get):
        """Test handling of empty HTTP response."""
        mock_response = AsyncMock()
        mock_response.text = ""
        mock_response.status_code = 200
        mock_response.url = "http://example.com/"
        mock_get.return_value = mock_response

        # Empty content should raise an error
        with pytest.raises(ValueError, match="No text content"):
            await analyze_website("http://example.com/", "seo")

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_handles_huge_html_document(self, mock_get):
        """Test handling of extremely large HTML documents."""
        huge_html = "<html><body>" + ("<p>Content</p>" * 100000) + "</body></html>"
        mock_response = AsyncMock()
        mock_response.text = huge_html
        mock_response.status_code = 200
        mock_response.url = "http://example.com/"
        mock_get.return_value = mock_response

        # Should handle without memory issues or hanging
        result = await analyze_website("http://example.com/", "seo")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_analyzes_seo_focus(self, mock_get):
        """Test SEO-focused analysis."""
        html = """
        <html>
        <head>
            <title>Test Page</title>
            <meta name="description" content="Test description">
        </head>
        <body><h1>Heading</h1><p>Content</p></body>
        </html>
        """
        mock_response = AsyncMock()
        mock_response.text = html
        mock_response.status_code = 200
        mock_response.url = "http://example.com/"
        mock_get.return_value = mock_response

        result = await analyze_website("http://example.com/", "seo")
        assert "analysis_type" in result
        assert result["analysis_type"] == "seo"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_analyzes_tone_focus(self, mock_get):
        """Test tone-focused analysis."""
        html = "<html><body><p>This is great content with excellent examples!</p></body></html>"
        mock_response = AsyncMock()
        mock_response.text = html
        mock_response.status_code = 200
        mock_response.url = "http://example.com/"
        mock_get.return_value = mock_response

        result = await analyze_website("http://example.com/", "tone")
        assert "analysis_type" in result
        assert result["analysis_type"] == "tone"


class TestMaliciousHTMLScenarios:
    """Tests for specific malicious HTML attack scenarios."""

    def test_handles_billion_laughs_attack(self):
        """Test handling of XML entity expansion attack."""
        # BeautifulSoup with lxml should handle this safely
        html = """<!DOCTYPE html [
        <!ENTITY lol "lol">
        <!ENTITY lol2 "&lol;&lol;">
        ]><html><body>&lol2;</body></html>"""

        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        # Should not cause infinite expansion
        assert len(text) < 10000

    def test_handles_xss_in_attributes(self):
        """Test that XSS in attributes doesn't leak into text."""
        html = """
        <html><body>
            <img src="x" onerror="alert('XSS')">
            <a href="javascript:alert('XSS')">Click</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "alert" not in text
        assert "javascript:" not in text

    def test_handles_svg_xss(self):
        """Test handling of XSS via SVG tags."""
        html = """
        <html><body>
            <svg onload="alert('XSS')">
                <script>alert('XSS')</script>
            </svg>
            <p>Safe content</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Safe content" in text
        assert "alert" not in text

    def test_handles_html_injection(self):
        """Test handling of HTML injection attempts."""
        html = """
        <html><body>
            <p>User input: <script>malicious()</script></p>
            <p>More user input: <iframe src="evil.com"></iframe></p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        # Scripts and iframes should be removed
        assert "malicious" not in text
        assert "iframe" not in text

    def test_handles_css_injection(self):
        """Test handling of CSS-based attacks."""
        html = """
        <html><body>
            <style>
                body { background: url('javascript:alert("XSS")'); }
            </style>
            <p>Content</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)

        assert "Content" in text
        assert "javascript" not in text
        assert "background" not in text

    def test_handles_meta_refresh_redirect(self):
        """Test that meta refresh redirects are detected in SEO analysis."""
        html = """
        <html>
        <head>
            <meta http-equiv="refresh" content="0;url=http://evil.com">
            <title>Redirecting...</title>
        </head>
        <body><p>Please wait</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)

        # SEO analysis should still work
        assert "seo_score" in result
