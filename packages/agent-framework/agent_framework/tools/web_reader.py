"""Web content reader tool.

This tool fetches web content and converts it to clean, LLM-readable markdown format.
Useful for reading articles, blog posts, documentation, and other web content.
"""

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from ..security import SSRFTransport, SSRFValidator
from ..utils.tool_decorators import handle_tool_errors

logger = logging.getLogger(__name__)


@handle_tool_errors(operation="fetch web content")
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
    # SSRF protection: validate URL and all redirects
    is_safe, result = await SSRFValidator.validate_request_with_redirects(url, max_redirects=5)
    if not is_safe:
        raise ValueError(f"URL not allowed: {result}")

    final_url = result  # result is the final URL after redirects

    logger.info(f"Fetching web content from: {url}")

    try:
        # Fetch the webpage using SSRFTransport to prevent DNS rebinding (TOCTOU).
        # Even though redirects were pre-validated, a second DNS resolution happens
        # at TCP connect time. SSRFTransport re-validates the resolved IP at that
        # moment, closing the TOCTOU gap (CWE-367).
        async with httpx.AsyncClient(
            transport=SSRFTransport(),
            timeout=15.0,
            follow_redirects=False,
        ) as client:
            response = await client.get(final_url)
            response.raise_for_status()
            html_content = response.text

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

        # Convert to markdown using markdownify
        markdown_content = md(str(main_content), heading_style="ATX", wrap=False)

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
        has_links = bool(re.search(r"(?<!!)\]\(", markdown_content))

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


# ---------------------------------------------------------------------------
# Tool schema for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "fetch_web_content",
        "description": (
            "Fetch web content and convert to clean, LLM-readable markdown format. "
            "Extracts the main content from a webpage, removes navigation and ads, "
            "and returns it as markdown. Useful for reading articles, blog posts, "
            "documentation, or any web content you want to analyze or comment on."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must start with http:// or https://)",
                },
                "max_length": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 100000,
                    "default": 50000,
                    "description": "Maximum content length in characters (default: 50000)",
                },
            },
            "required": ["url"],
        },
        "handler": fetch_web_content,
    },
]
