"""Tests for PII (Personally Identifiable Information) masking utilities."""

from agent_framework.security.pii import mask_phone_in_text, mask_phone_number


class TestMaskPhoneNumber:
    """Tests for mask_phone_number()."""

    def test_empty_string(self) -> None:
        assert mask_phone_number("") == "[no phone]"

    def test_none_like_empty(self) -> None:
        # Empty string is falsy
        assert mask_phone_number("") == "[no phone]"

    def test_e164_full(self) -> None:
        """Standard E.164 format: +15551234567."""
        result = mask_phone_number("+15551234567")
        assert result == "+1555***4567"

    def test_domestic_10_digit(self) -> None:
        """10-digit domestic number without country code."""
        result = mask_phone_number("5551234567")
        assert result == "5551***4567"

    def test_7_digit_number(self) -> None:
        """7-digit local number (just above threshold)."""
        result = mask_phone_number("1234567")
        assert result == "1234***4567"

    def test_short_number_6_digits(self) -> None:
        """6-digit number at the boundary: uses short masking."""
        result = mask_phone_number("123456")
        assert result == "***56"

    def test_short_number_3_digits(self) -> None:
        """3-digit number: short masking preserves last 2."""
        result = mask_phone_number("911")
        assert result == "***11"

    def test_short_number_2_digits(self) -> None:
        result = mask_phone_number("42")
        assert result == "***42"

    def test_single_digit(self) -> None:
        """Single digit: len < 2, returns '***'."""
        result = mask_phone_number("5")
        assert result == "***"

    def test_plus_prefix_preserved(self) -> None:
        result = mask_phone_number("+15551234567")
        assert result.startswith("+")

    def test_no_plus_prefix(self) -> None:
        result = mask_phone_number("5551234567")
        assert not result.startswith("+")

    def test_formatted_number_with_dashes(self) -> None:
        """Dashes and formatting are stripped before masking."""
        result = mask_phone_number("555-123-4567")
        assert result == "5551***4567"

    def test_formatted_number_with_parens(self) -> None:
        result = mask_phone_number("(555) 123-4567")
        assert result == "5551***4567"

    def test_formatted_number_with_spaces(self) -> None:
        result = mask_phone_number("555 123 4567")
        assert result == "5551***4567"

    def test_international_number(self) -> None:
        """International E.164 with longer prefix."""
        result = mask_phone_number("+442071234567")
        assert result.startswith("+")
        assert "***" in result
        assert result.endswith("4567")

    def test_short_with_plus(self) -> None:
        """Short number with + prefix: preserves + in output."""
        result = mask_phone_number("+12345")
        assert result == "+***45"

    def test_middle_is_hidden(self) -> None:
        """Verify the middle portion is masked with ***."""
        result = mask_phone_number("+15559876543")
        # prefix=1555, suffix=6543
        assert result == "+1555***6543"


class TestMaskPhoneInText:
    """Tests for mask_phone_in_text()."""

    def test_e164_in_text(self) -> None:
        text = "Call me at +15551234567 today"
        result = mask_phone_in_text(text)
        assert "+15551234567" not in result
        assert "+1555***4567" in result
        assert "Call me at" in result
        assert "today" in result

    def test_us_format_with_dashes(self) -> None:
        text = "Phone: 555-123-4567"
        result = mask_phone_in_text(text)
        assert "555-123-4567" not in result
        assert "***" in result

    def test_us_format_with_parens(self) -> None:
        text = "Phone: (555) 123-4567"
        result = mask_phone_in_text(text)
        assert "(555) 123-4567" not in result
        assert "***" in result

    def test_us_format_with_dots(self) -> None:
        text = "Phone: 555.123.4567"
        result = mask_phone_in_text(text)
        assert "555.123.4567" not in result
        assert "***" in result

    def test_multiple_numbers(self) -> None:
        text = "Call +15551234567 or +15559876543"
        result = mask_phone_in_text(text)
        assert "+15551234567" not in result
        assert "+15559876543" not in result
        assert result.count("***") == 2

    def test_no_phone_numbers(self) -> None:
        text = "No phone numbers here, just regular text."
        result = mask_phone_in_text(text)
        assert result == text

    def test_mixed_formats(self) -> None:
        text = "Home: +15551234567, Work: 555-987-6543"
        result = mask_phone_in_text(text)
        assert "+15551234567" not in result
        assert "555-987-6543" not in result

    def test_preserves_surrounding_text(self) -> None:
        text = "prefix +15551234567 suffix"
        result = mask_phone_in_text(text)
        assert result.startswith("prefix ")
        assert result.endswith(" suffix")

    def test_empty_text(self) -> None:
        assert mask_phone_in_text("") == ""

    def test_ten_digit_no_separator(self) -> None:
        """10 consecutive digits match US pattern."""
        text = "Number: 5551234567"
        result = mask_phone_in_text(text)
        assert "5551234567" not in result
        assert "***" in result
