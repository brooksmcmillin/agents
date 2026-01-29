"""Pytest configuration and fixtures for agent-framework tests."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_framework.storage.memory_store import Memory, MemoryStore
from agent_framework.storage.token_store import TokenData, TokenStore


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def memory_store(temp_dir: Path) -> MemoryStore:
    """Create a MemoryStore with a temporary storage path."""
    return MemoryStore(storage_path=temp_dir / "memories")


@pytest.fixture
def token_store(temp_dir: Path) -> TokenStore:
    """Create a TokenStore with a temporary storage path."""
    return TokenStore(storage_path=temp_dir / "tokens")


@pytest.fixture
def encrypted_token_store(temp_dir: Path) -> TokenStore:
    """Create a TokenStore with encryption enabled."""
    encryption_key = TokenStore.generate_encryption_key()
    return TokenStore(storage_path=temp_dir / "encrypted_tokens", encryption_key=encryption_key)


@pytest.fixture
def sample_memory() -> Memory:
    """Create a sample Memory object for testing."""
    return Memory(
        key="test_key",
        value="test value",
        category="test_category",
        tags=["tag1", "tag2"],
        importance=7,
    )


@pytest.fixture
def sample_token_data() -> TokenData:
    """Create a sample TokenData object for testing."""
    return TokenData(
        access_token="test_access_token_12345",
        refresh_token="test_refresh_token_67890",
        token_type="Bearer",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scope="read write",
    )


@pytest.fixture
def expired_token_data() -> TokenData:
    """Create an expired TokenData object for testing."""
    return TokenData(
        access_token="expired_access_token",
        refresh_token="expired_refresh_token",
        token_type="Bearer",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        scope="read",
    )


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client."""
    mock_client = AsyncMock()

    # Create mock response
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = []
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    mock_client.messages.create = AsyncMock(return_value=mock_response)

    return mock_client


@pytest.fixture
def mock_httpx_response():
    """Create a mock httpx response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = (
        "<html><head><title>Test Page</title></head><body><main>Test content</main></body></html>"
    )
    mock_response.url = "https://example.com"
    mock_response.raise_for_status = MagicMock()
    return mock_response


@pytest.fixture
def mock_slack_response():
    """Create a mock Slack webhook response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "ok"
    mock_response.raise_for_status = MagicMock()
    return mock_response


@pytest.fixture(autouse=True)
def reset_memory_store_singleton(monkeypatch):
    """Reset the global memory store singletons between tests."""
    from agent_framework.tools import memory

    memory._file_memory_store = None
    memory._database_memory_store = None
    # Reset backend to default
    monkeypatch.setenv("MEMORY_BACKEND", "file")
    monkeypatch.delenv("MEMORY_DATABASE_URL", raising=False)
    yield
    memory._file_memory_store = None
    memory._database_memory_store = None


@pytest.fixture
def env_with_api_key(monkeypatch):
    """Set up environment with API key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key-12345")


@pytest.fixture
def env_without_api_key(monkeypatch):
    """Remove API key from environment."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
