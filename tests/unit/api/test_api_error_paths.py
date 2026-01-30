"""Error path tests for API server.

Tests validation errors, 404s, agent processing errors, and authentication.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the API server."""
    from agents.api.server import app

    with TestClient(app) as c:
        yield c


class TestValidationErrors:
    """Test validation error responses (422)."""

    def test_create_conversation_missing_agent(self, client: TestClient):
        """Missing required 'agent' field should return 422."""
        response = client.post("/conversations", json={})
        assert response.status_code == 422

    def test_send_message_empty_body(self, client: TestClient):
        """Missing required 'message' field should return 422."""
        response = client.post("/agents/chatbot/message", json={})
        assert response.status_code == 422

    def test_create_session_missing_agent(self, client: TestClient):
        """Missing required 'agent' field should return 422."""
        response = client.post("/sessions", json={})
        assert response.status_code == 422

    def test_send_message_invalid_json(self, client: TestClient):
        """Invalid JSON should return 422."""
        response = client.post(
            "/agents/chatbot/message",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestNotFoundErrors:
    """Test 404 error responses."""

    def test_get_nonexistent_session(self, client: TestClient):
        """Getting a non-existent session should return 404."""
        response = client.get("/sessions/nonexistent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_message_to_nonexistent_session(self, client: TestClient):
        """Sending message to non-existent session should return 404."""
        response = client.post("/sessions/nonexistent-id/message", json={"message": "hello"})
        assert response.status_code == 404

    def test_delete_nonexistent_session(self, client: TestClient):
        """Deleting a non-existent session should return 404."""
        response = client.delete("/sessions/nonexistent-id")
        assert response.status_code == 404

    def test_invalid_agent_name(self, client: TestClient):
        """Using an invalid agent name should return 404."""
        response = client.post("/agents/invalid_agent_name/message", json={"message": "hello"})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_session_invalid_agent(self, client: TestClient):
        """Creating session with invalid agent should return 404."""
        response = client.post("/sessions", json={"agent": "nonexistent_agent"})
        assert response.status_code == 404

    def test_create_conversation_invalid_agent(self, client: TestClient):
        """Creating conversation with invalid agent should return 404."""
        response = client.post("/conversations", json={"agent": "nonexistent_agent"})
        # May be 404 if agent validation runs, or 503 if no database
        assert response.status_code in (404, 503)


class TestAgentProcessingErrors:
    """Test agent processing error responses (500)."""

    def test_agent_exception_returns_500(self):
        """Agent exceptions should return 500 with error detail."""
        from agents.api.server import app

        # Create a mock agent that raises an exception
        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(side_effect=RuntimeError("Agent processing failed"))
        mock_agent.total_input_tokens = 0
        mock_agent.total_output_tokens = 0

        with patch("agents.api.server._create_agent", return_value=mock_agent):
            with TestClient(app) as client:
                response = client.post("/agents/chatbot/message", json={"message": "test"})
                assert response.status_code == 500
                assert "Agent processing failed" in response.json()["detail"]


class TestAuthenticationErrors:
    """Test authentication error responses (401)."""

    def test_missing_api_key_when_required(self):
        """Missing API key when required should return 401."""

        with patch.dict("os.environ", {"API_KEY": "secret123"}):
            # Need to reimport to pick up the env change
            import importlib

            import agents.api.server as server_module

            importlib.reload(server_module)

            with TestClient(server_module.app) as client:
                response = client.post("/agents/chatbot/message", json={"message": "test"})
                assert response.status_code == 401

    def test_invalid_api_key(self):
        """Invalid API key should return 401."""

        with patch.dict("os.environ", {"API_KEY": "secret123"}):
            import importlib

            import agents.api.server as server_module

            importlib.reload(server_module)

            with TestClient(server_module.app) as client:
                response = client.post(
                    "/agents/chatbot/message",
                    json={"message": "test"},
                    headers={"Authorization": "Bearer wrongkey"},
                )
                assert response.status_code == 401

    def test_valid_api_key_allowed(self):
        """Valid API key should be allowed through."""
        with patch.dict("os.environ", {"API_KEY": "secret123"}):
            import importlib

            import agents.api.server as server_module

            importlib.reload(server_module)

            # Mock the agent to avoid actual API calls
            mock_agent = MagicMock()
            mock_agent.process_message = AsyncMock(return_value="Hello!")
            mock_agent.total_input_tokens = 10
            mock_agent.total_output_tokens = 5

            with patch.object(server_module, "_create_agent", return_value=mock_agent):
                with TestClient(server_module.app) as client:
                    response = client.post(
                        "/agents/chatbot/message",
                        json={"message": "test"},
                        headers={"Authorization": "Bearer secret123"},
                    )
                    # Should not be 401
                    assert response.status_code != 401


class TestConversationEndpointsWithoutDatabase:
    """Test conversation endpoints when database is not configured."""

    def test_list_conversations_no_database(self):
        """List conversations without database should return 503."""
        # Clear DATABASE_URL and reload module to test without database
        import importlib

        import agents.api.server as server_module

        with patch.dict("os.environ", {"DATABASE_URL": ""}, clear=False):
            # Remove DATABASE_URL from environ
            import os

            orig_url = os.environ.pop("DATABASE_URL", None)
            try:
                importlib.reload(server_module)
                with TestClient(server_module.app) as client:
                    response = client.get("/conversations")
                    assert response.status_code == 503
                    assert "not configured" in response.json()["detail"].lower()
            finally:
                if orig_url:
                    os.environ["DATABASE_URL"] = orig_url

    def test_get_conversation_no_database(self):
        """Get conversation without database should return 503."""
        import importlib
        import os

        import agents.api.server as server_module

        orig_url = os.environ.pop("DATABASE_URL", None)
        try:
            importlib.reload(server_module)
            with TestClient(server_module.app) as client:
                response = client.get("/conversations/some-id")
                assert response.status_code == 503
        finally:
            if orig_url:
                os.environ["DATABASE_URL"] = orig_url

    def test_conversation_stats_no_database(self):
        """Get stats without database should return 503."""
        import importlib
        import os

        import agents.api.server as server_module

        orig_url = os.environ.pop("DATABASE_URL", None)
        try:
            importlib.reload(server_module)
            with TestClient(server_module.app) as client:
                response = client.get("/conversations/stats")
                assert response.status_code == 503
        finally:
            if orig_url:
                os.environ["DATABASE_URL"] = orig_url


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_returns_200(self, client: TestClient):
        """Health endpoint should always return 200."""
        response = client.get("/health")
        assert response.status_code == 200
        assert "agents_available" in response.json()

    def test_list_agents(self, client: TestClient):
        """List agents endpoint should return available agents."""
        response = client.get("/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) > 0
        # Check structure
        for agent in data["agents"]:
            assert "name" in agent
            assert "description" in agent
