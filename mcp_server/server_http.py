"""HTTP/SSE transport for remote MCP server.

This server exposes MCP tools via HTTP with Server-Sent Events,
allowing remote agents to connect and use the tools.

Usage:
    uv run python -m mcp_server.server_http

Then connect from agents using RemoteMCPClient:
    from shared.remote_mcp_client import RemoteMCPClient
    client = RemoteMCPClient("http://localhost:8000")
"""

import asyncio
import logging
from typing import Any

from aiohttp import web
from mcp.server import Server
from mcp.server.sse import SseServerTransport

# Import existing tool implementations
from .tools import (
    analyze_website,
    fetch_web_content,
    get_social_media_stats,
    suggest_content_topics,
    save_memory,
    get_memories,
    search_memories,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def create_mcp_server() -> Server:
    """Create and configure the MCP server with all tools."""
    server = Server("pr-agent-mcp-remote")

    # Register list_tools handler
    @server.list_tools()
    async def handle_list_tools():
        """List all available tools."""
        return [
            {
                "name": "analyze_website",
                "description": "Analyze a website for tone, SEO, or engagement metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to analyze"},
                        "analysis_type": {
                            "type": "string",
                            "enum": ["tone", "seo", "engagement"],
                            "description": "Type of analysis",
                        },
                    },
                    "required": ["url", "analysis_type"],
                },
            },
            {
                "name": "fetch_web_content",
                "description": "Fetch web content as clean markdown for reading and analysis",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch"},
                        "max_length": {
                            "type": "number",
                            "description": "Maximum content length",
                            "default": 50000,
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "get_social_media_stats",
                "description": "Get social media performance metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "enum": ["twitter", "linkedin"],
                            "description": "Social media platform",
                        },
                        "username": {"type": "string", "description": "Username to analyze"},
                    },
                    "required": ["platform", "username"],
                },
            },
            {
                "name": "suggest_content_topics",
                "description": "Generate content topic suggestions",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content_type": {
                            "type": "string",
                            "enum": ["blog", "twitter", "linkedin"],
                            "description": "Type of content",
                        },
                        "industry": {"type": "string", "description": "Industry or topic area"},
                        "count": {
                            "type": "number",
                            "description": "Number of suggestions",
                            "default": 5,
                        },
                    },
                    "required": ["content_type", "industry"],
                },
            },
            {
                "name": "save_memory",
                "description": "Save information to persistent memory",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Unique identifier"},
                        "value": {"type": "string", "description": "Information to save"},
                        "category": {
                            "type": "string",
                            "description": "Category (user_preference, fact, goal, insight)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags for filtering",
                        },
                        "importance": {
                            "type": "number",
                            "description": "Importance (1-10)",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["key", "value"],
                },
            },
            {
                "name": "get_memories",
                "description": "Retrieve stored memories with optional filtering",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Filter by category"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by tags",
                        },
                        "min_importance": {
                            "type": "number",
                            "description": "Minimum importance",
                        },
                    },
                },
            },
            {
                "name": "search_memories",
                "description": "Search memories by keyword",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            },
        ]

    # Register call_tool handler
    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]):
        """Execute a tool and return results."""
        try:
            logger.info(f"Calling tool: {name} with args: {arguments}")

            # Route to appropriate tool
            if name == "analyze_website":
                result = await analyze_website(
                    arguments["url"], arguments["analysis_type"]
                )
            elif name == "fetch_web_content":
                result = await fetch_web_content(
                    arguments["url"], arguments.get("max_length", 50000)
                )
            elif name == "get_social_media_stats":
                result = await get_social_media_stats(
                    arguments["platform"], arguments["username"]
                )
            elif name == "suggest_content_topics":
                result = await suggest_content_topics(
                    arguments["content_type"],
                    arguments["industry"],
                    arguments.get("count", 5),
                )
            elif name == "save_memory":
                result = await save_memory(
                    arguments["key"],
                    arguments["value"],
                    arguments.get("category"),
                    arguments.get("tags", []),
                    arguments.get("importance", 5),
                )
            elif name == "get_memories":
                result = await get_memories(
                    arguments.get("category"),
                    arguments.get("tags"),
                    arguments.get("min_importance"),
                )
            elif name == "search_memories":
                result = await search_memories(arguments["query"])
            else:
                raise ValueError(f"Unknown tool: {name}")

            logger.info(f"Tool {name} completed successfully")
            return [{"type": "text", "text": str(result)}]

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}", exc_info=True)
            return [{"type": "text", "text": f"Error: {str(e)}", "isError": True}]

    return server


async def handle_sse(request: web.Request) -> web.StreamResponse:
    """Handle SSE connections for MCP."""
    logger.info(f"New SSE connection from {request.remote}")

    # Create transport
    transport = SseServerTransport("/messages")

    # Get read/write streams
    async with transport.connect_sse(
        request.url.path, request.headers
    ) as (read_stream, write_stream):
        # Create server for this connection
        server = await create_mcp_server()

        # Run server session
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

    return web.Response(text="SSE connection closed")


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "healthy", "service": "pr-agent-mcp"})


def create_app() -> web.Application:
    """Create aiohttp application."""
    app = web.Application()

    # Add routes
    app.router.add_post("/sse", handle_sse)
    app.router.add_get("/health", handle_health)

    # CORS for remote access
    async def cors_middleware(app, handler):
        async def middleware(request):
            if request.method == "OPTIONS":
                return web.Response(
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type",
                    }
                )
            response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response

        return middleware

    app.middlewares.append(cors_middleware)

    return app


def main():
    """Run the HTTP/SSE MCP server."""
    logger.info("Starting MCP HTTP/SSE server on http://0.0.0.0:8000")
    logger.info("SSE endpoint: http://0.0.0.0:8000/sse")
    logger.info("Health check: http://0.0.0.0:8000/health")

    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
