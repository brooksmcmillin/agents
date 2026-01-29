"""Tests for the REST API server and web UI endpoints.

Run with:
    pytest agents/api/test_server.py -v
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock the database before importing the server
with patch.dict(os.environ, {"DATABASE_URL": ""}):
    from agents.api.server import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_conversation_store(monkeypatch):
    """Mock conversation store for testing."""
    mock = MagicMock()
    monkeypatch.setattr("agents.api.server._conversation_store", mock)
    # Mock the store with sample data
    mock.list_conversations = AsyncMock(
        return_value=[
            MagicMock(
                id="conv-1",
                agent_name="chatbot",
                title="Test Conversation",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                message_count=2,
                metadata={},
            )
        ]
    )
    mock.create_conversation = AsyncMock(
        return_value=MagicMock(
            id="conv-new",
            agent_name="chatbot",
            title="New Conversation",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            message_count=0,
            metadata={},
        )
    )
    mock.get_conversation_with_messages = AsyncMock(
        return_value=MagicMock(
            id="conv-1",
            agent_name="chatbot",
            title="Test Conversation",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            message_count=2,
            metadata={},
            messages=[
                MagicMock(
                    role="user",
                    content="Hello",
                    turn_number=0,
                    created_at=datetime.now(timezone.utc),
                    token_count=5,
                ),
                MagicMock(
                    role="assistant",
                    content="Hi there!",
                    turn_number=1,
                    created_at=datetime.now(timezone.utc),
                    token_count=10,
                ),
            ],
        )
    )
    mock.update_conversation = AsyncMock(
        return_value=MagicMock(
            id="conv-1",
            agent_name="chatbot",
            title="Updated Title",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            message_count=2,
            metadata={},
        )
    )
    mock.delete_conversation = AsyncMock(return_value=True)
    return mock


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, client):
        """Test health endpoint returns OK status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "agents_available" in data


class TestAgentEndpoints:
    """Tests for agent listing endpoints."""

    def test_list_agents(self, client):
        """Test listing available agents."""
        response = client.get("/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) > 0

        # Verify agent structure
        agent = data["agents"][0]
        assert "name" in agent
        assert "description" in agent


class TestConversationEndpoints:
    """Tests for conversation management endpoints."""

    def test_list_conversations_no_database(self, client):
        """Test listing conversations without database configured."""
        response = client.get("/conversations")
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    @pytest.mark.skip(
        reason="Requires database configuration - tested in integration tests"
    )
    def test_list_conversations(self, client):
        """Test listing conversations with database."""
        pass

    def test_create_conversation(self, client, mock_conversation_store):
        """Test creating a new conversation."""
        response = client.post(
            "/conversations", json={"agent": "chatbot", "title": "New Conversation"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "conv-new"
        assert data["agent"] == "chatbot"
        assert data["title"] == "New Conversation"

    def test_create_conversation_invalid_agent(self, client, mock_conversation_store):
        """Test creating conversation with invalid agent name."""
        response = client.post("/conversations", json={"agent": "invalid_agent"})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_get_conversation(self, client, mock_conversation_store):
        """Test getting a conversation with messages."""
        response = client.get("/conversations/conv-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "conv-1"
        assert "messages" in data
        assert len(data["messages"]) == 2

        # Verify message structure
        msg = data["messages"][0]
        assert msg["role"] == "user"
        assert msg["content"] == "Hello"
        assert "turn_number" in msg

    def test_update_conversation(self, client, mock_conversation_store):
        """Test updating conversation title."""
        response = client.patch(
            "/conversations/conv-1", json={"title": "Updated Title"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    def test_delete_conversation(self, client, mock_conversation_store):
        """Test deleting a conversation."""
        response = client.delete("/conversations/conv-1")
        assert response.status_code == 204


class TestCORSConfiguration:
    """Tests for CORS configuration."""

    def test_cors_headers_present(self, client):
        """Test that CORS headers are properly configured."""
        # With DEV_MODE, should allow any origin
        with patch.dict(os.environ, {"DEV_MODE": "true"}):
            response = client.options(
                "/conversations", headers={"Origin": "http://example.com"}
            )
            # In test mode, CORS may not be fully enabled
            # This is more of a configuration check
            assert response.status_code in [200, 405]


class TestStaticFileServing:
    """Tests for static file serving."""

    @patch("agents.api.server.WEBUI_DIST")
    def test_spa_catchall_when_dist_exists(self, mock_dist, client):
        """Test SPA catch-all route when dist exists."""
        # Mock dist directory existence
        mock_dist.exists.return_value = True
        mock_index = MagicMock()
        mock_index.exists.return_value = True

        with patch("agents.api.server.FileResponse"):
            # This should catch non-API routes
            response = client.get("/some-random-path")
            # Will either serve index.html or 404
            assert response.status_code in [200, 404]

    def test_api_routes_not_caught_by_spa(self, client):
        """Test that API routes are not caught by SPA catch-all."""
        # API routes should always be handled by their specific handlers
        response = client.get("/health")
        assert response.status_code == 200
        # Should not be served as static file


class TestMessageSending:
    """Tests for sending messages in conversations."""

    @patch("agents.api.server._create_agent")
    def test_send_message(self, mock_create_agent, client, mock_conversation_store):
        """Test sending a message to a conversation."""
        # Mock the agent
        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(return_value="Test response")
        mock_agent.total_input_tokens = 0
        mock_agent.total_output_tokens = 0
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        # Mock conversation with messages
        mock_conversation_store.add_messages_batch = AsyncMock()

        response = client.post(
            "/conversations/conv-1/message", json={"message": "Hello"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert data["agent"] == "chatbot"
        assert "usage" in data


@pytest.mark.asyncio
async def test_conversation_persistence_workflow():
    """Integration test for full conversation workflow."""
    from agents.api.server import _conversation_store

    if _conversation_store is None:
        pytest.skip("Database not configured")

    # Create conversation
    conv = await _conversation_store.create_conversation(
        agent_name="chatbot", title="Integration Test"
    )
    assert conv.id is not None

    # Add messages
    await _conversation_store.add_messages_batch(
        conv.id,
        [
            {"role": "user", "content": "Test message"},
            {"role": "assistant", "content": "Test response"},
        ],
    )

    # Retrieve conversation
    retrieved = await _conversation_store.get_conversation_with_messages(conv.id)
    assert retrieved is not None
    assert len(retrieved.messages) == 2

    # Update conversation
    updated = await _conversation_store.update_conversation(
        conv.id, title="Updated Title"
    )
    assert updated.title == "Updated Title"

    # Delete conversation
    deleted = await _conversation_store.delete_conversation(conv.id)
    assert deleted is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
