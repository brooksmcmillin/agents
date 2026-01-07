"""MCP Server for PR Agent.

This server exposes tools for web analysis, social media analytics,
and content suggestions via the Model Context Protocol.
"""

import asyncio
import logging

from agent_framework.server import MCPServerBase, create_mcp_server

from .auth import OAuthHandler, TokenStore
from .config import settings
from .tools import (
    analyze_website,
    get_social_media_stats,
    suggest_content_topics,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(settings.get_log_file()),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# Initialize auth components
token_store = TokenStore(
    storage_path=settings.token_storage_path,
    encryption_key=settings.token_encryption_key,
)
oauth_handler = OAuthHandler(
    token_store=token_store,
    client_id=settings.twitter_client_id,  # Can be made platform-specific
    client_secret=settings.twitter_client_secret,
)


def setup_custom_tools(server: MCPServerBase) -> None:
    """
    Register custom PR Agent tools with the MCP server.

    Args:
        server: MCPServerBase instance to register tools on
    """
    server.register_tool(
        name="analyze_website",
        description=(
            "Fetch and analyze web content for tone, style, SEO, and engagement. "
            "Useful for understanding the characteristics of existing content "
            "and identifying opportunities for improvement."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to analyze (must start with http:// or https://)",
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["tone", "seo", "engagement"],
                    "description": (
                        "Type of analysis to perform:\n"
                        "- tone: Analyze writing style and tone\n"
                        "- seo: Analyze SEO optimization\n"
                        "- engagement: Analyze engagement potential"
                    ),
                },
            },
            "required": ["url", "analysis_type"],
        },
        handler=analyze_website,
    )

    server.register_tool(
        name="get_social_media_stats",
        description=(
            "Retrieve performance metrics from social media platforms. "
            "Provides engagement data, follower growth, top-performing posts, "
            "and actionable insights. Requires OAuth authentication."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["twitter", "linkedin"],
                    "description": (
                        "Social media platform:\n"
                        "- twitter: X/Twitter metrics\n"
                        "- linkedin: LinkedIn metrics"
                    ),
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["7d", "30d", "90d"],
                    "description": (
                        "Time period for metrics:\n"
                        "- 7d: Last 7 days\n"
                        "- 30d: Last 30 days\n"
                        "- 90d: Last 90 days"
                    ),
                },
            },
            "required": ["platform", "timeframe"],
        },
        handler=get_social_media_stats,
    )

    server.register_tool(
        name="suggest_content_topics",
        description=(
            "Generate content topic suggestions based on existing content analysis, "
            "trending topics, and audience engagement. Provides detailed suggestions "
            "with reasoning, outlines, and metadata."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content_type": {
                    "type": "string",
                    "enum": ["blog", "twitter", "linkedin"],
                    "description": (
                        "Type of content to suggest:\n"
                        "- blog: Long-form blog post ideas\n"
                        "- twitter: Short-form tweet ideas\n"
                        "- linkedin: Professional LinkedIn post ideas"
                    ),
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "description": "Number of suggestions to generate (1-10)",
                },
            },
            "required": ["content_type"],
        },
        handler=suggest_content_topics,
    )


if __name__ == "__main__":
    """Entry point for running the MCP server."""
    # Create server with default tools (memory, web fetch, slack)
    server = create_mcp_server("pr_agent")

    # Register custom tools
    setup_custom_tools(server)

    # Setup handlers and run
    server.setup_handlers()

    logger.info("Starting PR Agent MCP Server")
    logger.info(f"Token storage path: {settings.token_storage_path}")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"Registered tools: {list(server.tools.keys())}")

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception(f"Server error: {e}")
        raise
