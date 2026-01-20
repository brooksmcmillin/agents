"""Tests for the Slack webhook tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.tools.slack import send_slack_message


class TestSendSlackMessage:
    """Tests for send_slack_message function."""

    @pytest.mark.asyncio
    async def test_send_slack_message_success(self):
        """Test send_slack_message successfully sends a message."""
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await send_slack_message(
                text="Test message",
                webhook_url="https://hooks.slack.com/services/test",
            )

        assert result["success"] is True
        assert "successfully" in result["message"]
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_slack_message_with_options(self):
        """Test send_slack_message with all optional parameters."""
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await send_slack_message(
                text="Test message",
                webhook_url="https://hooks.slack.com/services/test",
                username="TestBot",
                icon_emoji="robot_face",
                channel="#general",
            )

        assert result["success"] is True

        # Verify payload was correct
        call_args = mock_client.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["text"] == "Test message"
        assert payload["username"] == "TestBot"
        assert payload["icon_emoji"] == ":robot_face:"
        assert payload["channel"] == "#general"

    @pytest.mark.asyncio
    async def test_send_slack_message_emoji_formatting(self):
        """Test send_slack_message properly formats emoji."""
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)

            # Test emoji without colons
            await send_slack_message(
                text="Test",
                webhook_url="https://hooks.slack.com/services/test",
                icon_emoji="tada",
            )

            payload = mock_client.post.call_args.kwargs["json"]
            assert payload["icon_emoji"] == ":tada:"

    @pytest.mark.asyncio
    async def test_send_slack_message_emoji_with_colons(self):
        """Test send_slack_message handles emoji already with colons."""
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)

            await send_slack_message(
                text="Test",
                webhook_url="https://hooks.slack.com/services/test",
                icon_emoji=":rocket:",
            )

            payload = mock_client.post.call_args.kwargs["json"]
            assert payload["icon_emoji"] == ":rocket:"

    @pytest.mark.asyncio
    async def test_send_slack_message_no_webhook_url(self, monkeypatch):
        """Test send_slack_message raises error when no webhook URL."""
        # Ensure no default webhook URL is set
        with patch("agent_framework.tools.slack.settings") as mock_settings:
            mock_settings.slack_webhook_url = None

            with pytest.raises(ValueError, match="webhook_url is required"):
                await send_slack_message(text="Test message")

    @pytest.mark.asyncio
    async def test_send_slack_message_invalid_webhook_url(self):
        """Test send_slack_message raises error for invalid webhook URL."""
        with pytest.raises(ValueError, match="Invalid Slack webhook URL"):
            await send_slack_message(
                text="Test message",
                webhook_url="https://example.com/webhook",
            )

    @pytest.mark.asyncio
    async def test_send_slack_message_empty_text(self):
        """Test send_slack_message raises error for empty text."""
        with pytest.raises(ValueError, match="text is required"):
            await send_slack_message(
                text="",
                webhook_url="https://hooks.slack.com/services/test",
            )

    @pytest.mark.asyncio
    async def test_send_slack_message_unexpected_response(self):
        """Test send_slack_message handles unexpected response."""
        mock_response = MagicMock()
        mock_response.text = "invalid_token"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await send_slack_message(
                text="Test",
                webhook_url="https://hooks.slack.com/services/test",
            )

        assert result["success"] is False
        assert "Unexpected response" in result["message"]

    @pytest.mark.asyncio
    async def test_send_slack_message_http_error(self):
        """Test send_slack_message handles HTTP errors."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))

            with pytest.raises(ValueError, match="Failed to send message"):
                await send_slack_message(
                    text="Test",
                    webhook_url="https://hooks.slack.com/services/test",
                )

    @pytest.mark.asyncio
    async def test_send_slack_message_uses_env_webhook(self, monkeypatch):
        """Test send_slack_message uses webhook from settings."""
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        with patch("agent_framework.tools.slack.settings") as mock_settings:
            mock_settings.slack_webhook_url = "https://hooks.slack.com/services/env"

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None
                mock_client.post = AsyncMock(return_value=mock_response)

                result = await send_slack_message(text="Test message")

        assert result["success"] is True
        # Verify the env webhook was used
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://hooks.slack.com/services/env"

    @pytest.mark.asyncio
    async def test_send_slack_message_sanitizes_webhook_in_response(self):
        """Test send_slack_message sanitizes webhook URL in response."""
        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.raise_for_status = MagicMock()

        # Use placeholder path for testing URL sanitization
        long_webhook = (
            "https://hooks.slack.com/services/TXXXXXXXXXX/BXXXXXXXXXX/xxxxxxxxxxxxxxxxxxxx"
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            mock_client.post = AsyncMock(return_value=mock_response)

            result = await send_slack_message(
                text="Test",
                webhook_url=long_webhook,
            )

        # Should only show first 50 chars + ...
        assert result["webhook_url"].endswith("...")
        assert len(result["webhook_url"]) == 53
