"""Tests for the tool permissions system."""

import pytest

from agent_framework.permissions.permissions import Permission, PermissionSet
from agent_framework.permissions.tool_permissions import (
    REMOTE_MCP_PERMISSIONS,
    TOOL_PERMISSIONS,
    check_tool_permission,
    get_allowed_tools,
    get_required_permissions,
    get_tool_permissions_by_category,
)


class TestToolPermissionMappings:
    """Tests for TOOL_PERMISSIONS mapping completeness."""

    def test_all_web_tools_mapped(self):
        """Verify all web analysis tools have permission mappings."""
        web_tools = ["fetch_web_content", "analyze_website"]
        for tool in web_tools:
            assert tool in TOOL_PERMISSIONS, f"Missing mapping for {tool}"

    def test_all_memory_tools_mapped(self):
        """Verify all memory tools have permission mappings."""
        memory_tools = [
            "get_memories",
            "search_memories",
            "get_memory_stats",
            "save_memory",
            "delete_memory",
            "configure_memory_store",
        ]
        for tool in memory_tools:
            assert tool in TOOL_PERMISSIONS, f"Missing mapping for {tool}"

    def test_all_rag_tools_mapped(self):
        """Verify all RAG tools have permission mappings."""
        rag_tools = [
            "search_documents",
            "get_document",
            "list_documents",
            "get_rag_stats",
            "add_document",
            "delete_document",
        ]
        for tool in rag_tools:
            assert tool in TOOL_PERMISSIONS, f"Missing mapping for {tool}"

    def test_all_email_tools_mapped(self):
        """Verify all FastMail tools have permission mappings."""
        email_tools = [
            "list_mailboxes",
            "get_emails",
            "get_email",
            "search_emails",
            "send_email",
            "send_agent_report",
            "move_email",
            "update_email_flags",
            "delete_email",
        ]
        for tool in email_tools:
            assert tool in TOOL_PERMISSIONS, f"Missing mapping for {tool}"

    def test_all_filesystem_tools_mapped(self):
        """Verify all filesystem tools have permission mappings."""
        filesystem_tools = [
            "read_file",
            "list_directory",
            "glob_files",
            "grep_files",
            "write_file",
            "edit_file",
        ]
        for tool in filesystem_tools:
            assert tool in TOOL_PERMISSIONS, f"Missing mapping for {tool}"

    def test_all_claude_code_tools_mapped(self):
        """Verify all Claude Code tools have permission mappings."""
        claude_code_tools = [
            "run_claude_code",
            "list_claude_code_workspaces",
            "create_claude_code_workspace",
            "delete_claude_code_workspace",
            "get_claude_code_workspace_status",
        ]
        for tool in claude_code_tools:
            assert tool in TOOL_PERMISSIONS, f"Missing mapping for {tool}"

    def test_read_tools_only_require_read(self):
        """Verify read-only tools only require READ permission."""
        read_only_tools = [
            "fetch_web_content",
            "analyze_website",
            "get_memories",
            "search_memories",
            "get_memory_stats",
            "search_documents",
            "get_document",
            "list_documents",
            "get_rag_stats",
            "list_mailboxes",
            "get_emails",
            "get_email",
            "search_emails",
            "get_social_media_stats",
            "suggest_content_topics",
            "list_claude_code_workspaces",
            "get_claude_code_workspace_status",
        ]
        for tool in read_only_tools:
            assert TOOL_PERMISSIONS[tool] == {Permission.READ}, (
                f"{tool} should only require READ, got {TOOL_PERMISSIONS[tool]}"
            )

    def test_write_tools_require_write(self):
        """Verify write tools require WRITE permission."""
        write_tools = [
            "save_memory",
            "add_document",
            "move_email",
            "update_email_flags",
            "create_claude_code_workspace",
            "write_file",
            "edit_file",
        ]
        for tool in write_tools:
            assert Permission.WRITE in TOOL_PERMISSIONS[tool], f"{tool} should require WRITE"

    def test_delete_tools_require_delete(self):
        """Verify delete tools require DELETE permission."""
        delete_tools = [
            "delete_memory",
            "delete_document",
            "delete_email",
            "delete_claude_code_workspace",
        ]
        for tool in delete_tools:
            assert Permission.DELETE in TOOL_PERMISSIONS[tool], f"{tool} should require DELETE"

    def test_send_tools_require_send(self):
        """Verify communication tools require SEND permission."""
        send_tools = [
            "send_email",
            "send_agent_report",
            "send_slack_message",
        ]
        for tool in send_tools:
            assert Permission.SEND in TOOL_PERMISSIONS[tool], f"{tool} should require SEND"

    def test_execute_tools_require_execute(self):
        """Verify code execution tools require EXECUTE permission."""
        execute_tools = [
            "run_claude_code",
        ]
        for tool in execute_tools:
            assert Permission.EXECUTE in TOOL_PERMISSIONS[tool], f"{tool} should require EXECUTE"


class TestGetRequiredPermissions:
    """Tests for get_required_permissions function."""

    def test_known_tool_returns_mapped_permissions(self):
        """Test that known tools return their mapped permissions."""
        perms = get_required_permissions("fetch_web_content")
        assert perms == {Permission.READ}

        perms = get_required_permissions("send_email")
        assert perms == {Permission.SEND}

    def test_unknown_tool_requires_admin(self):
        """Test that unknown tools default to ADMIN permission."""
        perms = get_required_permissions("unknown_tool_xyz")
        assert perms == {Permission.ADMIN}

        perms = get_required_permissions("definitely_not_a_tool")
        assert perms == {Permission.ADMIN}


class TestCheckToolPermission:
    """Tests for check_tool_permission function."""

    def test_allowed_with_required_permission(self):
        """Test tool is allowed when permission is present."""
        allowed, missing = check_tool_permission("fetch_web_content", {Permission.READ})
        assert allowed is True
        assert missing == set()

    def test_denied_without_required_permission(self):
        """Test tool is denied when permission is missing."""
        allowed, missing = check_tool_permission(
            "send_email",
            {Permission.READ},  # Missing SEND
        )
        assert allowed is False
        assert Permission.SEND in missing

    def test_allowed_with_extra_permissions(self):
        """Test tool is allowed even with extra permissions."""
        allowed, missing = check_tool_permission(
            "fetch_web_content", {Permission.READ, Permission.WRITE, Permission.SEND}
        )
        assert allowed is True
        assert missing == set()

    def test_denied_unknown_tool_without_admin(self):
        """Test unknown tools are denied without ADMIN."""
        allowed, missing = check_tool_permission(
            "unknown_tool", {Permission.READ, Permission.WRITE, Permission.SEND}
        )
        assert allowed is False
        assert Permission.ADMIN in missing

    def test_allowed_unknown_tool_with_admin(self):
        """Test unknown tools are allowed with ADMIN."""
        allowed, missing = check_tool_permission("unknown_tool", {Permission.ADMIN})
        assert allowed is True
        assert missing == set()

    def test_accepts_list_of_permissions(self):
        """Test function accepts list instead of set."""
        allowed, missing = check_tool_permission(
            "fetch_web_content", [Permission.READ, Permission.WRITE]
        )
        assert allowed is True


class TestGetAllowedTools:
    """Tests for get_allowed_tools function."""

    def test_read_only_allows_read_tools(self):
        """Test READ permission only allows read tools."""
        allowed = get_allowed_tools({Permission.READ})

        # Should include read-only tools
        assert "fetch_web_content" in allowed
        assert "analyze_website" in allowed
        assert "get_memories" in allowed
        assert "search_documents" in allowed

        # Should not include write/send/delete tools
        assert "save_memory" not in allowed
        assert "send_email" not in allowed
        assert "delete_document" not in allowed

    def test_send_allows_send_tools(self):
        """Test SEND permission allows communication tools."""
        allowed = get_allowed_tools({Permission.SEND})

        assert "send_email" in allowed
        assert "send_agent_report" in allowed
        assert "send_slack_message" in allowed

    def test_combined_permissions(self):
        """Test combined permissions allow more tools."""
        allowed = get_allowed_tools({Permission.READ, Permission.WRITE})

        # Read tools
        assert "fetch_web_content" in allowed
        # Write tools
        assert "save_memory" in allowed
        assert "add_document" in allowed
        # But not send tools
        assert "send_email" not in allowed

    def test_full_access_allows_most_tools(self):
        """Test full_access (minus ADMIN) allows most mapped tools."""
        full = {
            Permission.READ,
            Permission.WRITE,
            Permission.DELETE,
            Permission.EXECUTE,
            Permission.SEND,
        }
        allowed = get_allowed_tools(full)

        # Should include almost everything except ADMIN-only tools
        assert "fetch_web_content" in allowed
        assert "save_memory" in allowed
        assert "delete_document" in allowed
        assert "send_email" in allowed
        assert "run_claude_code" in allowed

        # But not ADMIN-only tools
        assert "configure_memory_store" not in allowed

    def test_admin_allows_admin_tools(self):
        """Test ADMIN permission allows admin-only tools."""
        allowed = get_allowed_tools({Permission.ADMIN})

        assert "configure_memory_store" in allowed

    def test_empty_permissions_allows_nothing(self):
        """Test empty permissions allow no tools."""
        allowed = get_allowed_tools(set())
        assert len(allowed) == 0

    def test_returns_sorted_list(self):
        """Test that results are sorted alphabetically."""
        allowed = get_allowed_tools({Permission.READ})
        assert allowed == sorted(allowed)


class TestGetToolPermissionsByCategory:
    """Tests for get_tool_permissions_by_category function."""

    def test_returns_expected_categories(self):
        """Test that all expected categories are present."""
        categories = get_tool_permissions_by_category()

        expected = {
            "web_analysis",
            "memory",
            "rag",
            "email",
            "calendar",
            "communication",
            "social_media",
            "content",
            "filesystem",
            "claude_code",
        }
        assert set(categories.keys()) == expected

    def test_web_analysis_category(self):
        """Test web_analysis category contains expected tools."""
        categories = get_tool_permissions_by_category()
        web_tools = categories["web_analysis"]

        assert "fetch_web_content" in web_tools
        assert "analyze_website" in web_tools

    def test_email_category(self):
        """Test email category contains expected tools."""
        categories = get_tool_permissions_by_category()
        email_tools = categories["email"]

        assert "send_email" in email_tools
        assert "get_emails" in email_tools
        assert "send_agent_report" in email_tools


class TestPermissionSet:
    """Tests for PermissionSet class from permissions module."""

    def test_empty_permission_set(self):
        """Test empty permission set has no permissions."""
        empty = PermissionSet.empty()
        assert len(empty) == 0
        assert not empty.has(Permission.READ)

    def test_read_only_permission_set(self):
        """Test read_only factory method."""
        read_only = PermissionSet.read_only()
        assert read_only.has(Permission.READ)
        assert not read_only.has(Permission.WRITE)
        assert not read_only.has(Permission.SEND)

    def test_standard_permission_set(self):
        """Test standard factory method."""
        standard = PermissionSet.standard()
        assert standard.has(Permission.READ)
        assert standard.has(Permission.WRITE)
        assert standard.has(Permission.SEND)
        assert not standard.has(Permission.DELETE)
        assert not standard.has(Permission.EXECUTE)

    def test_full_access_permission_set(self):
        """Test full_access factory method."""
        full = PermissionSet.full_access()
        assert full.has(Permission.READ)
        assert full.has(Permission.WRITE)
        assert full.has(Permission.DELETE)
        assert full.has(Permission.EXECUTE)
        assert full.has(Permission.SEND)
        assert not full.has(Permission.ADMIN)

    def test_admin_permission_set(self):
        """Test admin factory method includes all permissions."""
        admin = PermissionSet.admin()
        for perm in Permission:
            assert admin.has(perm), f"admin should have {perm}"

    def test_intersection(self):
        """Test intersection of permission sets."""
        full = PermissionSet.full_access()
        read_only = PermissionSet.read_only()

        result = full.intersection(read_only)

        assert result.has(Permission.READ)
        assert not result.has(Permission.WRITE)
        assert not result.has(Permission.SEND)

    def test_union(self):
        """Test union of permission sets."""
        read_only = PermissionSet.read_only()
        send_only = PermissionSet([Permission.SEND])

        result = read_only.union(send_only)

        assert result.has(Permission.READ)
        assert result.has(Permission.SEND)
        assert not result.has(Permission.WRITE)

    def test_to_list_and_from_list(self):
        """Test serialization and deserialization."""
        original = PermissionSet([Permission.READ, Permission.WRITE])
        names = original.to_list()

        restored = PermissionSet.from_list(names)

        assert original == restored

    def test_from_list_invalid_name(self):
        """Test from_list raises on invalid permission name."""
        with pytest.raises(ValueError) as exc_info:
            PermissionSet.from_list(["READ", "INVALID"])

        assert "Unknown permission" in str(exc_info.value)

    def test_contains_operator(self):
        """Test 'in' operator for permission checking."""
        perms = PermissionSet([Permission.READ, Permission.WRITE])

        assert Permission.READ in perms
        assert Permission.WRITE in perms
        assert Permission.SEND not in perms


GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"


class TestRemoteMCPPermissions:
    """Tests for REMOTE_MCP_PERMISSIONS config and get_required_permissions with server_url."""

    def test_github_server_configured(self):
        """Test that the GitHub Copilot MCP server is in REMOTE_MCP_PERMISSIONS."""
        assert GITHUB_MCP_URL in REMOTE_MCP_PERMISSIONS

    def test_github_server_has_default(self):
        """Test that GitHub server config includes a default permission set."""
        config = REMOTE_MCP_PERMISSIONS[GITHUB_MCP_URL]
        assert "default" in config
        assert config["default"] == {Permission.READ, Permission.WRITE}

    def test_github_server_has_tools(self):
        """Test that GitHub server config includes tool-specific overrides."""
        config = REMOTE_MCP_PERMISSIONS[GITHUB_MCP_URL]
        assert "tools" in config
        assert len(config["tools"]) > 0

    def test_github_read_tool_override(self):
        """Test tool-specific READ override for a known GitHub tool."""
        perms = get_required_permissions("get_me", GITHUB_MCP_URL)
        assert perms == {Permission.READ}

    def test_github_write_tool_override(self):
        """Test tool-specific WRITE override for a known GitHub tool."""
        perms = get_required_permissions("create_issue", GITHUB_MCP_URL)
        assert perms == {Permission.WRITE}

    def test_github_admin_tool_override(self):
        """Test tool-specific ADMIN override for dangerous GitHub operations."""
        perms = get_required_permissions("delete_file", GITHUB_MCP_URL)
        assert perms == {Permission.ADMIN}

        perms = get_required_permissions("merge_pull_request", GITHUB_MCP_URL)
        assert perms == {Permission.ADMIN}

    def test_github_unknown_tool_uses_server_default(self):
        """Test that an unknown tool on a known server uses the server default."""
        perms = get_required_permissions("some_new_github_tool", GITHUB_MCP_URL)
        assert perms == {Permission.READ, Permission.WRITE}

    def test_unknown_server_unknown_tool_requires_admin(self):
        """Test that an unknown tool on an unknown server falls back to ADMIN."""
        perms = get_required_permissions("unknown_tool", "https://unknown-server.example.com/mcp/")
        assert perms == {Permission.ADMIN}

    def test_local_tool_ignores_server_url(self):
        """Test that local tools are resolved from TOOL_PERMISSIONS even with server_url."""
        perms = get_required_permissions("fetch_web_content", GITHUB_MCP_URL)
        assert perms == {Permission.READ}

    def test_server_url_none_falls_back_to_admin_for_unknown(self):
        """Test that server_url=None for unknown tools falls back to ADMIN."""
        perms = get_required_permissions("totally_unknown_tool", None)
        assert perms == {Permission.ADMIN}

    def test_all_github_read_tools_require_read(self):
        """Verify all read-only GitHub tool overrides require only READ."""
        read_tools = [
            "get_me",
            "get_file_contents",
            "search_code",
            "search_repositories",
            "search_issues",
            "search_pull_requests",
            "search_users",
            "list_issues",
            "list_pull_requests",
            "list_commits",
            "list_branches",
            "list_tags",
            "list_releases",
            "get_issue",
            "get_commit",
            "get_tag",
            "get_release_by_tag",
            "get_latest_release",
            "get_label",
            "get_teams",
            "get_team_members",
            "issue_read",
            "pull_request_read",
        ]
        for tool in read_tools:
            perms = get_required_permissions(tool, GITHUB_MCP_URL)
            assert perms == {Permission.READ}, f"{tool} should require READ, got {perms}"

    def test_all_github_write_tools_require_write(self):
        """Verify all write GitHub tool overrides require only WRITE."""
        write_tools = [
            "create_issue",
            "update_issue",
            "issue_write",
            "add_issue_comment",
            "create_pull_request",
            "update_pull_request",
            "update_pull_request_branch",
            "create_branch",
            "create_or_update_file",
            "push_files",
            "pull_request_review_write",
            "add_comment_to_pending_review",
            "sub_issue_write",
            "request_copilot_review",
            "assign_copilot_to_issue",
        ]
        for tool in write_tools:
            perms = get_required_permissions(tool, GITHUB_MCP_URL)
            assert perms == {Permission.WRITE}, f"{tool} should require WRITE, got {perms}"

    def test_all_github_admin_tools_require_admin(self):
        """Verify all dangerous GitHub tool overrides require ADMIN."""
        admin_tools = [
            "delete_file",
            "fork_repository",
            "create_repository",
            "merge_pull_request",
        ]
        for tool in admin_tools:
            perms = get_required_permissions(tool, GITHUB_MCP_URL)
            assert perms == {Permission.ADMIN}, f"{tool} should require ADMIN, got {perms}"

    def test_config_values_are_sets_of_permission(self):
        """Verify all config values are proper set[Permission] types."""
        for server_url, config in REMOTE_MCP_PERMISSIONS.items():
            if "default" in config:
                default = config["default"]
                assert isinstance(default, set), (
                    f"{server_url} default should be set, got {type(default)}"
                )
                for perm in default:
                    assert isinstance(perm, Permission), (
                        f"{server_url} default contains non-Permission: {perm}"
                    )
            if "tools" in config:
                for tool_name, perms in config["tools"].items():
                    assert isinstance(perms, set), (
                        f"{server_url}/{tool_name} should be set, got {type(perms)}"
                    )
                    for perm in perms:
                        assert isinstance(perm, Permission), (
                            f"{server_url}/{tool_name} contains non-Permission: {perm}"
                        )


class TestCheckToolPermissionWithServerUrl:
    """Tests for check_tool_permission with server_url parameter."""

    def test_remote_read_tool_allowed_with_read(self):
        """Test remote read tool is allowed with READ permission."""
        allowed, missing = check_tool_permission(
            "get_me", {Permission.READ}, server_url=GITHUB_MCP_URL
        )
        assert allowed is True
        assert missing == set()

    def test_remote_read_tool_denied_without_read(self):
        """Test remote read tool is denied without READ permission."""
        allowed, missing = check_tool_permission(
            "get_me", {Permission.WRITE}, server_url=GITHUB_MCP_URL
        )
        assert allowed is False
        assert Permission.READ in missing

    def test_remote_write_tool_allowed_with_write(self):
        """Test remote write tool is allowed with WRITE permission."""
        allowed, missing = check_tool_permission(
            "create_issue", {Permission.WRITE}, server_url=GITHUB_MCP_URL
        )
        assert allowed is True
        assert missing == set()

    def test_remote_unknown_tool_uses_server_default(self):
        """Test unknown remote tool uses server default permissions."""
        allowed, missing = check_tool_permission(
            "some_new_tool",
            {Permission.READ, Permission.WRITE},
            server_url=GITHUB_MCP_URL,
        )
        assert allowed is True
        assert missing == set()

    def test_remote_unknown_tool_denied_with_partial_perms(self):
        """Test unknown remote tool denied when missing part of server default."""
        allowed, missing = check_tool_permission(
            "some_new_tool",
            {Permission.READ},  # Missing WRITE from default {READ, WRITE}
            server_url=GITHUB_MCP_URL,
        )
        assert allowed is False
        assert Permission.WRITE in missing

    def test_unknown_server_requires_admin(self):
        """Test tool on unknown server requires ADMIN."""
        allowed, missing = check_tool_permission(
            "some_tool",
            {Permission.READ, Permission.WRITE},
            server_url="https://unknown.example.com/mcp/",
        )
        assert allowed is False
        assert Permission.ADMIN in missing

    def test_none_server_url_for_local_tool(self):
        """Test local tool with server_url=None works as before."""
        allowed, missing = check_tool_permission(
            "fetch_web_content", {Permission.READ}, server_url=None
        )
        assert allowed is True
        assert missing == set()
