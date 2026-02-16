"""Tests for HTTP client security: credential redaction, session isolation, target allowlist."""

import os
import time
from unittest.mock import patch

import pytest
from agent_framework.tools.http_client import (
    _check_target_allowed,
    _get_session,
    _redact_sensitive,
    _session_key,
    _sessions,
    http_clear_session,
)


class TestCredentialRedaction:
    """Ensure sensitive fields are redacted regardless of casing/format."""

    def test_redacts_password(self) -> None:
        result = _redact_sensitive({"password": "s3cret"})
        assert result["password"] == "[REDACTED]"

    def test_redacts_api_key_case_insensitive(self) -> None:
        result = _redact_sensitive({"API_KEY": "abc123"})
        assert result["API_KEY"] == "[REDACTED]"

    def test_redacts_hyphenated_headers(self) -> None:
        """api-key, x-auth-token, etc. should be normalised and redacted."""
        result = _redact_sensitive({"Api-Key": "xyz", "X-Auth-Token": "tok"})
        assert result["Api-Key"] == "[REDACTED]"
        assert result["X-Auth-Token"] == "[REDACTED]"

    def test_redacts_authorization(self) -> None:
        result = _redact_sensitive({"Authorization": "Bearer abc"})
        assert result["Authorization"] == "[REDACTED]"

    def test_redacts_cookie_and_set_cookie(self) -> None:
        result = _redact_sensitive({"Cookie": "sid=abc", "Set-Cookie": "sid=def"})
        assert result["Cookie"] == "[REDACTED]"
        assert result["Set-Cookie"] == "[REDACTED]"

    def test_preserves_non_sensitive_fields(self) -> None:
        result = _redact_sensitive({"Content-Type": "application/json", "Accept": "text/html"})
        assert result["Content-Type"] == "application/json"
        assert result["Accept"] == "text/html"

    def test_mixed_sensitive_and_safe(self) -> None:
        data = {"username": "admin", "password": "s3cret", "remember": "true"}
        result = _redact_sensitive(data)
        assert result["username"] == "admin"
        assert result["password"] == "[REDACTED]"
        assert result["remember"] == "true"

    def test_empty_dict(self) -> None:
        assert _redact_sensitive({}) == {}

    def test_all_sensitive_fields(self) -> None:
        """Ensure every field in _SENSITIVE_FIELDS is actually redacted."""
        from agent_framework.tools.http_client import _SENSITIVE_FIELDS

        for field in _SENSITIVE_FIELDS:
            result = _redact_sensitive({field: "value"})
            assert result[field] == "[REDACTED]", f"Field {field!r} was not redacted"


class TestTargetAllowlist:
    """Ensure requests outside the allowlist are rejected."""

    def test_rejects_when_env_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("REDTEAM_ALLOWED_TARGETS", None)
            with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
                _check_target_allowed("http://example.com")

    def test_allows_exact_match(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            _check_target_allowed("http://example.com/")  # should not raise

    def test_allows_subpath(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            _check_target_allowed("http://example.com/api/users")

    def test_rejects_different_host(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://evil.com/api")

    def test_rejects_subdomain_bypass(self) -> None:
        """Subdomain evil.example.com should not match example.com."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://evil.example.com/api")

    def test_rejects_scheme_mismatch(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "https://example.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api")

    def test_rejects_port_mismatch(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com:8080"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com:9090/api")

    def test_rejects_path_prefix_confusion(self) -> None:
        """'/api/v1' should NOT match '/api/v1admin' (boundary check)."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api/v1"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/v1admin")

    def test_rejects_path_traversal(self) -> None:
        """/api/../admin should normalize and fail."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/../admin")

    def test_rejects_invalid_url(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            with pytest.raises(ValueError, match="Invalid URL"):
                _check_target_allowed("not-a-url")

    def test_multiple_allowed_targets(self) -> None:
        targets = "http://a.com/app, https://b.com/api"
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": targets}):
            _check_target_allowed("http://a.com/app/page")
            _check_target_allowed("https://b.com/api/v1")
            with pytest.raises(ValueError):
                _check_target_allowed("http://c.com")


class TestSessionIsolation:
    """Ensure sessions are scoped per agent and expire properly."""

    def setup_method(self) -> None:
        _sessions.clear()

    def test_sessions_scoped_by_agent_name(self) -> None:
        sess_a = _get_session("agent_a", "default")
        sess_b = _get_session("agent_b", "default")
        sess_a["cookies"]["sid"] = "aaa"
        assert "sid" not in sess_b.get("cookies", {})

    def test_session_key_format(self) -> None:
        assert _session_key("agent_a", "mysession") == "agent_a:mysession"

    def test_separate_named_sessions(self) -> None:
        sess1 = _get_session("agent_a", "session1")
        sess2 = _get_session("agent_a", "session2")
        sess1["cookies"]["a"] = "1"
        assert "a" not in sess2.get("cookies", {})

    @pytest.mark.asyncio
    async def test_clear_session(self) -> None:
        _get_session("agent_a", "default")
        result = await http_clear_session("agent_a", "default")
        assert result["cleared"] is True

    @pytest.mark.asyncio
    async def test_clear_nonexistent_session(self) -> None:
        result = await http_clear_session("agent_a", "nonexistent")
        assert result["cleared"] is False

    def test_session_expiry(self) -> None:
        from agent_framework.tools.http_client import _SESSION_TTL_SECONDS, _expire_sessions

        sess = _get_session("agent_a", "default")
        sess["last_used"] = time.monotonic() - _SESSION_TTL_SECONDS - 1
        _expire_sessions()
        key = _session_key("agent_a", "default")
        assert key not in _sessions

    def test_fresh_session_not_expired(self) -> None:
        from agent_framework.tools.http_client import _expire_sessions

        _get_session("agent_a", "default")
        _expire_sessions()
        key = _session_key("agent_a", "default")
        assert key in _sessions
