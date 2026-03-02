"""Unit tests for agent_framework/tools/twilio_utils.py.

Covers _redact_sensitive_text() credential/token/phone redaction and
validate_twilio_credentials() failure paths for missing and malformed
TWILIO_ACCOUNT_SID values.
"""

from unittest.mock import patch

import pytest
from agent_framework.tools.twilio_utils import (
    TwilioCredentials,
    _redact_sensitive_text,
    validate_account_sid,
    validate_message_sid,
    validate_phone_number,
    validate_twilio_credentials,
)

# ---------------------------------------------------------------------------
# _redact_sensitive_text
# ---------------------------------------------------------------------------


class TestRedactSensitiveText:
    """Tests for _redact_sensitive_text – credential and PII scrubbing."""

    # --- 32-hex token redaction ---

    def test_redacts_32_hex_lowercase(self) -> None:
        """A 32-character lowercase hex string should be replaced."""
        token = "a" * 32
        result = _redact_sensitive_text(f"token={token}")
        assert token not in result
        assert "[REDACTED]" in result

    def test_redacts_32_hex_uppercase(self) -> None:
        """A 32-character uppercase hex string should be replaced (case-insensitive)."""
        token = "A" * 32
        result = _redact_sensitive_text(f"sid={token}")
        assert token not in result
        assert "[REDACTED]" in result

    def test_redacts_32_hex_mixed_case(self) -> None:
        """A 32-character mixed-case hex string should be replaced."""
        token = "aAbBcCdDeEfF" * 2 + "00001111"  # 32 chars
        result = _redact_sensitive_text(token)
        assert token not in result
        assert "[REDACTED]" in result

    def test_redacts_twilio_auth_token_in_error_message(self) -> None:
        """Auth token embedded in a realistic error message should be scrubbed."""
        auth_token = "b3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6"  # 32 hex chars
        msg = f"Authentication failed for token {auth_token}: 401 Unauthorized"
        result = _redact_sensitive_text(msg)
        assert auth_token not in result
        assert "[REDACTED]" in result
        assert "Authentication failed" in result

    def test_redacts_multiple_hex_tokens(self) -> None:
        """Multiple 32-hex tokens in the same string should all be replaced."""
        token1 = "a" * 32
        token2 = "b" * 32
        msg = f"sid={token1} token={token2}"
        result = _redact_sensitive_text(msg)
        assert token1 not in result
        assert token2 not in result
        assert result.count("[REDACTED]") == 2

    def test_does_not_redact_short_hex_strings(self) -> None:
        """Hex strings shorter than 32 characters should not be redacted."""
        short_hex = "deadbeef"  # 8 chars
        result = _redact_sensitive_text(f"value={short_hex}")
        assert short_hex in result
        assert "[REDACTED]" not in result

    # --- Bearer header redaction ---

    def test_redacts_bearer_token(self) -> None:
        """Bearer token in Authorization header should be replaced."""
        msg = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result = _redact_sensitive_text(msg)
        assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "Bearer [REDACTED]" in result

    def test_redacts_bearer_token_case_insensitive(self) -> None:
        """BEARER (uppercase) should also be redacted."""
        msg = "BEARER some_secret_token_here"
        result = _redact_sensitive_text(msg)
        assert "some_secret_token_here" not in result
        assert "[REDACTED]" in result

    def test_bearer_prefix_preserved(self) -> None:
        """The word 'Bearer' should still appear (only the token value is hidden)."""
        msg = "Authorization: Bearer mysecrettoken123"
        result = _redact_sensitive_text(msg)
        assert "Bearer [REDACTED]" in result

    # --- Basic header redaction ---

    def test_redacts_basic_auth_header(self) -> None:
        """Basic auth credentials in header value should be replaced."""
        # base64 of "ACxxx:authtoken"
        credentials = "QUNmYWtlc2lkOmZha2VhdXRodG9rZW4="
        msg = f"Authorization: Basic {credentials}"
        result = _redact_sensitive_text(msg)
        assert credentials not in result
        assert "Basic [REDACTED]" in result

    def test_redacts_basic_auth_case_insensitive(self) -> None:
        """BASIC (uppercase) should also be redacted."""
        msg = "BASIC dXNlcjpwYXNz"
        result = _redact_sensitive_text(msg)
        assert "dXNlcjpwYXNz" not in result
        assert "[REDACTED]" in result

    # --- Phone number redaction ---

    def test_redacts_e164_phone_number(self) -> None:
        """E.164 phone number should be replaced."""
        msg = "Sending SMS to +15551234567 from agent"
        result = _redact_sensitive_text(msg)
        assert "+15551234567" not in result
        assert "[PHONE REDACTED]" in result

    def test_redacts_phone_number_with_dashes(self) -> None:
        """Phone number with dashes should be replaced."""
        msg = "Contact: 555-123-4567 for support"
        result = _redact_sensitive_text(msg)
        assert "555-123-4567" not in result
        assert "[PHONE REDACTED]" in result

    def test_redacts_phone_number_with_spaces(self) -> None:
        """Phone number with spaces should be replaced."""
        msg = "Call 555 123 4567 now"
        result = _redact_sensitive_text(msg)
        assert "555 123 4567" not in result
        assert "[PHONE REDACTED]" in result

    def test_phone_redaction_does_not_affect_short_numbers(self) -> None:
        """Short numeric strings (less than ~9 digits total) should not be replaced."""
        msg = "Error code: 12345"
        result = _redact_sensitive_text(msg)
        # The pattern requires 8+ separator chars, so 5-digit codes are safe
        assert "12345" in result

    # --- Text without sensitive data ---

    def test_plain_text_unchanged(self) -> None:
        """Text with no tokens, headers, or phone numbers should be returned as-is."""
        msg = "Connection timed out after 30 seconds"
        result = _redact_sensitive_text(msg)
        assert result == msg

    def test_empty_string(self) -> None:
        """Empty string should return empty string."""
        assert _redact_sensitive_text("") == ""

    def test_combined_redaction(self) -> None:
        """A message containing both a token and a Bearer header should redact both."""
        auth_token = "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6"
        msg = f"Error: Bearer secret_jwt AND raw token {auth_token} were rejected"
        result = _redact_sensitive_text(msg)
        assert "secret_jwt" not in result
        assert auth_token not in result
        assert "[REDACTED]" in result
        assert "Bearer [REDACTED]" in result


# ---------------------------------------------------------------------------
# validate_twilio_credentials
# ---------------------------------------------------------------------------


class TestValidateTwilioCredentials:
    """Tests for validate_twilio_credentials failure paths."""

    def test_returns_error_when_account_sid_is_none(self) -> None:
        """Missing TWILIO_ACCOUNT_SID should return a string error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = None
            mock_settings.twilio_auth_token = "sometoken"

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_ACCOUNT_SID" in result

    def test_returns_error_when_account_sid_is_empty_string(self) -> None:
        """Empty string TWILIO_ACCOUNT_SID should return a string error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = ""
            mock_settings.twilio_auth_token = "sometoken"

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_ACCOUNT_SID" in result

    def test_returns_error_when_account_sid_format_invalid_missing_ac_prefix(
        self,
    ) -> None:
        """SID without 'AC' prefix should return format error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            # 34 chars but starts with 'XX' instead of 'AC'
            mock_settings.twilio_account_sid = "XX" + "a" * 32
            mock_settings.twilio_auth_token = "sometoken"

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_ACCOUNT_SID" in result
        assert "format" in result.lower()

    def test_returns_error_when_account_sid_too_short(self) -> None:
        """SID that is too short should return format error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = "ACshort"
            mock_settings.twilio_auth_token = "sometoken"

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_ACCOUNT_SID" in result

    def test_returns_error_when_account_sid_too_long(self) -> None:
        """SID with more than 32 hex chars after 'AC' should return format error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = "AC" + "a" * 33  # one too many
            mock_settings.twilio_auth_token = "sometoken"

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_ACCOUNT_SID" in result

    def test_returns_error_when_account_sid_has_non_hex_chars(self) -> None:
        """SID with non-hex characters after 'AC' should return format error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            # 'z' is not a valid hex digit
            mock_settings.twilio_account_sid = "AC" + "z" * 32
            mock_settings.twilio_auth_token = "sometoken"

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_ACCOUNT_SID" in result

    def test_returns_error_when_auth_token_missing(self) -> None:
        """Valid SID but missing auth token should return a string error."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = "AC" + "a" * 32
            mock_settings.twilio_auth_token = None

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        assert "TWILIO_AUTH_TOKEN" in result

    def test_returns_credentials_when_valid(self) -> None:
        """Valid SID and token should return a TwilioCredentials instance."""
        valid_sid = "AC" + "a" * 32
        valid_token = "myauthtoken"

        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = valid_sid
            mock_settings.twilio_auth_token = valid_token

            result = validate_twilio_credentials()

        assert isinstance(result, TwilioCredentials)
        assert result.account_sid == valid_sid
        assert result.auth_token == valid_token

    def test_returns_credentials_with_uppercase_hex_sid(self) -> None:
        """SID with uppercase hex digits should be accepted (pattern is case-insensitive)."""
        valid_sid = "AC" + "A" * 32
        valid_token = "myauthtoken"

        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = valid_sid
            mock_settings.twilio_auth_token = valid_token

            result = validate_twilio_credentials()

        assert isinstance(result, TwilioCredentials)

    def test_error_message_mentions_setup_instructions_for_missing_sid(self) -> None:
        """Missing SID error should include setup instructions."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = None
            mock_settings.twilio_auth_token = None

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        # Verify the error includes a URL pointing to the Twilio console
        assert "https://" in result
        assert "twilio" in result.lower()

    def test_error_message_mentions_setup_instructions_for_missing_auth_token(
        self,
    ) -> None:
        """Missing auth token error should include setup instructions."""
        with patch("agent_framework.tools.twilio_utils.settings") as mock_settings:
            mock_settings.twilio_account_sid = "AC" + "f" * 32
            mock_settings.twilio_auth_token = ""

            result = validate_twilio_credentials()

        assert isinstance(result, str)
        # Verify the error includes a URL pointing to the Twilio console
        assert "https://" in result
        assert "twilio" in result.lower()


# ---------------------------------------------------------------------------
# validate_account_sid (helper used by validate_twilio_credentials)
# ---------------------------------------------------------------------------


class TestValidateAccountSid:
    """Tests for the validate_account_sid helper."""

    def test_valid_lowercase_sid(self) -> None:
        """Lowercase hex SID should be valid."""
        assert validate_account_sid("AC" + "a" * 32) is True

    def test_valid_uppercase_sid(self) -> None:
        """Uppercase hex SID should be valid (case-insensitive)."""
        assert validate_account_sid("AC" + "F" * 32) is True

    def test_valid_mixed_case_sid(self) -> None:
        """Mixed-case hex SID should be valid."""
        assert validate_account_sid("AC" + "aAbBcCdDeEfF" * 2 + "00001111") is True

    def test_invalid_prefix(self) -> None:
        """SID with wrong prefix should be invalid."""
        assert validate_account_sid("XX" + "a" * 32) is False

    def test_invalid_too_short(self) -> None:
        """SID that is too short should be invalid."""
        assert validate_account_sid("AC" + "a" * 10) is False

    def test_invalid_too_long(self) -> None:
        """SID that is too long should be invalid."""
        assert validate_account_sid("AC" + "a" * 33) is False

    def test_invalid_non_hex_chars(self) -> None:
        """SID with non-hex characters should be invalid."""
        assert validate_account_sid("AC" + "g" * 32) is False

    def test_empty_string(self) -> None:
        """Empty string should be invalid."""
        assert validate_account_sid("") is False


# ---------------------------------------------------------------------------
# validate_message_sid (helper)
# ---------------------------------------------------------------------------


class TestValidateMessageSid:
    """Tests for the validate_message_sid helper."""

    def test_valid_sm_prefix(self) -> None:
        """SM-prefixed message SID should be valid."""
        assert validate_message_sid("SM" + "a" * 32) is True

    def test_valid_mm_prefix(self) -> None:
        """MM-prefixed message SID should be valid."""
        assert validate_message_sid("MM" + "b" * 32) is True

    def test_invalid_prefix(self) -> None:
        """Wrong prefix should be invalid."""
        assert validate_message_sid("AC" + "a" * 32) is False

    def test_invalid_too_short(self) -> None:
        """Short SID should be invalid."""
        assert validate_message_sid("SM" + "a" * 5) is False


# ---------------------------------------------------------------------------
# validate_phone_number (helper)
# ---------------------------------------------------------------------------


class TestValidatePhoneNumber:
    """Tests for the validate_phone_number helper."""

    def test_valid_e164_number(self) -> None:
        """E.164 formatted number should be returned as-is."""
        assert validate_phone_number("+15551234567", "to") == "+15551234567"

    def test_10_digit_us_number_normalized(self) -> None:
        """10-digit US number should be normalized to E.164."""
        assert validate_phone_number("5551234567", "to") == "+15551234567"

    def test_11_digit_us_number_normalized(self) -> None:
        """11-digit US number starting with 1 should be normalized."""
        assert validate_phone_number("15551234567", "to") == "+15551234567"

    def test_number_with_dashes_normalized(self) -> None:
        """Number with dashes should be normalized."""
        assert validate_phone_number("555-123-4567", "to") == "+15551234567"

    def test_invalid_number_raises_value_error(self) -> None:
        """Non-numeric garbage should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid to"):
            validate_phone_number("not-a-phone", "to")

    def test_too_short_number_raises_value_error(self) -> None:
        """A number that is too short for E.164 should raise ValueError."""
        with pytest.raises(ValueError):
            validate_phone_number("+1", "to")
