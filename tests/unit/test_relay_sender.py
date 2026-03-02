"""Unit tests for MCP relay sender validation.

Covers RESERVED_RELAY_SENDER_NAMES and validate_relay_sender() in shared/constants.py.
"""

import pytest

from shared.constants import RESERVED_RELAY_SENDER_NAMES, validate_relay_sender


class TestReservedRelaySenderNames:
    """Tests for the RESERVED_RELAY_SENDER_NAMES constant."""

    def test_is_frozenset(self) -> None:
        assert isinstance(RESERVED_RELAY_SENDER_NAMES, frozenset)

    def test_contains_system(self) -> None:
        assert "system" in RESERVED_RELAY_SENDER_NAMES

    def test_contains_admin(self) -> None:
        assert "admin" in RESERVED_RELAY_SENDER_NAMES

    def test_contains_root(self) -> None:
        assert "root" in RESERVED_RELAY_SENDER_NAMES

    def test_contains_relay(self) -> None:
        assert "relay" in RESERVED_RELAY_SENDER_NAMES

    def test_stores_lowercase_only(self) -> None:
        """All entries should be lowercase canonical forms."""
        for name in RESERVED_RELAY_SENDER_NAMES:
            assert name == name.lower(), f"Expected lowercase, got: {name!r}"


class TestValidateRelaySender:
    """Tests for validate_relay_sender()."""

    # -- Safe senders -----------------------------------------------------------

    def test_agent_class_name_passes(self) -> None:
        assert validate_relay_sender("ChatbotAgent") == "ChatbotAgent"

    def test_arbitrary_safe_name_passes(self) -> None:
        assert validate_relay_sender("pr-agent") == "pr-agent"

    def test_numeric_name_passes(self) -> None:
        assert validate_relay_sender("Agent42") == "Agent42"

    def test_returns_original_casing(self) -> None:
        """The function must not alter the input string on success."""
        result = validate_relay_sender("MyCustomAgent")
        assert result == "MyCustomAgent"

    # -- Reserved names — exact match -------------------------------------------

    def test_system_lowercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("system")

    def test_admin_lowercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("admin")

    def test_root_lowercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("root")

    def test_relay_lowercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("relay")

    # -- Reserved names — case-insensitive matching -----------------------------

    def test_system_uppercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("SYSTEM")

    def test_system_titlecase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("System")

    def test_system_mixed_case_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("sYsTeM")

    def test_admin_uppercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("ADMIN")

    def test_root_uppercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("ROOT")

    def test_relay_uppercase_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("RELAY")

    # -- Whitespace handling ----------------------------------------------------

    def test_system_with_leading_space_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender(" system")

    def test_system_with_trailing_space_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("system ")

    def test_system_with_surrounding_spaces_raises(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            validate_relay_sender("  system  ")

    # -- Empty / whitespace-only ------------------------------------------------

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_relay_sender("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_relay_sender("   ")

    def test_tab_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_relay_sender("\t")

    # -- Error message content --------------------------------------------------

    def test_error_mentions_sender_value(self) -> None:
        with pytest.raises(ValueError, match="sYsTeM"):
            validate_relay_sender("sYsTeM")

    def test_error_mentions_advisory_note(self) -> None:
        with pytest.raises(ValueError, match="advisory-only"):
            validate_relay_sender("system")
