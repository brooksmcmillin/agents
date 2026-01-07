"""OAuth configuration discovery for MCP servers.

This module handles OAuth 2.0 discovery via RFC 8414 (OAuth Authorization Server Metadata)
and RFC 9908 (OAuth Protected Resource Metadata).
"""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class OAuthConfig:
    """OAuth configuration discovered from MCP server."""

    # Resource server info
    resource_url: str

    # Authorization server endpoints
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    introspection_endpoint: str | None = None

    # Supported features
    scopes_supported: list[str] | None = None
    response_types_supported: list[str] | None = None
    grant_types_supported: list[str] | None = None
    code_challenge_methods_supported: list[str] | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None

    def supports_pkce(self) -> bool:
        """Check if PKCE is supported."""
        return (
            self.code_challenge_methods_supported is not None
            and "S256" in self.code_challenge_methods_supported
        )

    def supports_public_clients(self) -> bool:
        """Check if public clients (no client secret) are supported."""
        return (
            self.token_endpoint_auth_methods_supported is not None
            and "none" in self.token_endpoint_auth_methods_supported
        )


async def discover_oauth_config(base_url: str) -> OAuthConfig:
    """Discover OAuth configuration from MCP server.

    Args:
        base_url: Base URL of the MCP server (e.g., "https://mcp.example.com/mcp/")

    Returns:
        OAuthConfig with discovered endpoints and capabilities

    Raises:
        ValueError: If OAuth discovery fails or required endpoints are missing
    """
    # Normalize URL - remove trailing /mcp/ or /mcp if present
    if base_url.endswith("/mcp/"):
        server_root = base_url[:-5]  # Remove "/mcp/"
    elif base_url.endswith("/mcp"):
        server_root = base_url[:-4]  # Remove "/mcp"
    else:
        server_root = base_url.rstrip("/")

    logger.debug(f"Discovering OAuth config for server root: {server_root}")

    async with httpx.AsyncClient() as client:
        # Step 1: Discover protected resource metadata (RFC 9908)
        resource_metadata_url = f"{server_root}/.well-known/oauth-protected-resource"
        logger.debug(f"Fetching resource metadata from: {resource_metadata_url}")

        try:
            resource_response = await client.get(resource_metadata_url)
            resource_response.raise_for_status()
            resource_metadata = resource_response.json()
        except httpx.HTTPError as e:
            raise ValueError(
                f"Failed to fetch OAuth protected resource metadata: {e}"
            ) from e

        resource_url = resource_metadata.get("resource")
        if not resource_url:
            raise ValueError("Resource metadata missing 'resource' field")

        auth_servers = resource_metadata.get("authorization_servers", [])
        if not auth_servers:
            raise ValueError("Resource metadata missing 'authorization_servers' field")

        auth_server_url = auth_servers[0].rstrip("/")  # Remove trailing slash
        logger.debug(f"Found authorization server: {auth_server_url}")

        # Step 2: Discover authorization server metadata (RFC 8414)
        # Try the standard location first
        auth_metadata_url = f"{auth_server_url}/.well-known/oauth-authorization-server"
        logger.debug(f"Fetching auth server metadata from: {auth_metadata_url}")

        try:
            auth_response = await client.get(auth_metadata_url)
            auth_response.raise_for_status()
            auth_metadata = auth_response.json()
        except httpx.HTTPError:
            # Fallback to OpenID Connect discovery
            logger.debug("Trying OpenID Connect discovery endpoint...")
            auth_metadata_url = f"{auth_server_url}/.well-known/openid-configuration"
            try:
                auth_response = await client.get(auth_metadata_url)
                auth_response.raise_for_status()
                auth_metadata = auth_response.json()
            except httpx.HTTPError as e:
                raise ValueError(
                    f"Failed to fetch OAuth authorization server metadata: {e}"
                ) from e

        # Extract required endpoints
        authorization_endpoint = auth_metadata.get("authorization_endpoint")
        token_endpoint = auth_metadata.get("token_endpoint")

        if not authorization_endpoint or not token_endpoint:
            raise ValueError(
                "Authorization server metadata missing required endpoints "
                "(authorization_endpoint, token_endpoint)"
            )

        # Build config
        config = OAuthConfig(
            resource_url=resource_url,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            registration_endpoint=auth_metadata.get("registration_endpoint"),
            introspection_endpoint=auth_metadata.get("introspection_endpoint"),
            scopes_supported=auth_metadata.get("scopes_supported"),
            response_types_supported=auth_metadata.get("response_types_supported"),
            grant_types_supported=auth_metadata.get("grant_types_supported"),
            code_challenge_methods_supported=auth_metadata.get(
                "code_challenge_methods_supported"
            ),
            token_endpoint_auth_methods_supported=auth_metadata.get(
                "token_endpoint_auth_methods_supported"
            ),
        )

        logger.info(f"Discovered OAuth config for {resource_url}")
        logger.debug(f"Authorization endpoint: {config.authorization_endpoint}")
        logger.debug(f"Token endpoint: {config.token_endpoint}")
        logger.debug(f"Supports PKCE: {config.supports_pkce()}")
        logger.debug(f"Supports public clients: {config.supports_public_clients()}")

        return config
