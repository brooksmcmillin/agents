"""MCP Server for PR Agent.

This server exposes tools for web analysis, social media analytics,
and content suggestions via the Model Context Protocol.

All tool schemas are co-located with their implementations in
``agent_framework.tools.*`` and auto-registered via ``ALL_TOOL_SCHEMAS``.
"""

import asyncio
import logging

from agent_framework.server import create_mcp_server

from .auth import OAuthHandler, TokenStore
from .config import settings

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


if __name__ == "__main__":
    """Entry point for running the MCP server."""
    # Create server with all default tools (auto-registered from ALL_TOOL_SCHEMAS)
    server = create_mcp_server("pr_agent")

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
