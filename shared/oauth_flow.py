"""OAuth authorization flow with PKCE.

This module implements the OAuth 2.0 authorization code flow with PKCE
for MCP server authentication.
"""

import asyncio
import hashlib
import logging
import secrets
import webbrowser
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

import httpx
from aiohttp import web

from .oauth_config import OAuthConfig
from .oauth_tokens import TokenSet

logger = logging.getLogger(__name__)


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate code verifier (43-128 characters)
    code_verifier = (
        urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    )

    # Generate code challenge (SHA256 hash of verifier)
    code_challenge = (
        urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    return code_verifier, code_challenge


class OAuthFlowHandler:
    """Handles OAuth authorization code flow with PKCE."""

    def __init__(
        self,
        oauth_config: OAuthConfig,
        redirect_port: int = 8889,
        scopes: str | None = None,
    ):
        """Initialize OAuth flow handler.

        Args:
            oauth_config: OAuth configuration from discovery
            redirect_port: Port for local callback server (default: 8889)
            scopes: Space-separated scopes to request (default: use server's default)
        """
        self.oauth_config = oauth_config
        self.redirect_port = redirect_port
        self.redirect_uri = f"http://localhost:{redirect_port}/callback"
        self.scopes = scopes or " ".join(oauth_config.scopes_supported or ["read"])
        self.client_id: str | None = None
        self.client_secret: str | None = None

    async def register_client(self) -> tuple[str, str | None]:
        """Register a dynamic OAuth client.

        Returns:
            Tuple of (client_id, client_secret)
            client_secret will be None for public clients

        Raises:
            ValueError: If registration fails or endpoint not available
        """
        if not self.oauth_config.registration_endpoint:
            raise ValueError("Server does not support dynamic client registration")

        logger.info("Registering OAuth client...")

        # Determine if we should register as a public client
        is_public = self.oauth_config.supports_public_clients()

        registration_data = {
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none" if is_public else "client_secret_post",
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_config.registration_endpoint,
                    json=registration_data,
                )
                response.raise_for_status()
                client_data = response.json()

                client_id = client_data["client_id"]
                client_secret = client_data.get("client_secret")

                self.client_id = client_id
                self.client_secret = client_secret

                logger.info(f"Registered client: {client_id} (public: {is_public})")
                return client_id, client_secret

            except httpx.HTTPError as e:
                raise ValueError(f"Failed to register OAuth client: {e}") from e

    async def authorize(self) -> TokenSet:
        """Run the authorization code flow to obtain tokens.

        This will:
        1. Register a dynamic OAuth client (if needed)
        2. Open browser for user authorization
        3. Start local callback server
        4. Exchange authorization code for tokens

        Returns:
            TokenSet with access token and optional refresh token

        Raises:
            ValueError: If authorization fails
        """
        # Register client if not already registered
        if not self.client_id:
            await self.register_client()

        # Generate PKCE pair
        code_verifier, code_challenge = generate_pkce_pair()

        # Build authorization URL
        auth_params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scopes,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = (
            f"{self.oauth_config.authorization_endpoint}?{urlencode(auth_params)}"
        )

        logger.info("Starting OAuth authorization flow...")
        logger.info(f"Opening browser to: {auth_url}")

        # Open browser
        webbrowser.open(auth_url)

        # Start callback server and wait for code
        auth_code = await self._run_callback_server()

        if not auth_code:
            raise ValueError("Authorization failed: no code received")

        logger.info("Received authorization code, exchanging for tokens...")

        # Exchange code for tokens
        token_set = await self._exchange_code(auth_code, code_verifier)

        logger.info("✅ Successfully obtained access token")
        return token_set

    async def _run_callback_server(self) -> str | None:
        """Start local HTTP server to receive OAuth callback.

        Returns:
            Authorization code from callback, or None if error
        """
        auth_code = None
        error = None

        app = web.Application()

        async def callback(request):
            nonlocal auth_code, error

            # Check for authorization code
            if "code" in request.query:
                auth_code = request.query["code"]
                return web.Response(
                    text="""
                    <html>
                    <head><title>Authorization Successful</title></head>
                    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1 style="color: green;">✅ Authorization Successful!</h1>
                        <p>You can close this window and return to the terminal.</p>
                    </body>
                    </html>
                    """,
                    content_type="text/html",
                )

            # Check for error
            if "error" in request.query:
                error = request.query.get("error", "Unknown error")
                error_description = request.query.get("error_description", "")
                return web.Response(
                    text=f"""
                    <html>
                    <head><title>Authorization Failed</title></head>
                    <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                        <h1 style="color: red;">❌ Authorization Failed</h1>
                        <p><strong>Error:</strong> {error}</p>
                        <p>{error_description}</p>
                        <p>Please close this window and try again.</p>
                    </body>
                    </html>
                    """,
                    content_type="text/html",
                )

            return web.Response(text="Invalid callback", status=400)

        app.router.add_get("/callback", callback)

        # Start server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self.redirect_port)
        await site.start()

        logger.info(
            f"Callback server listening on http://localhost:{self.redirect_port}/callback"
        )
        logger.info("⏳ Waiting for authorization...")

        # Wait for callback (with timeout)
        timeout = 300  # 5 minutes
        start_time = asyncio.get_event_loop().time()

        while auth_code is None and error is None:
            await asyncio.sleep(0.1)
            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.error("Authorization timeout")
                break

        await runner.cleanup()

        if error:
            logger.error(f"Authorization error: {error}")
            return None

        return auth_code

    async def _exchange_code(self, code: str, code_verifier: str) -> TokenSet:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from callback
            code_verifier: PKCE code verifier

        Returns:
            TokenSet with access token (includes client credentials for refresh)

        Raises:
            ValueError: If token exchange fails
        """
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier,
        }

        # Add client secret if we have one (confidential client)
        if self.client_secret:
            token_data["client_secret"] = self.client_secret

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_config.token_endpoint,
                    data=token_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                token_response = response.json()

                # Include client credentials in TokenSet for future refresh
                return TokenSet.from_oauth_response(
                    token_response,
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                )

            except httpx.HTTPError as e:
                raise ValueError(f"Failed to exchange code for token: {e}") from e

    async def refresh_token(
        self,
        refresh_token: str,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> TokenSet:
        """Refresh an access token using a refresh token.

        Args:
            refresh_token: Refresh token
            client_id: OAuth client ID (uses self.client_id if not provided)
            client_secret: OAuth client secret (uses self.client_secret if not provided)

        Returns:
            New TokenSet with refreshed access token (includes client credentials)

        Raises:
            ValueError: If refresh fails
        """
        # Use provided credentials or fall back to instance credentials
        effective_client_id = client_id or self.client_id
        effective_client_secret = client_secret or self.client_secret

        if not effective_client_id:
            raise ValueError("Client not registered and no client_id provided")

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": effective_client_id,
        }

        # Add client secret if we have one
        if effective_client_secret:
            refresh_data["client_secret"] = effective_client_secret

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_config.token_endpoint,
                    data=refresh_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                token_response = response.json()

                # Include client credentials in TokenSet for future refresh
                return TokenSet.from_oauth_response(
                    token_response,
                    client_id=effective_client_id,
                    client_secret=effective_client_secret,
                )

            except httpx.HTTPError as e:
                raise ValueError(f"Failed to refresh token: {e}") from e
