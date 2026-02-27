"""OAuth token storage and management.

This module handles storage, retrieval, and refresh of OAuth access tokens.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

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

    Stores tokens encrypted in JSON files in a configured directory
    (~/.agents/tokens by default). Each server gets its own file based
    on a hash of the server URL. Tokens are encrypted at rest using Fernet.
    """

    def __init__(
        self,
        storage_dir: Path | None = None,
        require_encryption: bool = False,
    ) -> None:
        """Initialize token storage.

        Args:
            storage_dir: Directory to store token files (default: ~/.agents/tokens)
            require_encryption: If True, raise RuntimeError when encryption
                cannot be established. Use in production deployments.
        """
        if storage_dir is None:
            storage_dir = Path.home() / ".agents" / "tokens"

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # Set restrictive directory permissions (owner only) to protect token files
        self.storage_dir.chmod(0o700)

        # Initialize encryption
        self.cipher: Fernet | None = None
        encryption_key = self._load_or_generate_key()
        if encryption_key:
            try:
                self.cipher = Fernet(encryption_key.encode())
                logger.debug("OAuth token encryption enabled")
            except Exception as e:
                if require_encryption:
                    raise RuntimeError(
                        f"Encryption required but failed to initialize: {type(e).__name__}"
                    ) from e
                logger.warning("Encryption initialization failed: %s", type(e).__name__)

        if require_encryption and self.cipher is None:
            raise RuntimeError("Encryption required but no key could be generated or loaded.")

        logger.debug(f"Token storage directory: {self.storage_dir}")

    def _load_or_generate_key(self) -> str | None:
        """Load existing encryption key or generate and persist a new one."""
        key_file = self.storage_dir / ".encryption.key"
        try:
            if key_file.exists():
                return key_file.read_text().strip()
            key = Fernet.generate_key().decode()
            # O_EXCL ensures atomic creation to prevent race conditions
            try:
                fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return key_file.read_text().strip()
            try:
                f = os.fdopen(fd, "w")
            except Exception:
                os.close(fd)
                raise
            with f:
                f.write(key)
            logger.info("Auto-generated OAuth token encryption key")
            return key
        except Exception as e:
            logger.warning("Failed to auto-generate encryption key: %s", type(e).__name__)
            return None

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
            # Serialize to JSON bytes
            raw_data = json.dumps(data, indent=2).encode()

            # Encrypt if encryption is available
            if self.cipher:
                raw_data = self.cipher.encrypt(raw_data)

            # Write token data with secure file permissions from the start
            # Using os.open ensures permissions are set atomically during file creation
            fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                f = os.fdopen(fd, "wb")
            except Exception:
                os.close(fd)
                raise
            with f:
                f.write(raw_data)
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
            with open(token_file, "rb") as f:
                raw_data = f.read()

            # Decrypt if encryption is available
            if self.cipher:
                raw_data = self.cipher.decrypt(raw_data)

            data = json.loads(raw_data.decode())

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
