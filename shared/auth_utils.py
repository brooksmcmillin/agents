"""Authentication utilities for MCP server access.

This module provides centralized token management for all agents and scripts,
including automatic token refresh and validation.
"""

import logging

import httpx
from agent_framework.oauth import OAuthFlowHandler, TokenStorage, discover_oauth_config

logger = logging.getLogger(__name__)


async def get_valid_token_for_mcp(mcp_url: str) -> str | None:
    """Get a valid access token from storage, refreshing if needed.

    Centralized token management for all agents and scripts. This function
    handles token loading, validation, and automatic refresh using the
    OAuth refresh token flow.

    Args:
        mcp_url: The MCP server URL

    Returns:
        Valid access token string, or None if unavailable

    Example:
        >>> token = await get_valid_token_for_mcp("https://mcp.example.com/")
        >>> if token:
        ...     # Use token for authenticated requests
        ...     headers = {"Authorization": f"Bearer {token}"}
    """
    token_storage = TokenStorage()

    # Normalize URL like RemoteMCPClient does
    if not mcp_url.endswith("/"):
        mcp_url = mcp_url + "/"

    # Try to load saved token
    token = token_storage.load_token(mcp_url)
    if not token:
        logger.warning(f"No saved token found for {mcp_url}")
        return None

    # Check if token is valid (not expired)
    if not token.is_expired():
        logger.info("Using valid token from storage")
        return token.access_token

    # Token expired - try to refresh
    logger.info("Token expired, attempting refresh...")

    if not token.refresh_token:
        logger.warning("No refresh token available")
        return None

    if not token.client_id:
        logger.warning("No client_id stored with token - cannot refresh")
        return None

    try:
        # Discover OAuth config for refresh endpoint
        oauth_config = await discover_oauth_config(mcp_url)
        oauth_flow = OAuthFlowHandler(oauth_config)

        # Refresh the token using stored client credentials
        new_token = await oauth_flow.refresh_token(
            token.refresh_token,
            client_id=token.client_id,
            client_secret=token.client_secret,
        )

        # Save the refreshed token
        token_storage.save_token(mcp_url, new_token)
        logger.info("Token refreshed successfully")

        return new_token.access_token

    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.error(f"Failed to refresh token: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error refreshing token: {e}")
        raise
