"""Tests for the token storage module."""

from datetime import datetime, timedelta
from pathlib import Path

from agent_framework.storage.token_store import TokenData, TokenStore


class TestTokenData:
    """Tests for the TokenData model."""

    def test_token_data_creation(self):
        """Test creating a TokenData object with required fields."""
        token = TokenData(access_token="test_token")

        assert token.access_token == "test_token"
        assert token.refresh_token is None
        assert token.token_type == "Bearer"
        assert token.expires_at is None
        assert token.scope is None

    def test_token_data_creation_with_all_fields(self, sample_token_data: TokenData):
        """Test creating a TokenData object with all fields."""
        assert sample_token_data.access_token == "test_access_token_12345"
        assert sample_token_data.refresh_token == "test_refresh_token_67890"
        assert sample_token_data.token_type == "Bearer"
        assert sample_token_data.expires_at is not None
        assert sample_token_data.scope == "read write"

    def test_is_expired_with_no_expiry(self):
        """Test is_expired returns False when no expiry is set."""
        token = TokenData(access_token="test")
        assert token.is_expired() is False

    def test_is_expired_with_future_expiry(self, sample_token_data: TokenData):
        """Test is_expired returns False for future expiry."""
        assert sample_token_data.is_expired() is False

    def test_is_expired_with_past_expiry(self, expired_token_data: TokenData):
        """Test is_expired returns True for past expiry."""
        assert expired_token_data.is_expired() is True

    def test_is_expired_with_buffer(self):
        """Test is_expired considers the 5-minute buffer."""
        # Token expires in 3 minutes (within the 5-minute buffer)
        token = TokenData(
            access_token="test",
            expires_at=datetime.utcnow() + timedelta(minutes=3),
        )
        assert token.is_expired() is True

        # Token expires in 10 minutes (outside the 5-minute buffer)
        token2 = TokenData(
            access_token="test",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        assert token2.is_expired() is False

    def test_time_until_expiry_no_expiry(self):
        """Test time_until_expiry returns None when no expiry is set."""
        token = TokenData(access_token="test")
        assert token.time_until_expiry() is None

    def test_time_until_expiry_with_expiry(self, sample_token_data: TokenData):
        """Test time_until_expiry returns correct timedelta."""
        time_remaining = sample_token_data.time_until_expiry()
        assert time_remaining is not None
        assert time_remaining.total_seconds() > 0


class TestTokenStore:
    """Tests for the TokenStore class."""

    def test_token_store_initialization(self, temp_dir: Path):
        """Test TokenStore initialization creates storage directory."""
        storage_path = temp_dir / "test_tokens"
        store = TokenStore(storage_path=storage_path)

        assert storage_path.exists()
        assert store.cipher is None  # No encryption by default

    def test_token_store_with_encryption(self, temp_dir: Path):
        """Test TokenStore initialization with encryption key."""
        storage_path = temp_dir / "encrypted_tokens"
        encryption_key = TokenStore.generate_encryption_key()
        store = TokenStore(storage_path=storage_path, encryption_key=encryption_key)

        assert store.cipher is not None

    def test_generate_encryption_key(self):
        """Test generating an encryption key."""
        key = TokenStore.generate_encryption_key()

        assert isinstance(key, str)
        assert len(key) > 0
        # Fernet keys are base64-encoded and 44 characters long
        assert len(key) == 44

    def test_save_and_get_token_unencrypted(
        self, token_store: TokenStore, sample_token_data: TokenData
    ):
        """Test saving and retrieving an unencrypted token."""
        success = token_store.save_token("twitter", sample_token_data)
        assert success is True

        retrieved = token_store.get_token("twitter")
        assert retrieved is not None
        assert retrieved.access_token == sample_token_data.access_token
        assert retrieved.refresh_token == sample_token_data.refresh_token
        assert retrieved.scope == sample_token_data.scope

    def test_save_and_get_token_encrypted(
        self, encrypted_token_store: TokenStore, sample_token_data: TokenData
    ):
        """Test saving and retrieving an encrypted token."""
        success = encrypted_token_store.save_token("linkedin", sample_token_data)
        assert success is True

        retrieved = encrypted_token_store.get_token("linkedin")
        assert retrieved is not None
        assert retrieved.access_token == sample_token_data.access_token
        assert retrieved.refresh_token == sample_token_data.refresh_token

    def test_get_nonexistent_token(self, token_store: TokenStore):
        """Test retrieving a non-existent token returns None."""
        result = token_store.get_token("nonexistent")
        assert result is None

    def test_save_token_with_user_id(self, token_store: TokenStore, sample_token_data: TokenData):
        """Test saving tokens with different user IDs."""
        token_store.save_token("twitter", sample_token_data, user_id="user1")
        token_store.save_token("twitter", sample_token_data, user_id="user2")

        token1 = token_store.get_token("twitter", user_id="user1")
        token2 = token_store.get_token("twitter", user_id="user2")

        assert token1 is not None
        assert token2 is not None

    def test_delete_token(self, token_store: TokenStore, sample_token_data: TokenData):
        """Test deleting a token."""
        token_store.save_token("github", sample_token_data)
        assert token_store.get_token("github") is not None

        success = token_store.delete_token("github")
        assert success is True
        assert token_store.get_token("github") is None

    def test_delete_nonexistent_token(self, token_store: TokenStore):
        """Test deleting a non-existent token returns True."""
        result = token_store.delete_token("nonexistent")
        assert result is True

    def test_token_file_permissions(self, token_store: TokenStore, sample_token_data: TokenData):
        """Test that token files have restricted permissions."""
        token_store.save_token("test_platform", sample_token_data)

        token_path = token_store._get_token_path("test_platform", "default")
        # Check that file has 600 permissions (owner read/write only)
        permissions = token_path.stat().st_mode & 0o777
        assert permissions == 0o600

    def test_token_persistence(self, temp_dir: Path, sample_token_data: TokenData):
        """Test that tokens persist across store instances."""
        storage_path = temp_dir / "persist_tokens"

        # Create store and save token
        store1 = TokenStore(storage_path=storage_path)
        store1.save_token("persist_test", sample_token_data)

        # Create new store instance
        store2 = TokenStore(storage_path=storage_path)

        # Token should be retrievable
        token = store2.get_token("persist_test")
        assert token is not None
        assert token.access_token == sample_token_data.access_token

    def test_encrypted_token_not_readable_without_key(
        self, temp_dir: Path, sample_token_data: TokenData
    ):
        """Test that encrypted tokens can't be read without the key."""
        storage_path = temp_dir / "encrypted_test"
        encryption_key = TokenStore.generate_encryption_key()

        # Save with encryption
        store1 = TokenStore(storage_path=storage_path, encryption_key=encryption_key)
        store1.save_token("secret", sample_token_data)

        # Try to read without encryption key
        store2 = TokenStore(storage_path=storage_path)
        token = store2.get_token("secret")

        # Should return None because decryption fails
        assert token is None

    def test_get_token_path(self, token_store: TokenStore):
        """Test token path generation."""
        path = token_store._get_token_path("twitter", "user123")
        assert path.name == "twitter_user123.token"
