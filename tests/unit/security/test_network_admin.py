"""Tests for network_admin security: subnet allowlist and dig target validation."""

import os
from unittest.mock import patch

import pytest
from agent_framework.tools.network_admin import (
    _check_subnet_allowed,
    _validate_dig_target,
)

# ---------------------------------------------------------------------------
# Tests for _check_subnet_allowed
# ---------------------------------------------------------------------------


class TestCheckSubnetAllowed:
    """Tests for the fail-secure subnet allowlist gate."""

    def test_blocks_all_when_env_not_set(self) -> None:
        """Without SYSADMIN_ALLOWED_SUBNETS, every target is denied."""
        with patch.dict(os.environ, {}, clear=True):
            # Make sure the key is absent
            os.environ.pop("SYSADMIN_ALLOWED_SUBNETS", None)
            with pytest.raises(ValueError, match="SYSADMIN_ALLOWED_SUBNETS is not set"):
                _check_subnet_allowed("192.168.1.1")

    def test_blocks_all_when_env_empty_string(self) -> None:
        """An empty SYSADMIN_ALLOWED_SUBNETS string is treated as not set."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": ""}):
            with pytest.raises(ValueError, match="SYSADMIN_ALLOWED_SUBNETS is not set"):
                _check_subnet_allowed("10.0.0.1")

    def test_allows_ip_within_allowed_subnet(self) -> None:
        """IP inside the configured subnet is allowed."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24"}):
            # Should not raise
            _check_subnet_allowed("192.168.1.100")

    def test_blocks_ip_outside_allowed_subnet(self) -> None:
        """IP outside the configured subnet is denied."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24"}):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                _check_subnet_allowed("10.0.0.1")

    def test_allows_exact_subnet_boundary_start(self) -> None:
        """Network address itself is inside the allowed subnet."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "10.0.0.0/8"}):
            _check_subnet_allowed("10.0.0.0")

    def test_allows_exact_subnet_boundary_end(self) -> None:
        """Broadcast address is inside the allowed subnet."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "10.0.0.0/8"}):
            _check_subnet_allowed("10.255.255.255")

    def test_allows_multiple_subnets_matches_second(self) -> None:
        """Target matching the second entry in a comma-separated list is allowed."""
        with patch.dict(
            os.environ,
            {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24,10.10.0.0/16"},
        ):
            _check_subnet_allowed("10.10.5.1")

    def test_allows_multiple_subnets_matches_first(self) -> None:
        """Target matching the first entry in a comma-separated list is allowed."""
        with patch.dict(
            os.environ,
            {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24,10.10.0.0/16"},
        ):
            _check_subnet_allowed("192.168.1.200")

    def test_blocks_ip_not_in_any_subnet(self) -> None:
        """Target not in any allowed subnet is denied even with multiple entries."""
        with patch.dict(
            os.environ,
            {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24,10.10.0.0/16"},
        ):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                _check_subnet_allowed("172.16.0.1")

    def test_allows_subnet_within_allowed_subnet(self) -> None:
        """A /28 target subnet fits inside an allowed /24."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24"}):
            _check_subnet_allowed("192.168.1.16/28")

    def test_blocks_subnet_larger_than_allowed(self) -> None:
        """A /16 target subnet does not fit inside an allowed /24."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24"}):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                _check_subnet_allowed("192.168.0.0/16")

    def test_raises_on_invalid_target(self) -> None:
        """A non-IP, non-CIDR target raises ValueError."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "192.168.1.0/24"}):
            with pytest.raises(ValueError, match="Invalid target or subnet"):
                _check_subnet_allowed("not-an-ip")

    def test_ignores_ipv6_allowed_subnet_for_ipv4_target(self) -> None:
        """IPv6 allowed subnet does not cover an IPv4 target (family mismatch)."""
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "::1/128"}):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                _check_subnet_allowed("127.0.0.1")

    def test_whitespace_around_subnet_entries_is_stripped(self) -> None:
        """Extra whitespace around comma-separated entries is handled gracefully."""
        with patch.dict(
            os.environ,
            {"SYSADMIN_ALLOWED_SUBNETS": "  192.168.1.0/24  ,  10.0.0.0/8  "},
        ):
            _check_subnet_allowed("10.1.2.3")


# ---------------------------------------------------------------------------
# Tests for _validate_dig_target
# ---------------------------------------------------------------------------


class TestValidateDigTarget:
    """Tests for the dig argument injection validator."""

    # --- Valid inputs that must pass ---

    def test_accepts_simple_hostname(self) -> None:
        """Plain hostname is accepted."""
        _validate_dig_target("example.com")

    def test_accepts_subdomain(self) -> None:
        """Multi-label hostname is accepted."""
        _validate_dig_target("sub.example.com")

    def test_accepts_deep_subdomain(self) -> None:
        """Deeply nested subdomain is accepted."""
        _validate_dig_target("a.b.c.example.com")

    def test_accepts_single_label(self) -> None:
        """Single-label hostname (e.g. 'localhost') is accepted."""
        _validate_dig_target("localhost")

    def test_accepts_ipv4_address(self) -> None:
        """IPv4 address is accepted."""
        _validate_dig_target("192.168.1.1")

    def test_accepts_hostname_with_digits(self) -> None:
        """Hostname labels containing digits are accepted."""
        _validate_dig_target("host1.example.com")

    def test_accepts_hostname_with_hyphens(self) -> None:
        """Hostname labels containing hyphens are accepted."""
        _validate_dig_target("my-host.example.com")

    def test_accepts_ipv6_bare(self) -> None:
        """Bare IPv6 address is accepted."""
        _validate_dig_target("2001:db8::1")

    def test_accepts_ipv6_loopback(self) -> None:
        """IPv6 loopback (::1) is accepted."""
        _validate_dig_target("::1")

    # --- Injection attacks that must be rejected ---

    def test_rejects_at_sign_nameserver(self) -> None:
        """@attacker.com redirects dig to an alternate nameserver — must be rejected."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("@attacker.com")

    def test_rejects_dash_option(self) -> None:
        """-b 0.0.0.0 is a dig flag — must be rejected."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("-b")

    def test_rejects_double_dash_option(self) -> None:
        """--option style flag is rejected."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("--trace")

    def test_rejects_space_in_target(self) -> None:
        """Whitespace is not a valid hostname character and must be rejected."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("example.com evil.com")

    def test_rejects_semicolon(self) -> None:
        """Semicolons are not valid in hostnames."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("example.com;evil.com")

    def test_rejects_backtick(self) -> None:
        """Backtick shell injection attempt is rejected."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("`id`")

    def test_rejects_dollar_sign(self) -> None:
        """Shell variable expansion attempt is rejected."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("$IFS")

    def test_rejects_at_embedded_in_value(self) -> None:
        """@ anywhere in the target is rejected (email-like or nameserver redirect)."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("user@example.com")

    def test_rejects_empty_string(self) -> None:
        """Empty string is not a valid target."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("")

    def test_rejects_slash_path(self) -> None:
        """Slash-separated path is not a valid hostname."""
        with pytest.raises(ValueError, match="Invalid dig target"):
            _validate_dig_target("/etc/passwd")
