"""Tests for the TokenStore and TokenData classes.

Tests cover token security, encryption, expiration logic, and error handling.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from config.mcp_server.auth.token_store import TokenData, TokenStore


class TestTokenData:
    """Tests for the TokenData model."""

    def test_token_data_creation(self):
        """Test creating a TokenData with required fields."""
        token = TokenData(access_token="test_token")
        assert token.access_token == "test_token"
        assert token.token_type == "Bearer"
        assert token.refresh_token is None
        assert token.expires_at is None
        assert token.scope is None

    def test_token_data_with_all_fields(self):
        """Test creating a TokenData with all fields."""
        expires = datetime.now(UTC) + timedelta(hours=1)
        token = TokenData(
            access_token="access",
            refresh_token="refresh",
            token_type="Bearer",
            expires_at=expires,
            scope="read write",
        )
        assert token.access_token == "access"
        assert token.refresh_token == "refresh"
        assert token.expires_at == expires
        assert token.scope == "read write"

    def test_is_expired_with_no_expiration(self):
        """Token without expiration should never expire."""
        token = TokenData(access_token="test_token", expires_at=None)
        assert not token.is_expired()

    def test_is_expired_with_future_expiration(self):
        """Token expiring in future should not be expired."""
        future = datetime.now(UTC) + timedelta(hours=1)
        token = TokenData(access_token="test_token", expires_at=future)
        assert not token.is_expired()

    def test_is_expired_with_past_expiration(self):
        """Token expiring in past should be expired."""
        past = datetime.now(UTC) - timedelta(hours=1)
        token = TokenData(access_token="test_token", expires_at=past)
        assert token.is_expired()

    def test_is_expired_with_buffer_edge_case(self):
        """Token expiring in 4 minutes should be considered expired (5-min buffer)."""
        soon = datetime.now(UTC) + timedelta(minutes=4)
        token = TokenData(access_token="test_token", expires_at=soon)
        # Should be True due to 5-min buffer
        assert token.is_expired()

    def test_is_expired_outside_buffer(self):
        """Token expiring in 6 minutes should NOT be expired (outside 5-min buffer)."""
        soon = datetime.now(UTC) + timedelta(minutes=6)
        token = TokenData(access_token="test_token", expires_at=soon)
        assert not token.is_expired()

    def test_time_until_expiry_with_no_expiration(self):
        """Token without expiration should return None for time_until_expiry."""
        token = TokenData(access_token="test_token")
        assert token.time_until_expiry() is None

    def test_time_until_expiry_with_future_expiration(self):
        """Token expiring in future should return positive timedelta."""
        future = datetime.now(UTC) + timedelta(hours=1)
        token = TokenData(access_token="test_token", expires_at=future)
        time_left = token.time_until_expiry()
        assert time_left is not None
        # Should be close to 1 hour (allow some tolerance for test execution time)
        assert timedelta(minutes=59) < time_left <= timedelta(hours=1)

    def test_time_until_expiry_with_past_expiration(self):
        """Token expiring in past should return negative timedelta."""
        past = datetime.now(UTC) - timedelta(hours=1)
        token = TokenData(access_token="test_token", expires_at=past)
        time_left = token.time_until_expiry()
        assert time_left is not None
        assert time_left < timedelta(0)


class TestTokenStore:
    """Tests for the TokenStore class."""

    @pytest.fixture
    def temp_store(self, tmp_path: Path) -> TokenStore:
        """Create a temporary unencrypted token store."""
        return TokenStore(storage_path=tmp_path / "tokens")

    @pytest.fixture
    def encrypted_store(self, tmp_path: Path) -> TokenStore:
        """Create a temporary encrypted token store."""
        key = Fernet.generate_key().decode()
        return TokenStore(
            storage_path=tmp_path / "tokens_encrypted", encryption_key=key
        )

    def test_store_creates_directory(self, tmp_path: Path):
        """Test that store creates storage directory if it doesn't exist."""
        storage_path = tmp_path / "new_tokens_dir"
        assert not storage_path.exists()
        TokenStore(storage_path=storage_path)
        assert storage_path.exists()
        assert storage_path.is_dir()

    def test_save_and_retrieve_token(self, temp_store: TokenStore):
        """Test basic token save and retrieve."""
        token = TokenData(access_token="secret_token", token_type="Bearer")
        assert temp_store.save_token("twitter", token, "user123")

        retrieved = temp_store.get_token("twitter", "user123")
        assert retrieved is not None
        assert retrieved.access_token == "secret_token"
        assert retrieved.token_type == "Bearer"

    def test_save_and_retrieve_token_default_user(self, temp_store: TokenStore):
        """Test token save/retrieve with default user_id."""
        token = TokenData(access_token="default_user_token")
        temp_store.save_token("linkedin", token)

        retrieved = temp_store.get_token("linkedin")
        assert retrieved is not None
        assert retrieved.access_token == "default_user_token"

    def test_get_nonexistent_token(self, temp_store: TokenStore):
        """Test getting a token that doesn't exist returns None."""
        retrieved = temp_store.get_token("nonexistent_platform")
        assert retrieved is None

    def test_token_persistence(self, tmp_path: Path):
        """Test that tokens persist across store instances."""
        storage_path = tmp_path / "persistent_tokens"

        # Create store and save token
        store1 = TokenStore(storage_path=storage_path)
        token = TokenData(
            access_token="persistent",
            refresh_token="refresh_me",
            scope="read write",
        )
        store1.save_token("twitter", token)

        # Create new store instance with same path
        store2 = TokenStore(storage_path=storage_path)
        retrieved = store2.get_token("twitter")

        assert retrieved is not None
        assert retrieved.access_token == "persistent"
        assert retrieved.refresh_token == "refresh_me"
        assert retrieved.scope == "read write"

    def test_encrypted_token_storage(self, encrypted_store: TokenStore):
        """Test that tokens are actually encrypted on disk."""
        token = TokenData(access_token="super_secret_token")
        encrypted_store.save_token("twitter", token)

        # Read raw file - should NOT contain plaintext token
        token_file = encrypted_store.storage_path / "twitter_default.token"
        raw_content = token_file.read_bytes()
        assert b"super_secret_token" not in raw_content

        # But should decrypt correctly
        retrieved = encrypted_store.get_token("twitter")
        assert retrieved is not None
        assert retrieved.access_token == "super_secret_token"

    def test_encrypted_store_persistence(self, tmp_path: Path):
        """Test encrypted tokens persist with same key."""
        storage_path = tmp_path / "encrypted_persistent"
        key = Fernet.generate_key().decode()

        # Save with encryption
        store1 = TokenStore(storage_path=storage_path, encryption_key=key)
        token = TokenData(access_token="encrypted_persistent_token")
        store1.save_token("platform", token)

        # Load with same key
        store2 = TokenStore(storage_path=storage_path, encryption_key=key)
        retrieved = store2.get_token("platform")

        assert retrieved is not None
        assert retrieved.access_token == "encrypted_persistent_token"

    def test_wrong_encryption_key_returns_none(self, tmp_path: Path):
        """Test that wrong encryption key returns None (handles decryption failure gracefully)."""
        storage_path = tmp_path / "wrong_key_test"
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()

        # Save with one key
        store1 = TokenStore(storage_path=storage_path, encryption_key=key1)
        token = TokenData(access_token="secret")
        store1.save_token("platform", token)

        # Try to load with different key
        store2 = TokenStore(storage_path=storage_path, encryption_key=key2)
        retrieved = store2.get_token("platform")

        # Should return None due to decryption failure
        assert retrieved is None

    def test_corrupted_token_file_returns_none(self, temp_store: TokenStore):
        """Test that corrupted token files return None."""
        # Create a corrupted token file
        token_file = temp_store.storage_path / "twitter_default.token"
        token_file.write_text("this is not valid json!!!")

        retrieved = temp_store.get_token("twitter")
        assert retrieved is None

    def test_file_permissions_are_restricted(self, temp_store: TokenStore):
        """Test that token files have 600 permissions (owner read/write only)."""
        token = TokenData(access_token="secret")
        temp_store.save_token("twitter", token)

        token_file = temp_store.storage_path / "twitter_default.token"
        # Check file permissions (should be 600 = rw-------)
        mode = token_file.stat().st_mode
        # st_mode includes file type bits, so we mask to get just permission bits
        permissions = oct(mode)[-3:]
        assert permissions == "600"

    def test_delete_token(self, temp_store: TokenStore):
        """Test deleting a token."""
        token = TokenData(access_token="to_delete")
        temp_store.save_token("twitter", token)
        assert temp_store.get_token("twitter") is not None

        deleted = temp_store.delete_token("twitter")
        assert deleted is True
        assert temp_store.get_token("twitter") is None

    def test_delete_nonexistent_token(self, temp_store: TokenStore):
        """Test deleting a token that doesn't exist returns True (idempotent)."""
        deleted = temp_store.delete_token("nonexistent")
        assert deleted is True

    def test_multiple_users_same_platform(self, temp_store: TokenStore):
        """Test storing tokens for multiple users on same platform."""
        token1 = TokenData(access_token="user1_token")
        token2 = TokenData(access_token="user2_token")

        temp_store.save_token("twitter", token1, "user1")
        temp_store.save_token("twitter", token2, "user2")

        retrieved1 = temp_store.get_token("twitter", "user1")
        retrieved2 = temp_store.get_token("twitter", "user2")

        assert retrieved1 is not None
        assert retrieved1.access_token == "user1_token"
        assert retrieved2 is not None
        assert retrieved2.access_token == "user2_token"

    def test_update_existing_token(self, temp_store: TokenStore):
        """Test that saving a token overwrites existing one."""
        token1 = TokenData(access_token="original_token")
        token2 = TokenData(access_token="updated_token")

        temp_store.save_token("twitter", token1)
        temp_store.save_token("twitter", token2)

        retrieved = temp_store.get_token("twitter")
        assert retrieved is not None
        assert retrieved.access_token == "updated_token"

    def test_generate_encryption_key(self):
        """Test that generate_encryption_key produces valid Fernet key."""
        key = TokenStore.generate_encryption_key()
        # Should be a valid Fernet key
        cipher = Fernet(key.encode())
        # Should be able to encrypt/decrypt
        encrypted = cipher.encrypt(b"test")
        decrypted = cipher.decrypt(encrypted)
        assert decrypted == b"test"

    def test_invalid_encryption_key_falls_back_to_unencrypted(self, tmp_path: Path):
        """Test that invalid encryption key falls back to unencrypted storage."""
        storage_path = tmp_path / "invalid_key_test"
        # Invalid Fernet key (not base64 encoded properly)
        store = TokenStore(storage_path=storage_path, encryption_key="invalid_key")

        # cipher should be None due to initialization failure
        assert store.cipher is None

        # Should still be able to save/retrieve tokens (unencrypted)
        token = TokenData(access_token="test")
        assert store.save_token("twitter", token)
        retrieved = store.get_token("twitter")
        assert retrieved is not None
        assert retrieved.access_token == "test"

    def test_token_with_expiration_serializes_correctly(self, temp_store: TokenStore):
        """Test that tokens with expiration times serialize/deserialize correctly."""
        expires = datetime.now(UTC) + timedelta(hours=2)
        token = TokenData(
            access_token="expiring_token",
            expires_at=expires,
        )
        temp_store.save_token("twitter", token)

        retrieved = temp_store.get_token("twitter")
        assert retrieved is not None
        assert retrieved.expires_at is not None
        # Allow 1 second tolerance for serialization
        assert abs((retrieved.expires_at - expires).total_seconds()) < 1
