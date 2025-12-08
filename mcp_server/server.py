"""MCP Server for PR Agent.

This server exposes tools for web analysis, social media analytics,
and content suggestions via the Model Context Protocol.
"""

import logging
import asyncio
from typing import Any, Sequence

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
)
import mcp.server.stdio

from .config import settings
from .auth import OAuthHandler, TokenStore
from .tools import (
    analyze_website,
    fetch_web_content,
    get_social_media_stats,
    suggest_content_topics,
    save_memory,
    get_memories,
    search_memories,
)


# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(settings.log_file),
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


# Create MCP server instance
app = Server("pr-agent-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """
    List available MCP tools.

    This is called by the MCP client to discover available tools.
    Each tool is defined with its name, description, and input schema.
    """
    logger.info("Listing available tools")

    return [
        Tool(
            name="analyze_website",
            description=(
                "Fetch and analyze web content for tone, style, SEO, and engagement. "
                "Useful for understanding the characteristics of existing content "
                "and identifying opportunities for improvement."
            ),
            inputSchema={
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
        ),
        Tool(
            name="fetch_web_content",
            description=(
                "Fetch web content and convert to clean, LLM-readable markdown format. "
                "Extracts the main content from a webpage, removes navigation and ads, "
                "and returns it as markdown. Useful for reading articles, blog posts, "
                "documentation, or any web content you want to analyze or comment on."
            ),
            inputSchema={
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
        ),
        Tool(
            name="get_social_media_stats",
            description=(
                "Retrieve performance metrics from social media platforms. "
                "Provides engagement data, follower growth, top-performing posts, "
                "and actionable insights. Requires OAuth authentication."
            ),
            inputSchema={
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
        ),
        Tool(
            name="suggest_content_topics",
            description=(
                "Generate content topic suggestions based on existing content analysis, "
                "trending topics, and audience engagement. Provides detailed suggestions "
                "with reasoning, outlines, and metadata."
            ),
            inputSchema={
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
        ),
        Tool(
            name="save_memory",
            description=(
                "Save important information to persistent memory. Use this to remember "
                "user preferences, goals, insights from analyses, brand voice, and any "
                "other details that should be recalled in future conversations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Unique identifier (e.g., 'user_blog_url', 'brand_voice', 'twitter_goal')",
                    },
                    "value": {
                        "type": "string",
                        "description": "The information to remember",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category: 'user_preference', 'fact', 'goal', 'insight', etc.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for organization (e.g., ['seo', 'twitter'])",
                    },
                    "importance": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                        "description": "Importance level 1-10 (1=low, 5=medium, 10=critical)",
                    },
                },
                "required": ["key", "value"],
            },
        ),
        Tool(
            name="get_memories",
            description=(
                "Retrieve stored memories from previous conversations. Returns memories "
                "sorted by importance. Use this at the start of conversations to recall "
                "context about the user."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category (e.g., 'user_preference', 'goal')",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags (returns memories with any matching tag)",
                    },
                    "min_importance": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Only return memories with importance >= this value",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                        "description": "Maximum number of memories to return",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="search_memories",
            description=(
                "Search for memories by keyword. Searches both keys and values. "
                "Useful when you don't know the exact memory key."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term (case-insensitive)",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                        "description": "Maximum number of results",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
    """
    Execute a tool with the given arguments.

    This is called when the MCP client wants to use a tool.
    The function routes to the appropriate tool implementation and
    handles errors gracefully.

    Args:
        name: Name of the tool to call
        arguments: Dictionary of tool arguments

    Returns:
        Sequence of content blocks (typically TextContent with JSON results)

    Raises:
        ValueError: If tool name is unknown
    """
    logger.info(f"Calling tool: {name} with arguments: {arguments}")

    try:
        if name == "analyze_website":
            # Extract and validate arguments
            url = arguments.get("url")
            analysis_type = arguments.get("analysis_type")

            if not url or not analysis_type:
                raise ValueError("Missing required arguments: url and analysis_type")

            # Call the tool
            result = await analyze_website(url=url, analysis_type=analysis_type)

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        elif name == "fetch_web_content":
            # Extract and validate arguments
            url = arguments.get("url")

            if not url:
                raise ValueError("Missing required argument: url")

            # Call the tool
            result = await fetch_web_content(
                url=url,
                max_length=arguments.get("max_length", 50000),
            )

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        elif name == "get_social_media_stats":
            # Extract and validate arguments
            platform = arguments.get("platform")
            timeframe = arguments.get("timeframe")

            if not platform or not timeframe:
                raise ValueError("Missing required arguments: platform and timeframe")

            # In production: Check for valid OAuth token
            # token = await oauth_handler.get_valid_token(platform)
            # if not token:
            #     raise PermissionError(
            #         f"No valid OAuth token for {platform}. "
            #         "Please authenticate using the OAuth flow."
            #     )

            # Call the tool
            result = await get_social_media_stats(
                platform=platform,
                timeframe=timeframe,
            )

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        elif name == "suggest_content_topics":
            # Extract and validate arguments
            content_type = arguments.get("content_type")
            count = arguments.get("count", 5)

            if not content_type:
                raise ValueError("Missing required argument: content_type")

            # Call the tool
            result = await suggest_content_topics(
                content_type=content_type,
                count=count,
            )

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        elif name == "save_memory":
            # Extract and validate arguments
            key = arguments.get("key")
            value = arguments.get("value")

            if not key or not value:
                raise ValueError("Missing required arguments: key and value")

            # Call the tool
            result = await save_memory(
                key=key,
                value=value,
                category=arguments.get("category"),
                tags=arguments.get("tags"),
                importance=arguments.get("importance", 5),
            )

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        elif name == "get_memories":
            # Extract arguments (all optional)
            result = await get_memories(
                category=arguments.get("category"),
                tags=arguments.get("tags"),
                min_importance=arguments.get("min_importance"),
                limit=arguments.get("limit", 20),
            )

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        elif name == "search_memories":
            # Extract and validate arguments
            query = arguments.get("query")

            if not query:
                raise ValueError("Missing required argument: query")

            # Call the tool
            result = await search_memories(
                query=query,
                limit=arguments.get("limit", 10),
            )

            # Return as TextContent with JSON
            import json
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )
            ]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except ValueError as e:
        logger.error(f"Validation error in {name}: {e}")
        import json
        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "error": "validation_error",
                    "message": str(e),
                    "tool": name,
                }),
            )
        ]

    except PermissionError as e:
        logger.error(f"Auth error in {name}: {e}")
        import json
        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "error": "authentication_required",
                    "message": str(e),
                    "tool": name,
                    "action_required": "Please complete OAuth authentication flow",
                }),
            )
        ]

    except Exception as e:
        logger.exception(f"Error executing tool {name}: {e}")
        import json
        return [
            TextContent(
                type="text",
                text=json.dumps({
                    "error": "execution_error",
                    "message": str(e),
                    "tool": name,
                }),
            )
        ]


async def main():
    """Run the MCP server."""
    logger.info("Starting PR Agent MCP Server")
    logger.info(f"Token storage path: {settings.token_storage_path}")
    logger.info(f"Log level: {settings.log_level}")

    # Run the server using stdio transport
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP server running on stdio")
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    """Entry point for running the MCP server."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception(f"Server error: {e}")
        raise
