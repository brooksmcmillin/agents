"""Web content reader tool.

This tool fetches web content and converts it to clean, LLM-readable markdown format.
Useful for reading articles, blog posts, documentation, and other web content.
"""

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

import html2text
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Validate URL is safe to fetch (SSRF protection).

    Prevents access to:
    - Private/internal IP addresses
    - Localhost
    - Cloud metadata endpoints
    - Non-HTTP(S) protocols

    Args:
        url: URL to validate

    Returns:
        Tuple of (is_safe, error_message). If safe, error_message is empty.
    """
    try:
        parsed = urlparse(url)

        # Only allow http/https
        if parsed.scheme not in ("http", "https"):
            return False, f"Protocol '{parsed.scheme}' not allowed (only http/https)"

        hostname = parsed.hostname
        if not hostname:
            return False, "URL missing hostname"

        # Block localhost variations
        localhost_names = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}  # nosec B104
        if hostname.lower() in localhost_names:
            return False, "Access to localhost not allowed"

        # Block cloud metadata endpoints (AWS, GCP, Azure)
        metadata_endpoints = {
            "169.254.169.254",  # AWS/Azure metadata
            "metadata.google.internal",  # GCP metadata
            "metadata",  # Generic metadata hostname
        }
        if hostname.lower() in metadata_endpoints:
            return False, "Access to cloud metadata endpoints not allowed"

        # Try to parse as IP address and check if it's private
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private:
                return False, f"Access to private IP addresses not allowed: {hostname}"
            if ip.is_loopback:
                return False, f"Access to loopback addresses not allowed: {hostname}"
            if ip.is_link_local:
                return False, f"Access to link-local addresses not allowed: {hostname}"
            if ip.is_reserved:
                return False, f"Access to reserved IP addresses not allowed: {hostname}"
        except ValueError:
            # Not an IP address, it's a hostname - that's OK
            # Could add DNS resolution check here for paranoid security,
            # but that adds latency and complexity
            pass

        return True, ""

    except Exception as e:
        return False, f"URL validation error: {e}"


async def fetch_web_content(url: str, max_length: int = 50000) -> dict[str, Any]:
    """
    Fetch web content and convert to LLM-readable markdown format.

    This tool fetches a webpage, extracts the main content, and converts it
    to clean markdown that's easy for LLMs to read and analyze. Removes
    navigation, footers, ads, and other non-content elements.

    Args:
        url: The URL to fetch
        max_length: Maximum content length in characters (default: 50000)

    Returns:
        Dictionary containing:
            - url: The fetched URL (may differ if redirected)
            - title: Page title
            - content: Clean markdown content
            - word_count: Number of words in content
            - char_count: Number of characters
            - has_images: Whether content contains images
            - has_links: Whether content contains links

    Raises:
        ValueError: If URL is invalid or content cannot be extracted
        httpx.HTTPError: If webpage cannot be fetched
    """
    # SSRF protection: validate URL is safe to fetch
    is_safe, error_msg = _is_safe_url(url)
    if not is_safe:
        raise ValueError(f"URL not allowed: {error_msg}")

    logger.info(f"Fetching web content from: {url}")

    try:
        # Fetch the webpage
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            html_content = response.text
            final_url = str(response.url)

        # Parse HTML
        soup = BeautifulSoup(html_content, "lxml")

        # Extract title
        title_tag = soup.find("title")
        title = title_tag.get_text().strip() if title_tag else "No title"

        # Remove unwanted elements
        for element in soup(
            ["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]
        ):
            element.decompose()

        # Try to find main content area
        main_content = None

        # Look for common content containers
        for selector in ["article", "main", '[role="main"]', ".content", ".post", ".entry-content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        # If no main content found, use body
        if not main_content:
            main_content = soup.find("body")

        if not main_content:
            raise ValueError("Could not extract content from page")

        # Convert to markdown using html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.ignore_emphasis = False
        h.body_width = 0  # Don't wrap lines
        h.unicode_snob = True
        h.skip_internal_links = True

        markdown_content = h.handle(str(main_content))

        # Clean up excessive whitespace
        lines = markdown_content.split("\n")
        cleaned_lines = []
        prev_empty = False

        for line in lines:
            line = line.rstrip()
            is_empty = len(line.strip()) == 0

            # Only add empty line if previous wasn't empty (max 1 consecutive empty line)
            if not is_empty or not prev_empty:
                cleaned_lines.append(line)

            prev_empty = is_empty

        markdown_content = "\n".join(cleaned_lines).strip()

        # Truncate if too long
        if len(markdown_content) > max_length:
            markdown_content = (
                markdown_content[:max_length] + "\n\n[Content truncated - exceeded maximum length]"
            )

        # Calculate metrics
        word_count = len(markdown_content.split())
        char_count = len(markdown_content)
        has_images = "![" in markdown_content
        has_links = "](" in markdown_content and "![" not in markdown_content

        result = {
            "url": final_url,
            "title": title,
            "content": markdown_content,
            "word_count": word_count,
            "char_count": char_count,
            "has_images": has_images,
            "has_links": has_links,
        }

        logger.info(f"Successfully fetched content from {url} ({word_count} words)")
        return result

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        raise ValueError(f"Failed to fetch URL: {e}")

    except Exception as e:
        logger.error(f"Content extraction failed for {url}: {e}")
        raise
