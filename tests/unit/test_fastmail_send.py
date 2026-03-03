"""Unit tests for agent_framework/tools/fastmail/send.py.

Covers the recipient allowlist gate functions:
- _check_recipients_allowed: allowed/blocked/mixed recipient lists
- _collect_all_recipients: aggregation of to/cc/bcc fields
Edge cases: empty lists, None cc/bcc, all-blocked, single recipient, etc.
"""

from __future__ import annotations

from agent_framework.tools.fastmail.send import (
    _check_recipients_allowed,
    _collect_all_recipients,
)

# ---------------------------------------------------------------------------
# _collect_all_recipients
# ---------------------------------------------------------------------------


class TestCollectAllRecipients:
    """Tests for _collect_all_recipients – aggregating to/cc/bcc into one list."""

    def test_to_only_no_cc_no_bcc(self) -> None:
        """Only to recipients, no cc or bcc."""
        result = _collect_all_recipients(["alice@example.com"], None, None)
        assert result == ["alice@example.com"]

    def test_to_and_cc_no_bcc(self) -> None:
        """to and cc recipients are combined; bcc is None."""
        result = _collect_all_recipients(
            ["alice@example.com"],
            ["bob@example.com"],
            None,
        )
        assert result == ["alice@example.com", "bob@example.com"]

    def test_to_and_bcc_no_cc(self) -> None:
        """to and bcc recipients are combined; cc is None."""
        result = _collect_all_recipients(
            ["alice@example.com"],
            None,
            ["carol@example.com"],
        )
        assert result == ["alice@example.com", "carol@example.com"]

    def test_to_cc_and_bcc_all_present(self) -> None:
        """All three fields present – all addresses appear in order."""
        result = _collect_all_recipients(
            ["alice@example.com"],
            ["bob@example.com"],
            ["carol@example.com"],
        )
        assert result == [
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
        ]

    def test_multiple_addresses_in_each_field(self) -> None:
        """Multiple addresses per field are all included."""
        result = _collect_all_recipients(
            ["a@x.com", "b@x.com"],
            ["c@x.com", "d@x.com"],
            ["e@x.com"],
        )
        assert result == ["a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com"]

    def test_empty_cc_list_not_included(self) -> None:
        """An empty cc list (not None but []) does not extend the result."""
        result = _collect_all_recipients(["alice@example.com"], [], None)
        # Empty list is falsy so the extend branch is skipped
        assert result == ["alice@example.com"]

    def test_empty_bcc_list_not_included(self) -> None:
        """An empty bcc list (not None but []) does not extend the result."""
        result = _collect_all_recipients(["alice@example.com"], None, [])
        assert result == ["alice@example.com"]

    def test_order_preserved_to_then_cc_then_bcc(self) -> None:
        """Recipient order is to -> cc -> bcc."""
        result = _collect_all_recipients(["to@x.com"], ["cc@x.com"], ["bcc@x.com"])
        assert result.index("to@x.com") < result.index("cc@x.com")
        assert result.index("cc@x.com") < result.index("bcc@x.com")

    def test_does_not_mutate_to_list(self) -> None:
        """The original to list must not be mutated."""
        original_to = ["alice@example.com"]
        _collect_all_recipients(original_to, ["bob@example.com"], None)
        assert original_to == ["alice@example.com"]

    def test_duplicate_addresses_preserved(self) -> None:
        """Duplicate addresses across fields are not deduplicated."""
        result = _collect_all_recipients(
            ["dup@example.com"],
            ["dup@example.com"],
            None,
        )
        assert result.count("dup@example.com") == 2

    def test_empty_to_list(self) -> None:
        """Empty to list with cc produces only cc addresses."""
        result = _collect_all_recipients([], ["cc@example.com"], None)
        assert result == ["cc@example.com"]

    def test_all_none_optional_fields(self) -> None:
        """Both cc and bcc are None – only to is returned."""
        result = _collect_all_recipients(["only@example.com"], None, None)
        assert result == ["only@example.com"]


# ---------------------------------------------------------------------------
# _check_recipients_allowed
# ---------------------------------------------------------------------------


class TestCheckRecipientsAllowed:
    """Tests for _check_recipients_allowed – allowlist enforcement."""

    # --- All allowed ---

    def test_single_allowed_exact_match(self) -> None:
        """Single recipient that exactly matches an allowed pattern."""
        ok, disallowed = _check_recipients_allowed(
            ["admin@example.com"],
            ["admin@example.com"],
        )
        assert ok is True
        assert disallowed == []

    def test_multiple_allowed_exact_matches(self) -> None:
        """Multiple recipients all present in the allowed list."""
        ok, disallowed = _check_recipients_allowed(
            ["a@example.com", "b@example.com"],
            ["a@example.com", "b@example.com", "c@example.com"],
        )
        assert ok is True
        assert disallowed == []

    def test_allowed_via_wildcard_domain(self) -> None:
        """Recipient allowed because their domain matches a *@domain.com pattern."""
        ok, disallowed = _check_recipients_allowed(
            ["anyone@trusted.com"],
            ["*@trusted.com"],
        )
        assert ok is True
        assert disallowed == []

    def test_multiple_recipients_allowed_via_wildcard(self) -> None:
        """Multiple recipients from the same wildcard domain are all allowed."""
        ok, disallowed = _check_recipients_allowed(
            ["alice@trusted.com", "bob@trusted.com"],
            ["*@trusted.com"],
        )
        assert ok is True
        assert disallowed == []

    def test_allowed_exact_match_case_insensitive(self) -> None:
        """Allowlist check is case-insensitive for exact matches."""
        ok, disallowed = _check_recipients_allowed(
            ["Admin@Example.COM"],
            ["admin@example.com"],
        )
        assert ok is True
        assert disallowed == []

    def test_allowed_wildcard_match_case_insensitive(self) -> None:
        """Wildcard domain match is case-insensitive."""
        ok, disallowed = _check_recipients_allowed(
            ["USER@TRUSTED.COM"],
            ["*@trusted.com"],
        )
        assert ok is True
        assert disallowed == []

    # --- All blocked ---

    def test_single_blocked_recipient(self) -> None:
        """Single recipient not in allowed list is returned as disallowed."""
        ok, disallowed = _check_recipients_allowed(
            ["stranger@evil.com"],
            ["admin@example.com"],
        )
        assert ok is False
        assert disallowed == ["stranger@evil.com"]

    def test_all_recipients_blocked(self) -> None:
        """All recipients are outside the allowed list."""
        ok, disallowed = _check_recipients_allowed(
            ["a@evil.com", "b@evil.com"],
            ["admin@example.com"],
        )
        assert ok is False
        assert set(disallowed) == {"a@evil.com", "b@evil.com"}

    def test_wrong_domain_blocked_by_wildcard(self) -> None:
        """Recipient from a domain not matching the wildcard pattern is blocked."""
        ok, disallowed = _check_recipients_allowed(
            ["user@untrusted.com"],
            ["*@trusted.com"],
        )
        assert ok is False
        assert disallowed == ["user@untrusted.com"]

    # --- Mixed allowed / blocked ---

    def test_mixed_some_allowed_some_blocked(self) -> None:
        """Only the blocked recipients are returned; allowed ones are omitted."""
        ok, disallowed = _check_recipients_allowed(
            ["admin@example.com", "stranger@evil.com"],
            ["admin@example.com"],
        )
        assert ok is False
        assert disallowed == ["stranger@evil.com"]
        assert "admin@example.com" not in disallowed

    def test_mixed_wildcard_and_exact_one_blocked(self) -> None:
        """Wildcard allows some, exact allows another, but one slips through."""
        ok, disallowed = _check_recipients_allowed(
            ["alice@trusted.com", "admin@example.com", "outsider@bad.com"],
            ["*@trusted.com", "admin@example.com"],
        )
        assert ok is False
        assert disallowed == ["outsider@bad.com"]

    # --- Empty recipient lists ---

    def test_empty_recipients_is_vacuously_allowed(self) -> None:
        """No recipients means no one is blocked – returns True with empty disallowed."""
        ok, disallowed = _check_recipients_allowed([], ["admin@example.com"])
        assert ok is True
        assert disallowed == []

    def test_empty_recipients_empty_patterns(self) -> None:
        """Both lists empty – vacuously true."""
        ok, disallowed = _check_recipients_allowed([], [])
        assert ok is True
        assert disallowed == []

    # --- Empty allowed patterns (nothing is permitted) ---

    def test_non_empty_recipients_empty_allowed_patterns(self) -> None:
        """No allowed patterns means every recipient is blocked."""
        ok, disallowed = _check_recipients_allowed(
            ["anyone@example.com"],
            [],
        )
        assert ok is False
        assert disallowed == ["anyone@example.com"]

    def test_multiple_recipients_empty_allowed_patterns(self) -> None:
        """All recipients blocked when allowed_patterns is empty."""
        ok, disallowed = _check_recipients_allowed(
            ["a@x.com", "b@x.com"],
            [],
        )
        assert ok is False
        assert set(disallowed) == {"a@x.com", "b@x.com"}

    # --- Return type / structure ---

    def test_returns_tuple_of_bool_and_list(self) -> None:
        """Return value is always a 2-tuple of (bool, list)."""
        result = _check_recipients_allowed(["x@y.com"], ["x@y.com"])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)

    def test_disallowed_list_preserves_original_email_case(self) -> None:
        """The disallowed list contains addresses with their original casing."""
        original = "Stranger@EVIL.COM"
        ok, disallowed = _check_recipients_allowed([original], ["admin@example.com"])
        assert ok is False
        assert disallowed == [original]
