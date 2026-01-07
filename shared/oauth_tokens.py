"""OAuth token storage and management.

This module handles storage, retrieval, and refresh of OAuth access tokens.
"""

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TokenSet:
    """OAuth token set with metadata."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int | None = None
    refresh_token: str | None = None
    scope: str | None = None

    # Computed fields
    issued_at: float | None = None  # Unix timestamp

    # Client credentials (needed for token refresh in subsequent sessions)
    client_id: str | None = None
    client_secret: str | None = None

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if token is expired or will expire soon.

        Args:
            buffer_seconds: Consider token expired if it expires within this many seconds

        Returns:
            True if token is expired or will expire within buffer_seconds
        """
        if self.expires_in is None or self.issued_at is None:
            # No expiration info, assume valid
            return False

        expires_at = self.issued_at + self.expires_in
        return time.time() >= (expires_at - buffer_seconds)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenSet":
        """Create from dictionary."""
        return cls(**data)

    @classmethod
    def from_oauth_response(
        cls,
        response_data: dict[str, Any],
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> "TokenSet":
        """Create from OAuth token endpoint response.

        Args:
            response_data: JSON response from token endpoint
            client_id: OAuth client ID (stored for token refresh)
            client_secret: OAuth client secret (stored for token refresh)

        Returns:
            TokenSet with issued_at set to current time
        """
        return cls(
            access_token=response_data["access_token"],
            token_type=response_data.get("token_type", "Bearer"),
            expires_in=response_data.get("expires_in"),
            refresh_token=response_data.get("refresh_token"),
            scope=response_data.get("scope"),
            issued_at=time.time(),
            client_id=client_id,
            client_secret=client_secret,
        )


class TokenStorage:
    """File-based token storage for OAuth credentials.

    Stores tokens in JSON files in a configured directory (~/.agents/tokens by default).
    Each server gets its own file based on a hash of the server URL.
    """

    def __init__(self, storage_dir: Path | None = None):
        """Initialize token storage.

        Args:
            storage_dir: Directory to store token files (default: ~/.agents/tokens)
        """
        if storage_dir is None:
            storage_dir = Path.home() / ".agents" / "tokens"

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Token storage directory: {self.storage_dir}")

    def _get_token_file(self, server_url: str) -> Path:
        """Get token file path for a server.

        Args:
            server_url: Server URL

        Returns:
            Path to token file
        """
        # Create a hash of the server URL for the filename
        url_hash = hashlib.sha256(server_url.encode()).hexdigest()[:16]
        return self.storage_dir / f"{url_hash}.json"

    def save_token(self, server_url: str, token_set: TokenSet) -> None:
        """Save token set for a server.

        Args:
            server_url: Server URL
            token_set: Token set to save
        """
        token_file = self._get_token_file(server_url)
        data = {
            "server_url": server_url,
            "token": token_set.to_dict(),
        }

        try:
            with open(token_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved token for {server_url}")
        except Exception as e:
            logger.error(f"Failed to save token: {e}")
            raise

    def load_token(self, server_url: str) -> TokenSet | None:
        """Load token set for a server.

        Args:
            server_url: Server URL

        Returns:
            TokenSet if found and valid, None otherwise
        """
        token_file = self._get_token_file(server_url)

        if not token_file.exists():
            logger.debug(f"No saved token for {server_url}")
            return None

        try:
            with open(token_file, "r") as f:
                data = json.load(f)

            # Verify server URL matches
            if data.get("server_url") != server_url:
                logger.warning(f"Token file server URL mismatch for {server_url}")
                return None

            token_set = TokenSet.from_dict(data["token"])
            logger.debug(f"Loaded token for {server_url}")
            return token_set

        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return None

    def delete_token(self, server_url: str) -> None:
        """Delete token for a server.

        Args:
            server_url: Server URL
        """
        token_file = self._get_token_file(server_url)

        if token_file.exists():
            try:
                token_file.unlink()
                logger.debug(f"Deleted token for {server_url}")
            except Exception as e:
                logger.error(f"Failed to delete token: {e}")
                raise
