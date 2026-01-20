"""Example Web Search Agent using Claude's built-in web search.

This example demonstrates how to create an agent with web search capabilities
using Claude's native web search tool.

Usage:
    python examples/web_search_agent.py

Requirements:
    - ANTHROPIC_API_KEY environment variable set
    - A running MCP server (or use the default one)
"""

import asyncio

from agent_framework import Agent


class WebSearchAgent(Agent):
    """An agent that can search the web for current information.

    This agent uses Claude's built-in web search capability to find
    up-to-date information from the internet. It can:
    - Search for current events and news
    - Look up technical documentation
    - Research topics with recent updates
    - Find and summarize web content

    The web search results are automatically cited in responses.
    """

    def get_system_prompt(self) -> str:
        return """You are a helpful research assistant with web search capabilities.

Your primary abilities:
1. **Web Search**: Search the internet for current, up-to-date information
2. **Web Reading**: Fetch and read specific web pages for detailed content
3. **Memory**: Remember important facts from our conversation

When answering questions:
- Use web search to find current and accurate information
- Always cite your sources when providing information from the web
- Combine information from multiple sources when appropriate
- Be clear about when information might be outdated or uncertain

For research tasks:
1. Start with a broad search to understand the topic
2. Narrow down to specific sources for detailed information
3. Synthesize findings into a clear, organized response
4. Provide source links for verification

You should proactively search the web when:
- Asked about current events or recent developments
- The question requires up-to-date information
- You're uncertain about facts that may have changed
- The user asks you to research something"""

    def get_agent_name(self) -> str:
        return "Web Search Agent"

    def get_greeting(self) -> str:
        return (
            "Hello! I'm your Web Search Agent. I can search the internet for "
            "current information, read web pages, and help you research topics. "
            "What would you like to know?"
        )


class RestrictedWebSearchAgent(Agent):
    """An agent with domain-restricted web search.

    This example shows how to configure web search to only search
    specific domains or exclude certain domains.
    """

    def get_system_prompt(self) -> str:
        return """You are a technical documentation assistant.

You have access to web search that is restricted to official documentation sites.
Use this to help users find accurate technical information from trusted sources.

When helping users:
- Search for relevant documentation
- Provide code examples when available
- Link to official documentation for further reading"""

    def get_agent_name(self) -> str:
        return "Docs Search Agent"


class LocalizedWebSearchAgent(Agent):
    """An agent with location-aware web search.

    This example shows how to configure web search with user location
    for localized search results.
    """

    def get_system_prompt(self) -> str:
        return """You are a local information assistant.

You can search for information relevant to the user's location.
This is useful for:
- Local news and events
- Nearby businesses and services
- Regional information and regulations
- Location-specific recommendations"""

    def get_agent_name(self) -> str:
        return "Local Search Agent"


async def main():
    """Run the Web Search Agent interactively."""
    # Basic web search agent
    agent = WebSearchAgent(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
        web_search_config={
            "max_uses": 5,  # Maximum searches per response
        },
    )

    await agent.start()


async def run_restricted_agent():
    """Example: Agent restricted to specific documentation domains."""
    agent = RestrictedWebSearchAgent(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
        web_search_config={
            "allowed_domains": [
                "docs.python.org",
                "developer.mozilla.org",
                "docs.anthropic.com",
                "react.dev",
            ],
            "max_uses": 3,
        },
    )

    await agent.start()


async def run_localized_agent():
    """Example: Agent with location-aware search."""
    agent = LocalizedWebSearchAgent(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
        web_search_config={
            "user_location": {
                "type": "approximate",
                "city": "San Francisco",
                "region": "California",
                "country": "US",
            },
            "max_uses": 5,
        },
    )

    await agent.start()


async def run_filtered_agent():
    """Example: Agent with blocked domains."""
    agent = WebSearchAgent(
        mcp_server_path="mcp_server/server.py",
        enable_web_search=True,
        web_search_config={
            "blocked_domains": [
                "pinterest.com",
                "facebook.com",
                "twitter.com",
            ],
            "max_uses": 5,
        },
    )

    await agent.start()


if __name__ == "__main__":
    # Run the basic web search agent by default
    # Uncomment other functions to try different configurations:
    # asyncio.run(run_restricted_agent())
    # asyncio.run(run_localized_agent())
    # asyncio.run(run_filtered_agent())

    asyncio.run(main())
