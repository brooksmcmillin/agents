"""Pre-research module for tasks that need information gathering.

Uses MCP tools to fetch web content and an LLM to summarize findings
into concise, actionable notes.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Coroutine
from typing import Any

from anthropic import AsyncAnthropic

from .models import resolve_model
from .prompts import PRE_RESEARCH_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Type alias for the MCP tool-calling function
ToolCaller = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


async def do_pre_research(
    task: dict,
    search_queries: list[str],
    call_tool: ToolCaller,
    model: str = "haiku",
    api_key: str | None = None,
) -> str:
    """Perform web research for a task and summarize findings.

    1. Fetch web content for up to 3 queries using the fetch_web_content MCP tool
    2. Summarize gathered content with an LLM call
    3. Return the research summary

    Args:
        task: Task dict from MCP.
        search_queries: List of search queries to research.
        call_tool: Async function to call MCP tools (BatchAgent.call_tool).
        model: Claude model for summarization.
        api_key: Anthropic API key.

    Returns:
        Research summary string.
    """
    if not search_queries:
        return "No research queries provided."

    # Limit to 3 queries
    queries = search_queries[:3]

    # Gather raw content from web
    raw_results: list[str] = []
    for query in queries:
        try:
            result = await call_tool(
                "fetch_web_content",
                {
                    "url": f"https://www.google.com/search?q={_url_encode(query)}",
                    "extract_text": True,
                },
            )
            content = _extract_text_content(result)
            if content:
                raw_results.append(f"[Query: {query}]\n{content[:3000]}")
                logger.info(f"Fetched content for query: {query[:50]}")
        except Exception as e:
            logger.warning(f"Failed to fetch content for query '{query}': {e}")
            raw_results.append(f"[Query: {query}]\nFetch failed: {e}")

    if not raw_results:
        return "No research content could be fetched."

    # Summarize with LLM
    combined_content = "\n\n---\n\n".join(raw_results)
    summary = await _summarize_research(
        task_title=task.get("title", "Unknown task"),
        task_description=task.get("description", ""),
        raw_content=combined_content,
        model=model,
        api_key=api_key,
    )

    return summary


async def _summarize_research(
    task_title: str,
    task_description: str,
    raw_content: str,
    model: str = "haiku",
    api_key: str | None = None,
) -> str:
    """Summarize raw research content using an LLM.

    Args:
        task_title: Title of the task being researched.
        task_description: Description of the task.
        raw_content: Combined raw web content.
        model: Claude model to use.
        api_key: Anthropic API key.

    Returns:
        Summarized research notes.
    """
    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    try:
        user_message = (
            f"Task: {task_title}\n"
            f"Description: {task_description}\n\n"
            f"Research content to summarize:\n\n{raw_content[:8000]}"
        )

        response = await client.messages.create(
            model=resolve_model(model),
            max_tokens=1024,
            system=PRE_RESEARCH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        return "".join(getattr(block, "text", "") for block in response.content)

    except Exception as e:
        logger.error(f"Research summarization failed: {e}")
        return f"Research content gathered but summarization failed: {e}\n\nRaw snippets:\n{raw_content[:2000]}"
    finally:
        await client.close()


def _extract_text_content(result: Any) -> str:
    """Extract text from an MCP tool result."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # fetch_web_content returns various formats
        for key in ("text", "content", "extracted_text", "body"):
            if key in result:
                return str(result[key])
        return str(result)
    return str(result)


def _url_encode(query: str) -> str:
    """Simple URL encoding for search queries."""
    import urllib.parse

    return urllib.parse.quote_plus(query)
