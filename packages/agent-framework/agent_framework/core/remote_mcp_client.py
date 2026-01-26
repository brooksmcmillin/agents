"""Remote MCP client with full OAuth 2.0 support.

This client connects to a remote MCP server over streamable HTTPS with
automatic OAuth authentication including:
- OAuth discovery via .well-known endpoints
- Authorization code flow with PKCE
- Automatic token refresh
- Persistent token storage
"""

import asyncio
import logging
import os
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

import httpx
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import ImageContent, TextContent

from agent_framework.oauth.device_flow import (
    DeviceAuthorizationCallback,
    DeviceFlowHandler,
)
from agent_framework.oauth.oauth_config import OAuthConfig, discover_oauth_config
from agent_framework.oauth.oauth_flow import OAuthFlowHandler
from agent_framework.oauth.oauth_tokens import TokenSet, TokenStorage
from agent_framework.utils.errors import NotConnectedError, OAuthNotInitializedError

logger = logging.getLogger(__name__)

# Auth error message template - used throughout the module for consistent messaging
AUTH_FAILURE_MESSAGE_TEMPLATE = """Authentication failed{status_info}

The provided token appears to be expired or invalid.
Please update MCP_AUTH_TOKEN in your .env file.

To obtain a new token, run:
  uv run python scripts/mcp_auth.py"""


def _format_auth_error(status_code: int | None = None) -> str:
    """Format authentication error message with optional HTTP status code.

    Args:
        status_code: Optional HTTP status code to include in message

    Returns:
        Formatted error message string
    """
    status_info = f" (HTTP {status_code})" if status_code else ""
    return AUTH_FAILURE_MESSAGE_TEMPLATE.format(status_info=status_info)


@dataclass
class _ConnectionErrorTracker:
    """Track errors across connection retry attempts.

    This helper class consolidates error tracking for the connection retry loop,
    making it easier to maintain error context across multiple exception handlers.
    """

    last_error: Exception | None = None
    last_http_status: int | None = None

    def update(self, error: Exception, status: int | None = None) -> None:
        """Update tracked error and optionally HTTP status.

        Args:
            error: The exception that occurred
            status: Optional HTTP status code
        """
        self.last_error = error
        if status:
            self.last_http_status = status

    def update_from_cleanup(
        self, cleanup_status: int | None, cleanup_error: Exception | None
    ) -> None:
        """Update from disconnect cleanup if it found a better error.

        Args:
            cleanup_status: HTTP status from cleanup, if any
            cleanup_error: Exception from cleanup, if any
        """
        if cleanup_status and not self.last_http_status:
            self.last_http_status = cleanup_status
            if cleanup_error:
                self.last_error = cleanup_error


class RemoteMCPClient:
    """Client for connecting to remote MCP servers with OAuth authentication.

    This client automatically handles OAuth authentication:
    1. Discovers OAuth configuration from server
    2. Loads saved tokens if available
    3. Triggers OAuth flow if needed (opens browser)
    4. Refreshes tokens automatically when expired
    5. Auto-reauthenticates on 401/403 errors with seamless retry

    Auto-Reauthentication:
        When tool calls or list_tools operations fail with authentication errors
        (401, 403, "unauthorized", "token expired", etc.), the client will:
        - Automatically clear the expired token
        - Disconnect and reconnect with fresh authentication
        - Retry the operation transparently
        - Fall back to full OAuth flow if token refresh fails

        This ensures agents can run for extended periods without manual intervention,
        even when tokens expire during execution.

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

        # Device Flow (RFC 8628) for headless/CLI environments
        # Displays a code for the user to enter at a URL instead of opening browser
        client = RemoteMCPClient(
            "https://mcp.example.com/mcp/",
            prefer_device_flow=True
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
        prefer_device_flow: bool = False,
        device_authorization_callback: DeviceAuthorizationCallback | None = None,
    ):
        """Initialize remote MCP client.

        Args:
            base_url: Base URL of the remote MCP server (e.g., "https://mcp.example.com/mcp/")
            auth_token: Optional manual authentication token (bypasses OAuth if provided)
            enable_oauth: Enable automatic OAuth authentication (default: True)
            oauth_redirect_port: Port for OAuth callback server (default: 8889)
            oauth_scopes: Space-separated OAuth scopes to request (default: server's default)
            token_storage_dir: Directory for token storage (default: ~/.agents/tokens)
            prefer_device_flow: Use Device Authorization Grant (RFC 8628) instead of browser flow.
                               Useful for headless/CLI environments. Displays a code for the user
                               to enter at a URL. Falls back to browser flow if not supported.
            device_authorization_callback: Optional callback invoked when device authorization is
                               required. Use this to notify users via Slack, email, etc. about
                               pending authorizations. The callback receives DeviceAuthorizationInfo
                               with the user code and verification URLs.
        """
        # MCP server expects trailing slash - ensure it's present
        if not base_url.endswith("/"):
            base_url = base_url + "/"
            logger.debug(f"Added trailing slash to URL: {base_url}")

        self.base_url = base_url
        self.enable_oauth = enable_oauth
        self.oauth_redirect_port = oauth_redirect_port
        self.oauth_scopes = oauth_scopes
        self.prefer_device_flow = prefer_device_flow
        self.device_authorization_callback = device_authorization_callback

        # Manual token from parameter or environment
        self.manual_token = auth_token or os.getenv("MCP_AUTH_TOKEN")

        # OAuth components (initialized on connect)
        self.oauth_config: OAuthConfig | None = None
        self.oauth_flow: OAuthFlowHandler | None = None
        self.device_flow: DeviceFlowHandler | None = None
        storage_path = Path(token_storage_dir) if token_storage_dir else None
        self.token_storage = TokenStorage(storage_path)
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
            try:
                self.oauth_config = await discover_oauth_config(self.base_url)
            except Exception as e:
                logger.error("❌ Failed to discover OAuth configuration")
                logger.error(f"Server: {self.base_url}")
                logger.error(f"Error: {e}")
                logger.error(
                    "Check that the server is running and has OAuth discovery enabled at "
                    "/.well-known/oauth-authorization-server"
                )
                raise
            logger.info("✅ OAuth discovery successful")
            logger.debug(
                f"OAuth endpoints: auth={self.oauth_config.authorization_endpoint}, "
                f"token={self.oauth_config.token_endpoint}, "
                f"device={self.oauth_config.device_authorization_endpoint}"
            )
            logger.debug(f"Supported grants: {self.oauth_config.grant_types_supported}")

            # Initialize appropriate flow handler based on preference and support
            use_device_flow = self.prefer_device_flow and self.oauth_config.supports_device_flow()

            if use_device_flow:
                logger.info("✅ Using Device Authorization Grant (RFC 8628)")
                self.device_flow = DeviceFlowHandler(
                    self.oauth_config,
                    scopes=self.oauth_scopes,
                    authorization_callback=self.device_authorization_callback,
                )
            else:
                if self.prefer_device_flow:
                    logger.warning(
                        "⚠️  Device flow requested but not supported by server, falling back to browser flow"
                    )
                    logger.info(
                        f"Server supports: {', '.join(self.oauth_config.grant_types_supported or ['unknown'])}"
                    )
                else:
                    logger.info("Using browser-based OAuth flow")
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

        # Determine which flow handler to use
        flow_handler = self.device_flow or self.oauth_flow

        # Check if token is expired and try to refresh
        if self.current_token and self.current_token.is_expired():
            logger.info("Token expired, attempting refresh...")
            if self.current_token.refresh_token and flow_handler:
                try:
                    # Pass stored client credentials for refresh (needed in subsequent sessions)
                    self.current_token = await flow_handler.refresh_token(
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
            if flow_handler is None:
                raise OAuthNotInitializedError()

            if self.device_flow:
                # Device flow will display its own instructions
                logger.info("🔐 No valid token found, starting device authorization...")
            else:
                # Browser flow - print to stdout so user sees it
                logger.info("🔐 No valid token found, starting OAuth authentication...")
                print("\n" + "=" * 60)
                print("🔐 AUTHENTICATION REQUIRED")
                print("=" * 60)
                print(f"Server: {self.base_url}")
                print()
                print("Your browser will open for authentication.")
                print("Please complete the login process in your browser.")
                print("=" * 60)
                print()

            self.current_token = await flow_handler.authorize()
            self.token_storage.save_token(self.base_url, self.current_token)
            logger.info("✅ OAuth authentication successful, token saved")

        return self.current_token.access_token

    def _log_connection_attempt(self) -> None:
        """Log initial connection information."""
        logger.info(f"🔌 Connecting to remote MCP server: {self.base_url}")
        if self.manual_token:
            logger.debug("Using manual authentication token")
        elif self.enable_oauth:
            logger.debug(f"OAuth enabled (prefer_device_flow={self.prefer_device_flow})")
        else:
            logger.warning("⚠️  No authentication configured")

    def _create_bearer_auth(self, token: str) -> httpx.Auth:
        """Create Bearer token authentication for httpx.

        Args:
            token: Access token to use

        Returns:
            httpx.Auth instance configured with Bearer token
        """

        class BearerAuth(httpx.Auth):
            def __init__(self, token: str):
                self.token = token

            def auth_flow(
                self, request: httpx.Request
            ) -> Generator[httpx.Request, httpx.Response, None]:
                request.headers["Authorization"] = f"Bearer {self.token}"
                yield request

        return BearerAuth(token)

    def _log_connection_failure(self, error: BaseException, http_status: int | None) -> None:
        """Log connection failure with consistent formatting.

        Args:
            error: The exception that occurred
            http_status: HTTP status code if available
        """
        if http_status:
            logger.error(f"❌ Failed to connect to remote MCP server: HTTP {http_status}")
        else:
            logger.error(f"❌ Failed to connect to remote MCP server: {type(error).__name__}")

        logger.error(f"URL: {self.base_url}")
        logger.error(f"Error: {error}")

    def _check_auth_error(self, error: BaseException, http_status: int | None) -> bool:
        """Check if error is auth-related based on status or message.

        Args:
            error: The exception to check
            http_status: HTTP status code if available

        Returns:
            True if error appears to be authentication-related
        """
        if http_status in (401, 403):
            return True

        error_context = str(error).lower()
        return any(
            keyword in error_context for keyword in ["401", "403", "unauthorized", "authentication"]
        )

    async def _setup_streamable_connection(self, auth: httpx.Auth) -> None:
        """Setup streamable HTTP connection with error extraction.

        Args:
            auth: httpx Auth instance for authentication

        Raises:
            BaseExceptionGroup: If setup fails with exception group
            Exception: If setup fails with other error
        """
        try:
            self._streamable_context = streamablehttp_client(self.base_url, auth=auth)
            (
                self._read_stream,
                self._write_stream,
                self._get_session_id,
            ) = await self._streamable_context.__aenter__()
        except BaseExceptionGroup as eg:
            logger.debug(
                f"Caught BaseExceptionGroup during streamable setup: {len(eg.exceptions)} exceptions"
            )
            self._streamable_context = None
            for exc in eg.exceptions:
                logger.debug(f"  Exception in group: {type(exc).__name__}")
            raise
        except Exception as stream_error:
            # If streamable context failed to enter, clear it
            self._streamable_context = None
            raise stream_error

    async def _initialize_mcp_session(self) -> None:
        """Initialize MCP client session.

        Raises:
            ValueError: If streams are not initialized
            Exception: If session initialization fails
        """
        from mcp import ClientSession

        if self._read_stream is None or self._write_stream is None:
            raise ValueError("Streams not initialized - call _setup_streamable_connection first")

        logger.debug("Creating MCP session...")
        self._session = ClientSession(self._read_stream, self._write_stream)

        logger.debug("Initializing session...")
        await self._session.__aenter__()

        logger.debug("Sending MCP initialize request...")
        await self._session.initialize()
        logger.debug("MCP session initialized successfully")

    async def _attempt_connection(self) -> Self:
        """Single connection attempt with OAuth token.

        Returns:
            Self for use in async context manager

        Raises:
            Exception: If connection fails
        """
        # Get valid access token
        access_token = await self._ensure_valid_token()

        # Create auth and setup connection
        auth = self._create_bearer_auth(access_token)
        logger.debug(f"Connecting to {self.base_url} with OAuth token")

        # Setup streamable connection
        await self._setup_streamable_connection(auth)

        # Initialize MCP session
        await self._initialize_mcp_session()

        logger.info(f"✅ Connected to remote MCP server at {self.base_url}")
        return self

    async def _handle_http_error(
        self,
        error: httpx.HTTPStatusError,
        attempt: int,
        max_retries: int,
        tracker: _ConnectionErrorTracker,
    ) -> bool:
        """Handle HTTP status errors.

        Args:
            error: The HTTP status error
            attempt: Current attempt number
            max_retries: Maximum retries allowed
            tracker: Error tracker instance

        Returns:
            True if the error was handled and caller should retry, False otherwise

        Raises:
            ValueError: If auth fails and OAuth is disabled
            httpx.HTTPStatusError: If error is not retryable
        """
        tracker.update(error, error.response.status_code)

        # Cleanup partial state
        cleanup_status, cleanup_error = await self.disconnect()
        tracker.update_from_cleanup(cleanup_status, cleanup_error)

        # Check for auth errors and retry if possible
        if error.response.status_code in (401, 403) and attempt < max_retries:
            if self.enable_oauth:
                logger.warning(
                    f"Connection failed with HTTP {error.response.status_code} on attempt {attempt + 1}"
                )
                logger.info("Clearing token and retrying with reauthentication...")
                self.current_token = None
                return True  # Signal retry
            else:
                # OAuth disabled, can't retry
                logger.error(
                    f"Authentication failed with HTTP {error.response.status_code} and OAuth is disabled"
                )
                raise ValueError(_format_auth_error(error.response.status_code)) from error

        # Not retryable, log and fail
        self._log_connection_failure(error, error.response.status_code)
        return False

    async def _handle_exception_group(
        self,
        eg: BaseExceptionGroup,
        attempt: int,
        max_retries: int,
        tracker: _ConnectionErrorTracker,
    ) -> bool:
        """Handle exception groups from anyio.

        Args:
            eg: The exception group
            attempt: Current attempt number
            max_retries: Maximum retries allowed
            tracker: Error tracker instance

        Returns:
            True if handled and should retry, False otherwise

        Raises:
            ValueError: If auth fails and OAuth is disabled
            BaseExceptionGroup: If error is not retryable
        """
        logger.debug(f"Caught BaseExceptionGroup with {len(eg.exceptions)} exceptions")

        # Extract HTTP error if present
        http_error = None
        for exc in eg.exceptions:
            logger.debug(f"  Exception type: {type(exc).__name__}")
            if isinstance(exc, httpx.HTTPStatusError):
                http_error = exc
                break

        if http_error:
            # Delegate to HTTP error handler
            return await self._handle_http_error(http_error, attempt, max_retries, tracker)
        else:
            # No HTTP error, just fail
            self._log_connection_failure(eg, None)
            logger.debug(f"Exception group contained {len(eg.exceptions)} exceptions")
            return False

    async def _handle_runtime_error(
        self,
        error: asyncio.CancelledError | RuntimeError,
        attempt: int,
        max_retries: int,
        tracker: _ConnectionErrorTracker,
    ) -> bool:
        """Handle cancelled/runtime errors (often from cleanup after HTTPStatusError).

        Args:
            error: The runtime or cancelled error
            attempt: Current attempt number
            max_retries: Maximum retries allowed
            tracker: Error tracker instance

        Returns:
            True if handled and should retry, False otherwise

        Raises:
            ValueError: If auth fails and OAuth is disabled
            httpx.HTTPStatusError: If underlying HTTP error exists
            Exception: If error is not retryable
        """
        logger.debug(f"Caught {type(error).__name__}: {error}")

        # Cleanup and check for underlying HTTP error
        cleanup_status, cleanup_error = await self.disconnect()
        tracker.update_from_cleanup(cleanup_status, cleanup_error)

        if cleanup_status:
            logger.debug(f"Found HTTP {cleanup_status} error during disconnect cleanup")

        # Check if this is an auth error
        is_auth_error = self._check_auth_error(error, tracker.last_http_status)

        # Manual token with auth error - provide helpful message
        if not self.enable_oauth and is_auth_error:
            logger.error(
                f"Connection failed with manual token (HTTP {tracker.last_http_status or 'auth error'})"
            )
            raise ValueError(_format_auth_error(tracker.last_http_status)) from (
                tracker.last_error if tracker.last_error else error
            )

        # OAuth enabled with auth error - retry
        if self.enable_oauth and is_auth_error and attempt < max_retries:
            logger.warning(
                f"Connection cancelled/failed due to auth error (HTTP {tracker.last_http_status}) on attempt {attempt + 1}"
            )
            logger.info("Clearing token and retrying with reauthentication...")
            self.current_token = None
            return True

        # Not auth error or can't retry - fail with best error
        if tracker.last_error and isinstance(tracker.last_error, httpx.HTTPStatusError):
            self._log_connection_failure(tracker.last_error, tracker.last_http_status)
            raise tracker.last_error
        else:
            self._log_connection_failure(error, None)
            return False

    async def _handle_generic_error(
        self,
        error: Exception,
        attempt: int,
        max_retries: int,
        tracker: _ConnectionErrorTracker,
    ) -> bool:
        """Handle generic exceptions.

        Args:
            error: The exception
            attempt: Current attempt number
            max_retries: Maximum retries allowed
            tracker: Error tracker instance

        Returns:
            True if handled and should retry, False otherwise

        Raises:
            ValueError: If auth fails and OAuth is disabled
            Exception: If error is not retryable
        """
        tracker.update(error)

        # Cleanup
        cleanup_status, cleanup_error = await self.disconnect()
        tracker.update_from_cleanup(cleanup_status, cleanup_error)

        # Check for auth errors
        if self._is_auth_error(error) and attempt < max_retries:
            if self.enable_oauth:
                logger.warning(
                    f"Connection failed with auth-related error on attempt {attempt + 1}: {error}"
                )
                logger.info("Clearing token and retrying with reauthentication...")
                self.current_token = None
                return True
            else:
                logger.error("Authentication failed with manual token and OAuth is disabled")
                raise ValueError(_format_auth_error()) from error

        # Not retryable
        self._log_connection_failure(error, None)
        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException)):
            logger.error("Check that the server is running and accessible from your network.")
        return False

    async def connect(self) -> Self:
        """Connect to the remote MCP server with OAuth authentication.

        This method handles connection setup with automatic retry on auth errors.
        Error handling has been refactored into focused helper methods to improve
        maintainability and testability.

        Returns:
            Self for use in async context manager

        Raises:
            ValueError: If authentication fails
            httpx.HTTPStatusError: If connection fails with HTTP error
            Exception: For other connection errors
        """
        self._log_connection_attempt()

        max_retries = 1  # Only retry once for auth errors
        error_tracker = _ConnectionErrorTracker()

        for attempt in range(max_retries + 1):
            try:
                return await self._attempt_connection()

            except BaseExceptionGroup as eg:
                if not await self._handle_exception_group(eg, attempt, max_retries, error_tracker):
                    raise

            except httpx.HTTPStatusError as e:
                if not await self._handle_http_error(e, attempt, max_retries, error_tracker):
                    raise

            except (asyncio.CancelledError, RuntimeError) as e:
                if not await self._handle_runtime_error(e, attempt, max_retries, error_tracker):
                    raise

            except Exception as e:
                if not await self._handle_generic_error(e, attempt, max_retries, error_tracker):
                    raise

        # This line should never be reached - all exception handlers either retry or raise
        raise RuntimeError("Connection retry loop exhausted without resolution")

    async def disconnect(self) -> tuple[int | None, Exception | None]:
        """Disconnect from the remote MCP server.

        Returns:
            Tuple of (http_status_code, error) if an HTTP error occurred during cleanup, (None, None) otherwise
        """
        http_status = None
        http_error = None

        # Exit session context first
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except BaseExceptionGroup as eg:
                # Extract HTTP error from exception group during cleanup
                logger.debug(
                    f"Error disconnecting from MCP server (BaseExceptionGroup): {len(eg.exceptions)} exceptions"
                )
                for exc in eg.exceptions:
                    if isinstance(exc, httpx.HTTPStatusError):
                        http_status = exc.response.status_code
                        http_error = exc
                        logger.debug(f"  Found HTTP {http_status} error during disconnect")
                        break
            except (Exception, asyncio.CancelledError) as e:
                # Suppress all other errors during cleanup
                logger.debug(f"Error disconnecting from MCP server (suppressed): {e}")
            finally:
                self._session = None

        # Then close the streamable HTTP connection
        if self._streamable_context:
            try:
                await self._streamable_context.__aexit__(None, None, None)
            except BaseExceptionGroup as eg:
                # Extract HTTP error from exception group during cleanup
                logger.debug(
                    f"Error closing streamable HTTP connection (BaseExceptionGroup): {len(eg.exceptions)} exceptions"
                )
                for exc in eg.exceptions:
                    if isinstance(exc, httpx.HTTPStatusError) and not http_error:
                        http_status = exc.response.status_code
                        http_error = exc
                        logger.debug(f"  Found HTTP {http_status} error during streamable cleanup")
                        break
            except (Exception, asyncio.CancelledError) as e:
                # Suppress all other errors during cleanup
                logger.debug(f"Error closing streamable HTTP connection (suppressed): {e}")
            finally:
                self._streamable_context = None
                self._read_stream = None
                self._write_stream = None
                self._get_session_id = None

        return (http_status, http_error)

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def _is_auth_error(self, error: Exception) -> bool:
        """Check if an error is authentication-related.

        Args:
            error: The exception to check

        Returns:
            True if the error is authentication-related, False otherwise
        """
        # Check for httpx HTTPStatusError with 401/403 status
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (401, 403):
            return True

        # Check error message for auth-related keywords
        error_str = str(error).lower()
        error_indicators = [
            "401",
            "403",
            "unauthorized",
            "authentication",
            "auth",
            "token expired",
            "token invalid",
            "invalid token",
            "forbidden",
            "access denied",
        ]
        return any(indicator in error_str for indicator in error_indicators)

    async def _retry_with_reauth(self, operation_name: str, operation_func: Any) -> Any:
        """Retry an operation with reauthentication if it fails with auth error.

        Args:
            operation_name: Name of the operation for logging
            operation_func: Async function to execute

        Returns:
            Result of the operation

        Raises:
            The original exception if retry fails or error is not auth-related
        """
        try:
            return await operation_func()
        except Exception as e:
            if self._is_auth_error(e):
                logger.warning(
                    f"{operation_name} failed with auth error: {e}. Attempting to reauthenticate..."
                )

                try:
                    # Clear current token to force reauthentication
                    logger.info("Clearing expired token")
                    self.current_token = None

                    # Disconnect and reconnect with new token
                    logger.info("Disconnecting from MCP server")
                    _ = await self.disconnect()  # Ignore return value

                    logger.info("Reconnecting with new authentication")
                    await self.connect()

                    # Retry the operation
                    logger.info(f"Retrying {operation_name} after reauthentication")
                    return await operation_func()

                except Exception as retry_error:
                    logger.error(
                        f"Reauthentication and retry failed for {operation_name}: {retry_error}"
                    )
                    raise
            else:
                # Not an auth error, re-raise original exception
                raise

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the remote server.

        Returns:
            List of tool definitions with name, description, and input schema
        """
        if not self._session:
            raise NotConnectedError()

        session = self._session

        async def _list_tools_impl() -> list[dict[str, Any]]:
            response = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                for tool in response.tools
            ]

        return await self._retry_with_reauth("list_tools", _list_tools_impl)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the remote server.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if not self._session:
            raise NotConnectedError()

        session = self._session

        async def _call_tool_impl() -> Any:
            result = await session.call_tool(name, arguments)

            # Extract content from result
            if hasattr(result, "content") and result.content:
                # Return first content item (usually text or JSON)
                first_content = result.content[0]
                if isinstance(first_content, TextContent):
                    return first_content.text
                elif isinstance(first_content, ImageContent):
                    return first_content.data

            return result

        return await self._retry_with_reauth(f"call_tool({name})", _call_tool_impl)

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
                    f"{base}/health"
                    if not base.endswith("/mcp")
                    else base.replace("/mcp", "/health"),
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
