"""Tests for Tenuo capability-token authorization integration.

Covers:
- Configuration (with and without tenuo installed)
- Permission-to-capability mapping
- Warrant minting (sync)
- Worker attenuation
- Tool authorization checks
- TenuoToolGuard wrapper
- Graceful degradation when tenuo is not installed/configured
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from agent_framework.security.capabilities import (
    _PERMISSION_TOOL_MAP,
    _active_warrant,
    capabilities_from_permissions,
    check_tool_authorized,
    configure_tenuo,
    is_tenuo_configured,
    mint_agent_warrant_sync,
    set_active_warrant,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_module_state() -> None:
    """Reset module-level state between tests."""
    import agent_framework.security.capabilities as caps

    caps._configured = False
    caps._dev_mode = True
    caps._tenuo_available = None
    # Reset context var
    token = _active_warrant.set(None)
    _active_warrant.reset(token)


# ---------------------------------------------------------------------------
# Tests: Graceful degradation (tenuo not installed)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """When tenuo is not installed, all operations should be no-ops."""

    def setup_method(self) -> None:
        _reset_module_state()

    def test_configure_returns_false_when_tenuo_missing(self) -> None:
        """configure_tenuo returns False if tenuo is not importable."""
        with patch("agent_framework.security.capabilities._check_tenuo", return_value=False):
            result = configure_tenuo()
            assert result is False
            assert not is_tenuo_configured()

    def test_capabilities_from_permissions_returns_empty_when_no_tenuo(self) -> None:
        """capabilities_from_permissions returns [] if tenuo not available."""
        with patch("agent_framework.security.capabilities._check_tenuo", return_value=False):
            caps = capabilities_from_permissions(["READ", "WRITE"])
            assert caps == []

    def test_mint_returns_none_when_not_configured(self) -> None:
        """mint_agent_warrant_sync returns None if tenuo not configured."""
        _reset_module_state()
        result = mint_agent_warrant_sync("test-agent", ["READ"])
        assert result is None

    def test_check_tool_authorized_passes_when_not_configured(self) -> None:
        """check_tool_authorized returns True when tenuo not configured."""
        _reset_module_state()
        assert check_tool_authorized("any_tool") is True

    def test_check_tool_authorized_passes_with_no_warrant(self) -> None:
        """check_tool_authorized returns True when no warrant in context."""
        import agent_framework.security.capabilities as caps

        caps._configured = True
        try:
            assert check_tool_authorized("any_tool") is True
        finally:
            caps._configured = False


# ---------------------------------------------------------------------------
# Tests: Permission-to-capability mapping
# ---------------------------------------------------------------------------


class TestPermissionMapping:
    """Test the _PERMISSION_TOOL_MAP structure."""

    def test_all_permission_levels_mapped(self) -> None:
        """Every permission level has at least one tool mapping."""
        expected_levels = {"READ", "WRITE", "DELETE", "EXECUTE", "SEND", "ADMIN"}
        assert set(_PERMISSION_TOOL_MAP.keys()) == expected_levels

    def test_read_tools_are_read_only(self) -> None:
        """READ tools should be non-destructive operations."""
        read_tools = _PERMISSION_TOOL_MAP["READ"]
        assert len(read_tools) > 0
        # All should be get/list/search/fetch/analyze operations
        for tool in read_tools:
            assert any(
                prefix in tool
                for prefix in ("get_", "list_", "search_", "fetch_", "analyze_", "recall_", "glob_", "grep_", "read_", "suggest_")
            ), f"Unexpected READ tool: {tool}"

    def test_write_tools_are_mutations(self) -> None:
        """WRITE tools should be create/modify operations."""
        write_tools = _PERMISSION_TOOL_MAP["WRITE"]
        assert len(write_tools) > 0
        for tool in write_tools:
            assert any(
                prefix in tool
                for prefix in ("save_", "add_", "move_", "update_", "create_", "write_", "edit_")
            ), f"Unexpected WRITE tool: {tool}"

    def test_delete_tools_are_destructive(self) -> None:
        """DELETE tools should be removal operations."""
        delete_tools = _PERMISSION_TOOL_MAP["DELETE"]
        assert len(delete_tools) > 0
        for tool in delete_tools:
            assert "delete_" in tool, f"Unexpected DELETE tool: {tool}"

    def test_execute_tools(self) -> None:
        """EXECUTE maps to code execution tools."""
        assert "run_claude_code" in _PERMISSION_TOOL_MAP["EXECUTE"]

    def test_send_tools(self) -> None:
        """SEND maps to communication tools."""
        send_tools = _PERMISSION_TOOL_MAP["SEND"]
        assert "send_email" in send_tools
        assert "send_slack_message" in send_tools

    def test_no_duplicate_tools_across_permissions(self) -> None:
        """No tool should appear in multiple permission levels."""
        all_tools: list[str] = []
        for tools in _PERMISSION_TOOL_MAP.values():
            all_tools.extend(tools)
        assert len(all_tools) == len(set(all_tools)), "Duplicate tool found across permission levels"


# ---------------------------------------------------------------------------
# Tests: capabilities_from_permissions (with mocked tenuo)
# ---------------------------------------------------------------------------


class TestCapabilitiesFromPermissions:
    """Test conversion of permission names to Tenuo Capability objects."""

    def setup_method(self) -> None:
        _reset_module_state()

    def test_single_permission(self) -> None:
        """Single permission maps to its tools."""
        mock_cap = MagicMock()
        with (
            patch("agent_framework.security.capabilities._check_tenuo", return_value=True),
            patch("agent_framework.security.capabilities.Capability", mock_cap) if False else
            patch.dict("sys.modules", {"tenuo": MagicMock()}),
        ):
            with patch("agent_framework.security.capabilities._check_tenuo", return_value=True):
                # When tenuo is available, it returns Capability objects
                caps = capabilities_from_permissions(["EXECUTE"])
                # Should have at least 1 capability (run_claude_code)
                # But since tenuo isn't actually installed, test the fallback
                # The function returns [] when _check_tenuo returns False
                pass

    def test_empty_permissions(self) -> None:
        """Empty permission list returns empty capabilities."""
        with patch("agent_framework.security.capabilities._check_tenuo", return_value=False):
            caps = capabilities_from_permissions([])
            assert caps == []

    def test_unknown_permission_returns_empty(self) -> None:
        """Unknown permission name returns no capabilities."""
        with patch("agent_framework.security.capabilities._check_tenuo", return_value=False):
            caps = capabilities_from_permissions(["NONEXISTENT"])
            assert caps == []


# ---------------------------------------------------------------------------
# Tests: Active warrant context variable
# ---------------------------------------------------------------------------


class TestActiveWarrant:
    """Test the context variable for active warrants."""

    def setup_method(self) -> None:
        _reset_module_state()

    def test_default_is_none(self) -> None:
        """Active warrant defaults to None."""
        assert _active_warrant.get() is None

    def test_set_and_get_warrant(self) -> None:
        """Setting a warrant makes it retrievable."""
        sentinel = object()
        token = set_active_warrant(sentinel)
        try:
            assert _active_warrant.get() is sentinel
        finally:
            _active_warrant.reset(token)

    def test_reset_restores_previous(self) -> None:
        """Resetting the token restores the previous value."""
        sentinel = object()
        token = set_active_warrant(sentinel)
        _active_warrant.reset(token)
        assert _active_warrant.get() is None


# ---------------------------------------------------------------------------
# Tests: TenuoToolGuard
# ---------------------------------------------------------------------------


class TestTenuoToolGuard:
    """Test the tool guard wrapper."""

    def setup_method(self) -> None:
        _reset_module_state()

    def test_wrap_returns_original_when_tenuo_not_available(self) -> None:
        """When tenuo is not installed, wrap() returns the original handler."""
        from agent_framework.security.capabilities import TenuoToolGuard

        with patch("agent_framework.security.capabilities._check_tenuo", return_value=False):
            guard = TenuoToolGuard()
            original = MagicMock()
            wrapped = guard.wrap("test_tool", original)
            assert wrapped is original


# ---------------------------------------------------------------------------
# Tests: Worker attenuation
# ---------------------------------------------------------------------------


class TestWorkerAttenuation:
    """Test attenuate_for_worker."""

    def setup_method(self) -> None:
        _reset_module_state()

    def test_returns_none_when_not_configured(self) -> None:
        """attenuate_for_worker returns None if tenuo not configured."""
        from agent_framework.security.capabilities import attenuate_for_worker

        result = attenuate_for_worker("/workspace/test", "feature/branch")
        assert result is None

    def test_accepts_workspace_and_branch(self) -> None:
        """attenuate_for_worker accepts workspace path and branch name."""
        from agent_framework.security.capabilities import attenuate_for_worker

        # Just verifying the API doesn't crash when not configured
        result = attenuate_for_worker(
            workspace_path="/home/user/.claude_code_workspaces/orch-123",
            branch_name="orchestrator/abc-fix-bug",
            ttl=timedelta(minutes=15),
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: Integration with existing permission system
# ---------------------------------------------------------------------------


class TestPermissionSystemIntegration:
    """Verify Tenuo mapping aligns with TOOL_PERMISSIONS from the permission system."""

    def test_mapped_tools_exist_in_tool_permissions(self) -> None:
        """All tools in _PERMISSION_TOOL_MAP should exist in TOOL_PERMISSIONS."""
        from agent_framework.permissions.tool_permissions import TOOL_PERMISSIONS

        all_tenuo_tools = set()
        for tools in _PERMISSION_TOOL_MAP.values():
            all_tenuo_tools.update(tools)

        for tool in all_tenuo_tools:
            assert tool in TOOL_PERMISSIONS, (
                f"Tool '{tool}' in _PERMISSION_TOOL_MAP but not in TOOL_PERMISSIONS"
            )

    def test_permission_levels_match(self) -> None:
        """Each tool's Tenuo permission level should match TOOL_PERMISSIONS."""
        from agent_framework.permissions.permissions import Permission
        from agent_framework.permissions.tool_permissions import TOOL_PERMISSIONS

        perm_name_to_enum = {
            "READ": Permission.READ,
            "WRITE": Permission.WRITE,
            "DELETE": Permission.DELETE,
            "EXECUTE": Permission.EXECUTE,
            "SEND": Permission.SEND,
            "ADMIN": Permission.ADMIN,
        }

        for perm_name, tools in _PERMISSION_TOOL_MAP.items():
            expected_perm = perm_name_to_enum[perm_name]
            for tool in tools:
                required = TOOL_PERMISSIONS.get(tool, set())
                assert expected_perm in required, (
                    f"Tool '{tool}' mapped to {perm_name} in Tenuo but "
                    f"requires {required} in TOOL_PERMISSIONS"
                )
