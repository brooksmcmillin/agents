"""Tests for the FastMail JMAP email tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_framework.tools.fastmail import (
    JMAPClient,
    _format_email_full,
    _format_email_summary,
    _format_mailbox,
    _is_recipient_allowed,
    _sanitize_html,
    _validate_email,
    _validate_email_list,
    get_email,
    list_mailboxes,
    send_agent_report,
    send_email,
)


class TestJMAPClient:
    """Tests for the JMAPClient class."""

    def test_client_requires_api_token(self):
        """Test that JMAPClient requires an API token."""
        with patch("agent_framework.tools.fastmail.client.settings") as mock_settings:
            mock_settings.fastmail_api_token = None

            with pytest.raises(ValueError) as exc_info:
                JMAPClient()

            assert "FastMail API token required" in str(exc_info.value)

    def test_client_accepts_explicit_token(self):
        """Test that JMAPClient accepts explicit API token."""
        with patch("agent_framework.tools.fastmail.client.settings") as mock_settings:
            mock_settings.fastmail_api_token = None

            client = JMAPClient(api_token="test-token-123")
            assert client.api_token == "test-token-123"

    def test_client_uses_settings_token(self):
        """Test that JMAPClient uses token from settings."""
        with patch("agent_framework.tools.fastmail.client.settings") as mock_settings:
            mock_settings.fastmail_api_token = "settings-token"

            client = JMAPClient()
            assert client.api_token == "settings-token"


class TestEmailFormatting:
    """Tests for email formatting helpers."""

    def test_format_email_summary(self):
        """Test email summary formatting."""
        email = {
            "id": "email-123",
            "threadId": "thread-456",
            "mailboxIds": {"inbox-id": True},
            "from": [{"email": "sender@example.com", "name": "Sender"}],
            "to": [{"email": "recipient@example.com"}],
            "subject": "Test Subject",
            "receivedAt": "2024-01-15T10:30:00Z",
            "keywords": {"$seen": True, "$flagged": True},
            "hasAttachment": True,
            "preview": "This is a preview...",
        }

        result = _format_email_summary(email)

        assert result["id"] == "email-123"
        assert result["thread_id"] == "thread-456"
        assert result["mailbox_ids"] == ["inbox-id"]
        assert result["subject"] == "Test Subject"
        assert result["is_unread"] is False  # $seen is present
        assert result["is_flagged"] is True
        assert result["has_attachment"] is True
        assert result["preview"] == "This is a preview..."

    def test_format_email_summary_unread(self):
        """Test email summary correctly identifies unread emails."""
        email = {
            "id": "email-123",
            "keywords": {},  # No $seen keyword = unread
        }

        result = _format_email_summary(email)
        assert result["is_unread"] is True

    def test_format_email_full_with_text_body(self):
        """Test full email formatting with text body."""
        email = {
            "id": "email-123",
            "threadId": "thread-456",
            "mailboxIds": {},
            "from": [],
            "to": [],
            "subject": "Test",
            "receivedAt": "2024-01-15T10:30:00Z",
            "keywords": {},
            "hasAttachment": False,
            "preview": "",
            "textBody": [{"partId": "1"}],
            "htmlBody": [],
            "bodyValues": {"1": {"value": "Plain text content"}},
            "cc": [],
            "bcc": [],
            "replyTo": [],
            "inReplyTo": None,
            "references": [],
            "messageId": ["msg-id"],
            "sentAt": "2024-01-15T10:29:00Z",
            "size": 1024,
        }

        result = _format_email_full(email)

        assert result["body_text"] == "Plain text content"
        assert result["body_html"] == ""
        assert result["size"] == 1024

    def test_format_mailbox(self):
        """Test mailbox formatting."""
        mailbox = {
            "id": "mailbox-123",
            "name": "Inbox",
            "role": "inbox",
            "parentId": None,
            "totalEmails": 100,
            "unreadEmails": 5,
            "totalThreads": 80,
            "unreadThreads": 3,
            "sortOrder": 0,
            "isSubscribed": True,
        }

        result = _format_mailbox(mailbox)

        assert result["id"] == "mailbox-123"
        assert result["name"] == "Inbox"
        assert result["role"] == "inbox"
        assert result["total_emails"] == 100
        assert result["unread_emails"] == 5


class TestSecurityHelpers:
    """Tests for security-related helper functions."""

    def test_validate_email_valid(self):
        """Test validation of valid email addresses."""
        valid_emails = [
            "user@example.com",
            "user.name@example.com",
            "user+tag@example.com",
            "user@subdomain.example.com",
        ]
        for email in valid_emails:
            assert _validate_email(email), f"{email} should be valid"

    def test_validate_email_invalid(self):
        """Test validation rejects invalid email addresses."""
        invalid_emails = [
            "",
            "not-an-email",
            "@example.com",
            "user@",
            "user@.com",
            None,
            "a" * 65 + "@example.com",  # Local part too long
        ]
        for email in invalid_emails:
            assert not _validate_email(email), f"{email} should be invalid"

    def test_validate_email_list(self):
        """Test validation of email lists."""
        valid, invalid = _validate_email_list(["user@example.com", "bad-email"])
        assert valid is False
        assert invalid == ["bad-email"]

        valid, invalid = _validate_email_list(["user@example.com", "other@test.com"])
        assert valid is True
        assert invalid == []

    def test_is_recipient_allowed_exact_match(self):
        """Test exact email matching in allowlist."""
        patterns = ["allowed@example.com", "admin@test.com"]
        assert _is_recipient_allowed("allowed@example.com", patterns)
        assert _is_recipient_allowed("ALLOWED@example.com", patterns)  # Case insensitive
        assert not _is_recipient_allowed("other@example.com", patterns)

    def test_is_recipient_allowed_wildcard_domain(self):
        """Test wildcard domain matching in allowlist."""
        patterns = ["*@example.com"]
        assert _is_recipient_allowed("anyone@example.com", patterns)
        assert _is_recipient_allowed("user@EXAMPLE.COM", patterns)  # Case insensitive
        assert not _is_recipient_allowed("user@other.com", patterns)

    def test_sanitize_html_safe_content(self):
        """Test that safe HTML passes through."""
        safe_html = "<p>Hello <strong>world</strong></p>"
        assert _sanitize_html(safe_html) == safe_html

    def test_sanitize_html_blocks_script(self):
        """Test that script tags are escaped."""
        dangerous = "<script>alert('xss')</script>"
        result = _sanitize_html(dangerous)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_sanitize_html_blocks_event_handlers(self):
        """Test that event handlers are escaped (rendered as text, not executable)."""
        dangerous = '<img src="x" onerror="alert(1)">'
        result = _sanitize_html(dangerous)
        # The entire content is HTML-escaped, making it non-executable
        assert "&lt;img" in result  # < is escaped
        assert "<img" not in result  # Raw tag is gone

    def test_sanitize_html_blocks_javascript_urls(self):
        """Test that javascript: URLs are escaped (rendered as text, not executable)."""
        dangerous = '<a href="javascript:alert(1)">click</a>'
        result = _sanitize_html(dangerous)
        # The entire content is HTML-escaped, making it non-executable
        assert "&lt;a" in result  # < is escaped
        assert "<a href" not in result  # Raw tag is gone


class TestListMailboxes:
    """Tests for list_mailboxes function."""

    @pytest.mark.asyncio
    async def test_list_mailboxes_success(self):
        """Test successful mailbox listing."""
        mock_response = {
            "methodResponses": [
                [
                    "Mailbox/get",
                    {
                        "list": [
                            {"id": "inbox", "name": "Inbox", "role": "inbox"},
                            {"id": "sent", "name": "Sent", "role": "sent"},
                        ]
                    },
                    "mailbox-list",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.mailbox._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await list_mailboxes()

            assert result["status"] == "success"
            assert result["total_count"] == 2
            assert len(result["mailboxes"]) == 2

    @pytest.mark.asyncio
    async def test_list_mailboxes_auth_error(self):
        """Test authentication error handling."""
        with patch("agent_framework.tools.fastmail.mailbox._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Unauthorized",
                    request=MagicMock(),
                    response=MagicMock(status_code=401),
                )
            )
            mock_get_client.return_value = mock_client

            result = await list_mailboxes()

            assert result["status"] == "error"
            assert result["error_type"] == "AuthenticationError"
            assert result["status_code"] == 401


class TestSendEmail:
    """Tests for send_email function."""

    @pytest.mark.asyncio
    async def test_send_email_requires_recipients(self):
        """Test that send_email requires at least one recipient."""
        result = await send_email(
            to=[],
            subject="Test",
            body="Body",
        )

        assert result["status"] == "error"
        assert "recipient" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_send_email_requires_subject(self):
        """Test that send_email requires a subject."""
        result = await send_email(
            to=["test@example.com"],
            subject="",
            body="Body",
        )

        assert result["status"] == "error"
        assert "Subject is required" in result["message"]

    @pytest.mark.asyncio
    async def test_send_email_blocked_by_allowlist(self):
        """Test that send_email blocks recipients not in allowlist."""
        with patch("agent_framework.tools.fastmail.send.settings") as mock_settings:
            mock_settings.admin_email_address = "admin@example.com"
            mock_settings.allowed_email_recipients = None  # Only admin allowed

            result = await send_email(
                to=["unauthorized@example.com"],
                subject="Test",
                body="Body",
            )

            assert result["status"] == "error"
            assert "not in allowed list" in result["message"]

    @pytest.mark.asyncio
    async def test_send_email_identity_not_found(self):
        """Test error when requested identity doesn't exist."""
        mock_identity_response = {
            "methodResponses": [
                [
                    "Identity/get",
                    {"list": [{"id": "id1", "email": "other@example.com"}]},
                    "identity-get",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.send.settings") as mock_settings:
            mock_settings.admin_email_address = "admin@example.com"
            mock_settings.allowed_email_recipients = "*@example.com"  # Allow all example.com

            with patch("agent_framework.tools.fastmail.send._get_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client._ensure_session = AsyncMock()
                mock_client.account_id = "account-123"
                mock_client._call = AsyncMock(return_value=mock_identity_response)
                mock_get_client.return_value = mock_client

                result = await send_email(
                    to=["recipient@example.com"],
                    subject="Test",
                    body="Body",
                    identity_email="notfound@example.com",
                )

                assert result["status"] == "error"
                assert "not found" in result["message"].lower()


class TestSendAgentReport:
    """Tests for send_agent_report function."""

    @pytest.mark.asyncio
    async def test_send_agent_report_requires_admin_email(self):
        """Test that send_agent_report requires ADMIN_EMAIL_ADDRESS."""
        with patch("agent_framework.tools.fastmail.send.settings") as mock_settings:
            mock_settings.admin_email_address = None

            result = await send_agent_report(
                subject="Test Report",
                body="Report body",
                agent_name="test-agent",
            )

            assert result["status"] == "error"
            assert "ADMIN_EMAIL_ADDRESS" in result["message"]

    @pytest.mark.asyncio
    async def test_send_agent_report_requires_agent_name(self):
        """Test that send_agent_report requires agent_name."""
        with patch("agent_framework.tools.fastmail.send.settings") as mock_settings:
            mock_settings.admin_email_address = "admin@example.com"

            result = await send_agent_report(
                subject="Test Report",
                body="Report body",
                agent_name=None,
            )

            assert result["status"] == "error"
            assert "agent_name is required" in result["message"]

    @pytest.mark.asyncio
    async def test_send_agent_report_derives_from_email(self):
        """Test that from_email is correctly derived from agent name."""
        with patch("agent_framework.tools.fastmail.send.settings") as mock_settings:
            mock_settings.admin_email_address = "admin@example.com"
            mock_settings.agent_email_domain = "agents.example.com"
            mock_settings.fastmail_api_token = "token"
            mock_settings.allowed_email_recipients = None  # Admin always allowed

            with patch(
                "agent_framework.tools.fastmail.send.send_email",
                new_callable=AsyncMock,
            ) as mock_send:
                mock_send.return_value = {"status": "success", "email_id": "123"}

                await send_agent_report(
                    subject="Test Report",
                    body="Report body",
                    agent_name="Test_Agent",
                )

                # Check send_email was called with correct identity
                mock_send.assert_called_once()
                call_kwargs = mock_send.call_args[1]
                assert call_kwargs["identity_email"] == "test-agent@agents.example.com"
                assert call_kwargs["to"] == ["admin@example.com"]


class TestErrorHandling:
    """Tests for error handling across FastMail functions."""

    @pytest.mark.asyncio
    async def test_get_email_not_found(self):
        """Test handling of non-existent email."""
        mock_response = {
            "methodResponses": [
                [
                    "Email/get",
                    {"list": [], "notFound": ["nonexistent-id"]},
                    "email-get",
                ]
            ]
        }

        with patch("agent_framework.tools.fastmail.read._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock()
            mock_client.account_id = "account-123"
            mock_client._call = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await get_email("nonexistent-id")

            assert result["status"] == "not_found"
            assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_network_error_handling(self):
        """Test handling of network errors."""
        with patch("agent_framework.tools.fastmail.mailbox._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )
            mock_get_client.return_value = mock_client

            result = await list_mailboxes()

            assert result["status"] == "error"
            # Error messages are now masked for security - check error type instead
            assert result["error_type"] == "RequestError"
            assert "request failed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_403_forbidden_handling(self):
        """Test handling of 403 Forbidden errors."""
        with patch("agent_framework.tools.fastmail.mailbox._get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client._ensure_session = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Forbidden",
                    request=MagicMock(),
                    response=MagicMock(status_code=403),
                )
            )
            mock_get_client.return_value = mock_client

            result = await list_mailboxes()

            assert result["status"] == "error"
            assert result["error_type"] == "ForbiddenError"
            assert result["status_code"] == 403
