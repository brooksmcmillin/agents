"""Remote MCP client with full OAuth 2.0 support.

This client connects to a remote MCP server over streamable HTTPS with
automatic OAuth authentication including:
- OAuth discovery via .well-known endpoints
- Authorization code flow with PKCE
- Automatic token refresh
- Persistent token storage
"""

import logging
import os
from typing import Any

import httpx
from mcp.client.streamable_http import streamablehttp_client

from .oauth_config import OAuthConfig, discover_oauth_config
from .oauth_flow import OAuthFlowHandler
from .oauth_tokens import TokenSet, TokenStorage

logger = logging.getLogger(__name__)


class RemoteMCPClient:
    """Client for connecting to remote MCP servers with OAuth authentication.

    This client automatically handles OAuth authentication:
    1. Discovers OAuth configuration from server
    2. Loads saved tokens if available
    3. Triggers OAuth flow if needed (opens browser)
    4. Refreshes tokens automatically when expired
    5. Re-authenticates on 401 errors

    Usage:
        # Automatic OAuth (will open browser if needed)
        client = RemoteMCPClient("https://mcp.example.com/mcp/")
        async with client:
            tools = await client.list_tools()
            result = await client.call_tool("tool_name", {"arg": "value"})

        # With manual token (bypasses OAuth)
        client = RemoteMCPClient(
            "https://mcp.example.com/mcp/",
            auth_token="your-token"
        )

        # Custom OAuth configuration
        client = RemoteMCPClient(
            "https://mcp.example.com/mcp/",
            enable_oauth=True,
            oauth_redirect_port=8889,
            oauth_scopes="read write"
        )
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        enable_oauth: bool = True,
        oauth_redirect_port: int = 8889,
        oauth_scopes: str | None = None,
        token_storage_dir: str | None = None,
    ):
        """Initialize remote MCP client.

        Args:
            base_url: Base URL of the remote MCP server (e.g., "https://mcp.example.com/mcp/")
            auth_token: Optional manual authentication token (bypasses OAuth if provided)
            enable_oauth: Enable automatic OAuth authentication (default: True)
            oauth_redirect_port: Port for OAuth callback server (default: 8889)
            oauth_scopes: Space-separated OAuth scopes to request (default: server's default)
            token_storage_dir: Directory for token storage (default: ~/.claude-code/tokens)
        """
        # Normalize URL - ensure trailing slash for Streamable HTTP transport
        if not base_url.endswith("/"):
            base_url = base_url + "/"
            logger.debug(f"Added trailing slash to URL: {base_url}")

        self.base_url = base_url
        self.enable_oauth = enable_oauth
        self.oauth_redirect_port = oauth_redirect_port
        self.oauth_scopes = oauth_scopes

        # Manual token from parameter or environment
        self.manual_token = auth_token or os.getenv("MCP_AUTH_TOKEN")

        # OAuth components (initialized on connect)
        self.oauth_config: OAuthConfig | None = None
        self.oauth_flow: OAuthFlowHandler | None = None
        self.token_storage = TokenStorage(token_storage_dir)
        self.current_token: TokenSet | None = None

        # MCP session components
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._get_session_id = None
        self._streamable_context = None

    async def _ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, obtaining one if needed.

        Returns:
            Valid access token

        Raises:
            ValueError: If authentication fails
        """
        # If manual token provided, use it without OAuth
        if self.manual_token:
            logger.debug("Using manual token from parameter/environment")
            return self.manual_token

        # If OAuth disabled and no manual token, fail
        if not self.enable_oauth:
            raise ValueError(
                "No authentication token available and OAuth is disabled. "
                "Set auth_token parameter, MCP_AUTH_TOKEN environment variable, "
                "or enable OAuth."
            )

        # Discover OAuth config if not already done
        if not self.oauth_config:
            logger.info("Discovering OAuth configuration...")
            self.oauth_config = await discover_oauth_config(self.base_url)
            self.oauth_flow = OAuthFlowHandler(
                self.oauth_config,
                redirect_port=self.oauth_redirect_port,
                scopes=self.oauth_scopes,
            )

        # Try to load saved token
        if not self.current_token:
            self.current_token = self.token_storage.load_token(self.base_url)
            if self.current_token:
                logger.debug("Loaded saved token from storage")

        # Check if token is expired and try to refresh
        if self.current_token and self.current_token.is_expired():
            logger.info("Token expired, attempting refresh...")
            if self.current_token.refresh_token:
                try:
                    # Pass stored client credentials for refresh (needed in subsequent sessions)
                    self.current_token = await self.oauth_flow.refresh_token(
                        self.current_token.refresh_token,
                        client_id=self.current_token.client_id,
                        client_secret=self.current_token.client_secret,
                    )
                    self.token_storage.save_token(self.base_url, self.current_token)
                    logger.info("✅ Token refreshed successfully")
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}, will re-authenticate")
                    self.current_token = None

        # If no valid token, run OAuth flow
        if not self.current_token:
            logger.info("🔐 No valid token found, starting OAuth authentication...")
            print("\n" + "=" * 60)
            print("🔐 AUTHENTICATION REQUIRED")
            print("=" * 60)
            print(f"Server: {self.base_url}")
            print("\nYour browser will open for authentication.")
            print("Please complete the login process in your browser.")
            print("=" * 60 + "\n")

            self.current_token = await self.oauth_flow.authorize()
            self.token_storage.save_token(self.base_url, self.current_token)
            logger.info("✅ OAuth authentication successful, token saved")

        return self.current_token.access_token

    async def connect(self):
        """Connect to the remote MCP server with OAuth authentication."""
        try:
            # Get valid access token
            access_token = await self._ensure_valid_token()

            # Create Bearer token auth for httpx
            # This is the proper way to add authentication without overriding Accept headers
            class BearerAuth(httpx.Auth):
                def __init__(self, token: str):
                    self.token = token

                def auth_flow(self, request):
                    request.headers["Authorization"] = f"Bearer {self.token}"
                    yield request

            auth = BearerAuth(access_token)
            logger.debug(f"Connecting to {self.base_url} with OAuth token")

            # Create streamable HTTP client connection with auth parameter
            self._streamable_context = streamablehttp_client(self.base_url, auth=auth)
            self._read_stream, self._write_stream, self._get_session_id = (
                await self._streamable_context.__aenter__()
            )

            # Initialize MCP session
            from mcp import ClientSession

            logger.debug("Creating MCP session...")
            self._session = ClientSession(self._read_stream, self._write_stream)

            # Enter the session context
            logger.debug("Initializing session...")
            await self._session.__aenter__()

            # Send MCP initialize request (required by protocol)
            logger.debug("Sending MCP initialize request...")
            await self._session.initialize()
            logger.debug("MCP session initialized successfully")

            logger.info(f"✅ Connected to remote MCP server at {self.base_url}")

            return self

        except Exception as e:
            logger.error(f"Failed to connect to remote MCP server: {e}")
            raise

    async def disconnect(self):
        """Disconnect from the remote MCP server."""
        # Exit session context first
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error disconnecting from MCP server: {e}")
            finally:
                self._session = None

        # Then close the streamable HTTP connection
        if self._streamable_context:
            try:
                await self._streamable_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing streamable HTTP connection: {e}")
            finally:
                self._streamable_context = None
                self._read_stream = None
                self._write_stream = None
                self._get_session_id = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the remote server.

        Returns:
            List of tool definitions with name, description, and input schema
        """
        if not self._session:
            raise RuntimeError("Not connected. Use 'async with client' first.")

        response = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the remote server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if not self._session:
            raise RuntimeError("Not connected. Use 'async with client' first.")

        result = await self._session.call_tool(name, arguments)

        # Extract content from result
        if hasattr(result, "content") and result.content:
            # Return first content item (usually text or JSON)
            first_content = result.content[0]
            if hasattr(first_content, "text"):
                return first_content.text
            elif hasattr(first_content, "data"):
                return first_content.data

        return result

    async def health_check(self) -> bool:
        """Check if the remote server is healthy.

        Returns:
            True if server is healthy, False otherwise
        """
        try:
            # Get valid token
            access_token = await self._ensure_valid_token()
            headers = {"Authorization": f"Bearer {access_token}"}

            # Check health endpoint (if available)
            async with httpx.AsyncClient() as client:
                # Try root URL
                base = self.base_url.rstrip("/")
                response = await client.get(
                    f"{base}/health" if not base.endswith("/mcp") else base.replace("/mcp", "/health"),
                    headers=headers,
                    timeout=5.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def clear_tokens(self) -> None:
        """Clear saved tokens for this server (useful for debugging/logout)."""
        self.token_storage.delete_token(self.base_url)
        self.current_token = None
        logger.info(f"Cleared tokens for {self.base_url}")
