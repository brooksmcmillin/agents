"""Secure token storage with encryption support.

This module provides a file-based token storage system with encryption.
The design allows easy migration to database or vault-based storage by
implementing the same interface.
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
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
        return datetime.now(UTC) >= (self.expires_at - timedelta(minutes=5))

    def time_until_expiry(self) -> timedelta | None:
        """Get time until token expires."""
        if not self.expires_at:
            return None
        return self.expires_at - datetime.now(UTC)


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

    def __init__(
        self,
        storage_path: Path,
        encryption_key: str | None = None,
        require_encryption: bool = False,
    ) -> None:
        """
        Initialize token store.

        Args:
            storage_path: Directory to store token files
            encryption_key: Optional encryption key (base64-encoded Fernet key)
            require_encryption: If True, raise RuntimeError when encryption
                cannot be established. Use in production deployments.
        """
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        # Set restrictive directory permissions (owner only) to protect token files
        self.storage_path.chmod(0o700)

        # Initialize encryption -- auto-generate key if none provided
        self.cipher: Fernet | None = None
        if not encryption_key:
            encryption_key = self._load_or_generate_key()

        if encryption_key:
            try:
                if len(encryption_key) != 44:
                    raise ValueError(
                        f"Invalid encryption key length: {len(encryption_key)} (expected 44)"
                    )
                self.cipher = Fernet(encryption_key.encode())
                logger.info("Token encryption enabled")
            except Exception as e:
                if require_encryption:
                    raise RuntimeError(f"Encryption required but failed to initialize: {e}")
                logger.warning(
                    "Failed to initialize encryption: %s. Tokens will be stored unencrypted.", e
                )

        if require_encryption and self.cipher is None:
            raise RuntimeError("Encryption required but no key could be generated or loaded.")

    def _load_or_generate_key(self) -> str | None:
        """Load existing encryption key or generate and persist a new one.

        Uses O_EXCL for atomic file creation to prevent race conditions
        when multiple processes start simultaneously.
        """
        import os

        key_file = self.storage_path / ".encryption.key"
        try:
            if key_file.exists():
                return key_file.read_text().strip()
            key = Fernet.generate_key().decode()
            # O_EXCL ensures atomic creation — if another process created the
            # file between our exists() check and now, we get FileExistsError
            # and fall through to read their key instead.
            try:
                fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                return key_file.read_text().strip()
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(key)
            except Exception:
                os.close(fd)
                raise
            # nosem: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
            logger.info("Auto-generated token encryption key (stored at %s)", key_file)
            return key
        except Exception as e:
            logger.warning("Failed to auto-generate encryption key: %s", e)
            return None

    _SAFE_STORE_KEY_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,100}$")

    def _validate_store_key(self, value: str, field: str) -> None:
        """Validate a token store key to prevent path traversal.

        Args:
            value: The key value to validate
            field: Field name for error messages (e.g., "platform", "user_id")

        Raises:
            ValueError: If the key contains invalid characters
        """
        if not value:
            raise ValueError(f"{field} cannot be empty")
        if "\x00" in value or ".." in value or "/" in value or "\\" in value:
            raise ValueError(f"{field} contains invalid characters")
        if not self._SAFE_STORE_KEY_RE.match(value):
            raise ValueError(
                f"{field} must contain only alphanumeric characters, "
                "underscores, and hyphens (max 100 chars)"
            )

    def _get_token_path(self, platform: str, user_id: str = "default") -> Path:
        """Get file path for storing token."""
        self._validate_store_key(platform, "platform")
        self._validate_store_key(user_id, "user_id")
        filename = f"{platform}_{user_id}.token"
        token_path = (self.storage_path / filename).resolve()
        # Confinement check: ensure path stays inside storage directory
        if not token_path.is_relative_to(self.storage_path.resolve()):
            raise ValueError("Token path escapes storage directory")
        return token_path

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
