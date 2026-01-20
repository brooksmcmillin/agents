"""Base class for OAuth flow handlers.

This module provides shared functionality for OAuth handlers including
token refresh and common configuration.
"""

import logging
from abc import ABC, abstractmethod

import httpx

from .oauth_config import OAuthConfig
from .oauth_tokens import TokenSet

logger = logging.getLogger(__name__)


class OAuthHandlerBase(ABC):
    """Base class for OAuth flow handlers with shared functionality.

    This class provides common attributes and methods used by both
    the Authorization Code Flow and Device Flow handlers.
    """

    def __init__(
        self,
        oauth_config: OAuthConfig,
        scopes: str | None = None,
    ):
        """Initialize OAuth handler base.

        Args:
            oauth_config: OAuth configuration from discovery
            scopes: Space-separated scopes to request (default: use server's default)
        """
        self.oauth_config = oauth_config
        self.scopes = scopes or " ".join(oauth_config.scopes_supported or ["read"])
        self.client_id: str | None = None
        self.client_secret: str | None = None

    @abstractmethod
    async def register_client(self) -> tuple[str, str | None]:
        """Register a dynamic OAuth client.

        Returns:
            Tuple of (client_id, client_secret)
            client_secret will be None for public clients

        Raises:
            ValueError: If registration fails or endpoint not available
        """
        pass

    @abstractmethod
    async def authorize(self) -> TokenSet:
        """Run the authorization flow to obtain tokens.

        Returns:
            TokenSet with access token and optional refresh token

        Raises:
            ValueError: If authorization fails
        """
        pass

    def _parse_oauth_error(self, response: httpx.Response) -> str | None:
        """Parse OAuth error response (RFC 6749 Section 5.2).

        Args:
            response: HTTP response from token endpoint

        Returns:
            Formatted error string with error code and description, or None if parsing fails
        """
        try:
            error_data = response.json()
            error_code = error_data.get("error", "unknown_error")
            error_description = error_data.get("error_description", "")

            if error_description:
                return f"{error_code}: {error_description}"
            return error_code

        except Exception:
            # If we can't parse the error response, return None to use default error
            return None

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

            except httpx.HTTPStatusError as e:
                # Try to parse OAuth error response (RFC 6749 Section 5.2)
                error_detail = self._parse_oauth_error(e.response)
                if error_detail:
                    raise ValueError(f"Failed to refresh token: {error_detail}") from e
                raise ValueError(f"Failed to refresh token: {e}") from e
            except httpx.HTTPError as e:
                raise ValueError(f"Failed to refresh token: {e}") from e
