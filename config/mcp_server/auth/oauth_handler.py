"""OAuth 2.0 handler with auto-refresh support.

This module handles OAuth flows for different platforms with automatic
token refresh. It supports both service-to-service auth and user-delegated auth.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from authlib.integrations.httpx_client import AsyncOAuth2Client

from .token_store import TokenData, TokenStore

logger = logging.getLogger(__name__)


class OAuthHandler:
    """
    Manages OAuth 2.0 flows with automatic token refresh.

    Supports:
    - Authorization Code flow (user-delegated auth)
    - Client Credentials flow (service-to-service auth)
    - Automatic token refresh using refresh tokens
    """

    # OAuth endpoints for different platforms (mocked for now)
    PLATFORM_CONFIGS = {
        "twitter": {
            "authorize_url": "https://twitter.com/i/oauth2/authorize",
            "token_url": "https://api.twitter.com/2/oauth2/token",
            "scopes": ["tweet.read", "users.read", "offline.access"],
        },
        "linkedin": {
            "authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
            "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
            "scopes": ["r_liteprofile", "r_emailaddress", "w_member_social"],
        },
    }

    def __init__(
        self,
        token_store: TokenStore,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        """
        Initialize OAuth handler.

        Args:
            token_store: Token storage instance
            client_id: OAuth client ID (optional)
            client_secret: OAuth client secret (optional)
        """
        self.token_store = token_store
        self.client_id = client_id
        self.client_secret = client_secret

    def get_authorization_url(
        self,
        platform: str,
        redirect_uri: str,
        state: str | None = None,
    ) -> str:
        """
        Generate OAuth authorization URL for user consent.

        This is step 1 of the Authorization Code flow. The user should be
        redirected to this URL to grant permissions.

        Args:
            platform: Platform name (e.g., "twitter", "linkedin")
            redirect_uri: Callback URL after authorization
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL
        """
        if platform not in self.PLATFORM_CONFIGS:
            raise ValueError(f"Unsupported platform: {platform}")

        config = self.PLATFORM_CONFIGS[platform]

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(config["scopes"]),
        }

        if state:
            params["state"] = state

        url = f"{config['authorize_url']}?{urlencode(params)}"
        logger.info(f"Generated authorization URL for {platform}")

        return url

    async def exchange_code_for_token(
        self,
        platform: str,
        code: str,
        redirect_uri: str,
        user_id: str = "default",
    ) -> TokenData | None:
        """
        Exchange authorization code for access token.

        This is step 2 of the Authorization Code flow, called after the user
        grants permissions and is redirected back with an authorization code.

        Args:
            platform: Platform name
            code: Authorization code from callback
            redirect_uri: Same redirect URI used in authorization
            user_id: User identifier for token storage

        Returns:
            TokenData if successful, None otherwise
        """
        if platform not in self.PLATFORM_CONFIGS:
            logger.error(f"Unsupported platform: {platform}")
            return None

        config = self.PLATFORM_CONFIGS[platform]

        client = AsyncOAuth2Client(
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        try:
            # Exchange code for token
            token_response = await client.fetch_token(
                config["token_url"],
                code=code,
                redirect_uri=redirect_uri,
            )

            # Create TokenData
            token_data = self._parse_token_response(token_response)

            # Save token
            self.token_store.save_token(platform, token_data, user_id)

            logger.info(f"Successfully exchanged code for token: {platform}:{user_id}")
            return token_data

        except Exception as e:
            logger.error(f"Failed to exchange code for token: {e}")
            return None
        finally:
            await client.aclose()  # type: ignore[attr-defined]

    async def refresh_token(
        self,
        platform: str,
        user_id: str = "default",
    ) -> TokenData | None:
        """
        Refresh an expired access token using the refresh token.

        This method automatically uses the stored refresh token to obtain
        a new access token when the current one expires.

        Args:
            platform: Platform name
            user_id: User identifier

        Returns:
            New TokenData if successful, None otherwise
        """
        if platform not in self.PLATFORM_CONFIGS:
            logger.error(f"Unsupported platform: {platform}")
            return None

        # Get current token
        current_token = self.token_store.get_token(platform, user_id)
        if not current_token or not current_token.refresh_token:
            logger.error(f"No refresh token available for {platform}:{user_id}")
            return None

        config = self.PLATFORM_CONFIGS[platform]

        client = AsyncOAuth2Client(
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        try:
            # Refresh token
            token_response = await client.fetch_token(
                config["token_url"],
                grant_type="refresh_token",
                refresh_token=current_token.refresh_token,
            )

            # Create new TokenData
            token_data = self._parse_token_response(token_response)

            # Preserve refresh token if not returned in response
            if not token_data.refresh_token and current_token.refresh_token:
                token_data.refresh_token = current_token.refresh_token

            # Save new token
            self.token_store.save_token(platform, token_data, user_id)

            logger.info(f"Successfully refreshed token: {platform}:{user_id}")
            return token_data

        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            return None
        finally:
            await client.aclose()  # type: ignore[attr-defined]

    async def get_valid_token(
        self,
        platform: str,
        user_id: str = "default",
    ) -> TokenData | None:
        """
        Get a valid access token, refreshing if necessary.

        This is the main method to use when you need a token for API calls.
        It automatically handles token refresh if the token is expired.

        Args:
            platform: Platform name
            user_id: User identifier

        Returns:
            Valid TokenData if available, None if token is missing or refresh failed
        """
        # Get current token
        token = self.token_store.get_token(platform, user_id)

        if not token:
            logger.warning(f"No token found for {platform}:{user_id}")
            return None

        # Check if token is expired
        if token.is_expired():
            logger.info(f"Token expired for {platform}:{user_id}, refreshing...")
            token = await self.refresh_token(platform, user_id)

        return token

    def _parse_token_response(self, response: dict[str, Any]) -> TokenData:
        """
        Parse OAuth token response into TokenData.

        Args:
            response: Token response from OAuth provider

        Returns:
            TokenData instance
        """
        # Calculate expiration time
        expires_at = None
        if "expires_in" in response:
            expires_at = datetime.now(UTC) + timedelta(
                seconds=response["expires_in"]
            )

        return TokenData(
            access_token=response["access_token"],
            refresh_token=response.get("refresh_token"),
            token_type=response.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=response.get("scope"),
        )

    async def revoke_token(
        self,
        platform: str,
        user_id: str = "default",
    ) -> bool:
        """
        Revoke and delete stored token.

        Args:
            platform: Platform name
            user_id: User identifier

        Returns:
            True if successful, False otherwise
        """
        # In production, you would call the platform's revoke endpoint here
        # For now, just delete from storage
        return self.token_store.delete_token(platform, user_id)
