"""Secure token storage with encryption support.

This module provides a file-based token storage system with encryption.
The design allows easy migration to database or vault-based storage by
implementing the same interface.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TokenData(BaseModel):
    """OAuth token data with metadata."""

    access_token: str = Field(..., description="OAuth access token")
    refresh_token: str | None = Field(None, description="OAuth refresh token")
    token_type: str = Field(default="Bearer", description="Token type")
    expires_at: datetime | None = Field(None, description="Token expiration timestamp")
    scope: str | None = Field(None, description="Token scopes")

    def is_expired(self) -> bool:
        """Check if token is expired."""
        if not self.expires_at:
            return False
        # Add 5-minute buffer to avoid race conditions
        return datetime.now(timezone.utc) >= (self.expires_at - timedelta(minutes=5))

    def time_until_expiry(self) -> timedelta | None:
        """Get time until token expires."""
        if not self.expires_at:
            return None
        return self.expires_at - datetime.now(timezone.utc)


class TokenStore:
    """
    File-based token storage with optional encryption.

    This implementation can be easily replaced with database or vault storage
    by implementing the same interface (get_token, save_token, delete_token).

    Security considerations:
    - Tokens are encrypted at rest using Fernet (symmetric encryption)
    - File permissions should be restricted (600)
    - In production, consider using a proper secret management service
    """

    def __init__(self, storage_path: Path, encryption_key: str | None = None):
        """
        Initialize token store.

        Args:
            storage_path: Directory to store token files
            encryption_key: Optional encryption key (base64-encoded Fernet key)
        """
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Initialize encryption if key is provided
        self.cipher: Fernet | None = None
        if encryption_key:
            try:
                self.cipher = Fernet(encryption_key.encode())
                logger.info("Token encryption enabled")
            except Exception as e:
                logger.warning(
                    f"Failed to initialize encryption: {e}. Tokens will be stored unencrypted."
                )
        else:
            logger.warning("No encryption key provided. Tokens will be stored unencrypted.")

    def _get_token_path(self, platform: str, user_id: str = "default") -> Path:
        """Get file path for storing token."""
        # Use platform and user_id to support multiple users
        filename = f"{platform}_{user_id}.token"
        return self.storage_path / filename

    def get_token(self, platform: str, user_id: str = "default") -> TokenData | None:
        """
        Retrieve token from storage.

        Args:
            platform: Platform name (e.g., "twitter", "linkedin")
            user_id: User identifier (default: "default")

        Returns:
            TokenData if found and valid, None otherwise
        """
        token_path = self._get_token_path(platform, user_id)

        if not token_path.exists():
            logger.debug(f"No token found for {platform}:{user_id}")
            return None

        try:
            # Read token file
            with open(token_path, "rb") as f:
                data = f.read()

            # Decrypt if encryption is enabled
            if self.cipher:
                data = self.cipher.decrypt(data)

            # Parse JSON
            token_dict = json.loads(data.decode())

            # Convert to TokenData
            token = TokenData(**token_dict)

            logger.debug(f"Retrieved token for {platform}:{user_id}")
            return token

        except Exception as e:
            logger.error(f"Failed to retrieve token for {platform}:{user_id}: {e}")
            return None

    def save_token(self, platform: str, token_data: TokenData, user_id: str = "default") -> bool:
        """
        Save token to storage.

        Args:
            platform: Platform name (e.g., "twitter", "linkedin")
            token_data: Token data to save
            user_id: User identifier (default: "default")

        Returns:
            True if successful, False otherwise
        """
        token_path = self._get_token_path(platform, user_id)

        try:
            # Serialize to JSON
            token_dict = token_data.model_dump(mode="json")
            data = json.dumps(token_dict).encode()

            # Encrypt if encryption is enabled
            if self.cipher:
                data = self.cipher.encrypt(data)

            # Write to file with secure permissions from the start
            # Using os.open ensures permissions are set atomically during file creation
            import os

            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
            except Exception:
                # If write fails, close the fd and re-raise
                os.close(fd)
                raise

            logger.info(f"Saved token for {platform}:{user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save token for {platform}:{user_id}: {e}")
            return False

    def delete_token(self, platform: str, user_id: str = "default") -> bool:
        """
        Delete token from storage.

        Args:
            platform: Platform name
            user_id: User identifier

        Returns:
            True if successful, False otherwise
        """
        token_path = self._get_token_path(platform, user_id)

        try:
            if token_path.exists():
                token_path.unlink()
                logger.info(f"Deleted token for {platform}:{user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete token for {platform}:{user_id}: {e}")
            return False

    @staticmethod
    def generate_encryption_key() -> str:
        """Generate a new Fernet encryption key."""
        return Fernet.generate_key().decode()


# Migration guide for database storage:
#
# To migrate to database storage, create a new class that implements:
# - get_token(platform: str, user_id: str) -> Optional[TokenData]
# - save_token(platform: str, token_data: TokenData, user_id: str) -> bool
# - delete_token(platform: str, user_id: str) -> bool
#
# Example SQL schema:
# CREATE TABLE oauth_tokens (
#     id SERIAL PRIMARY KEY,
#     platform VARCHAR(50) NOT NULL,
#     user_id VARCHAR(255) NOT NULL,
#     access_token TEXT NOT NULL,
#     refresh_token TEXT,
#     token_type VARCHAR(50) DEFAULT 'Bearer',
#     expires_at TIMESTAMP,
#     scope TEXT,
#     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#     UNIQUE(platform, user_id)
# );
