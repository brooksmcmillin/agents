"""Tool-to-permission mappings.

Defines which permissions are required to execute each MCP tool.
Tools check these mappings before execution.

For remote MCP servers, use REMOTE_MCP_PERMISSIONS to define:
- Server-level default permissions
- Tool-specific overrides for dangerous operations
"""

from __future__ import annotations

from typing import TypedDict

from .permissions import Permission


class RemoteMCPServerConfig(TypedDict, total=False):
    """Configuration for a remote MCP server's permission defaults.

    Attributes:
        default: Default permissions applied to all tools from this server.
        tools: Tool-specific permission overrides.
    """

    default: set[Permission]
    tools: dict[str, set[Permission]]


# Mapping of tool names to required permissions
# A tool can be executed if the caller has ALL required permissions
TOOL_PERMISSIONS: dict[str, set[Permission]] = {
    # =========================================================================
    # Web Analysis Tools - READ only (fetch/analyze content)
    # =========================================================================
    "fetch_web_content": {Permission.READ},
    "analyze_website": {Permission.READ},
    # =========================================================================
    # Memory Tools - READ for retrieval, WRITE for modification
    # =========================================================================
    "get_memories": {Permission.READ},
    "search_memories": {Permission.READ},
    "recall_memories": {Permission.READ},
    "get_memory_stats": {Permission.READ},
    "save_memory": {Permission.WRITE},
    "delete_memory": {Permission.DELETE},
    "configure_memory_store": {Permission.ADMIN},
    # =========================================================================
    # RAG Document Tools - READ for search, WRITE for modification
    # =========================================================================
    "search_documents": {Permission.READ},
    "get_document": {Permission.READ},
    "list_documents": {Permission.READ},
    "get_rag_stats": {Permission.READ},
    "add_document": {Permission.WRITE},
    "delete_document": {Permission.DELETE},
    # =========================================================================
    # FastMail Email Tools - READ for retrieval, SEND for sending
    # =========================================================================
    "list_mailboxes": {Permission.READ},
    "get_emails": {Permission.READ},
    "get_email": {Permission.READ},
    "search_emails": {Permission.READ},
    "send_email": {Permission.SEND},
    "send_agent_report": {Permission.SEND},
    "move_email": {Permission.WRITE},
    "update_email_flags": {Permission.WRITE},
    "delete_email": {Permission.DELETE},
    # =========================================================================
    # Communication Tools - SEND required
    # =========================================================================
    "send_slack_message": {Permission.SEND},
    # =========================================================================
    # Social Media Tools - READ for stats, WRITE for posting
    # =========================================================================
    "get_social_media_stats": {Permission.READ},
    # Future: "post_to_twitter": {Permission.SEND},
    # Future: "post_to_linkedin": {Permission.SEND},
    # =========================================================================
    # Content Suggestion Tools - READ only (generates suggestions)
    # =========================================================================
    "suggest_content_topics": {Permission.READ},
    # =========================================================================
    # Filesystem Tools - READ only (scoped to FILESYSTEM_ALLOWED_DIRS)
    # =========================================================================
    "read_file": {Permission.READ},
    "list_directory": {Permission.READ},
    "glob_files": {Permission.READ},
    "grep_files": {Permission.READ},
    # =========================================================================
    # Claude Code Tools - EXECUTE required for running code
    # =========================================================================
    "run_claude_code": {Permission.EXECUTE},
    "list_claude_code_workspaces": {Permission.READ},
    "create_claude_code_workspace": {Permission.WRITE},
    "delete_claude_code_workspace": {Permission.DELETE},
    "get_claude_code_workspace_status": {Permission.READ},
}

# =============================================================================
# Remote MCP Server Permissions
# =============================================================================
# Configuration for remote MCP servers with:
# - "default": set[Permission] applied to all tools from this server
# - "tools": Dict of tool-specific permission overrides
#
# Tools not in TOOL_PERMISSIONS or REMOTE_MCP_PERMISSIONS require ADMIN.
# =============================================================================

REMOTE_MCP_PERMISSIONS: dict[str, RemoteMCPServerConfig] = {
    # GitHub Copilot MCP Server
    "https://api.githubcopilot.com/mcp/": {
        "default": {Permission.READ, Permission.WRITE},  # Most GitHub tools are safe
        "tools": {
            # Read-only operations
            "get_me": {Permission.READ},
            "get_file_contents": {Permission.READ},
            "search_code": {Permission.READ},
            "search_repositories": {Permission.READ},
            "search_issues": {Permission.READ},
            "search_pull_requests": {Permission.READ},
            "search_users": {Permission.READ},
            "list_issues": {Permission.READ},
            "list_pull_requests": {Permission.READ},
            "list_commits": {Permission.READ},
            "list_branches": {Permission.READ},
            "list_tags": {Permission.READ},
            "list_releases": {Permission.READ},
            "get_issue": {Permission.READ},
            "get_commit": {Permission.READ},
            "get_tag": {Permission.READ},
            "get_release_by_tag": {Permission.READ},
            "get_latest_release": {Permission.READ},
            "get_label": {Permission.READ},
            "get_teams": {Permission.READ},
            "get_team_members": {Permission.READ},
            "issue_read": {Permission.READ},
            "pull_request_read": {Permission.READ},
            # Write operations
            "create_issue": {Permission.WRITE},
            "update_issue": {Permission.WRITE},
            "issue_write": {Permission.WRITE},
            "add_issue_comment": {Permission.WRITE},
            "create_pull_request": {Permission.WRITE},
            "update_pull_request": {Permission.WRITE},
            "update_pull_request_branch": {Permission.WRITE},
            "create_branch": {Permission.WRITE},
            "create_or_update_file": {Permission.WRITE},
            "push_files": {Permission.WRITE},
            "pull_request_review_write": {Permission.WRITE},
            "add_comment_to_pending_review": {Permission.WRITE},
            "sub_issue_write": {Permission.WRITE},
            "request_copilot_review": {Permission.WRITE},
            "assign_copilot_to_issue": {Permission.WRITE},
            # Dangerous operations - require ADMIN
            "delete_file": {Permission.ADMIN},
            "fork_repository": {Permission.ADMIN},
            "create_repository": {Permission.ADMIN},
            "merge_pull_request": {Permission.ADMIN},
        },
    },
    # Add more remote MCP servers here as needed
    # "https://other-mcp-server.example.com/mcp/": {
    #     "default": {Permission.READ},
    #     "tools": { ... },
    # },
}


def get_required_permissions(
    tool_name: str,
    server_url: str | None = None,
) -> set[Permission]:
    """Get the permissions required to execute a tool.

    Permission lookup order:
    1. Local tools: Check TOOL_PERMISSIONS
    2. Remote tools: Check REMOTE_MCP_PERMISSIONS for server-specific config
       a. Tool-specific override if defined
       b. Server default if no tool override
    3. Fall back to {Permission.ADMIN} for unknown tools (fail-safe)

    Args:
        tool_name: Name of the tool
        server_url: Optional URL of the remote MCP server (for remote tools)

    Returns:
        Set of required permissions

    Example:
        # Local tool
        perms = get_required_permissions("fetch_web_content")
        # Returns {Permission.READ}

        # Remote tool with server config
        perms = get_required_permissions("get_me", "https://api.githubcopilot.com/mcp/")
        # Returns {Permission.READ}

        # Unknown tool
        perms = get_required_permissions("unknown_tool")
        # Returns {Permission.ADMIN} (fail-safe)
    """
    # 1. Check local tool permissions first
    if tool_name in TOOL_PERMISSIONS:
        return TOOL_PERMISSIONS[tool_name]

    # 2. Check remote MCP server permissions
    if server_url and server_url in REMOTE_MCP_PERMISSIONS:
        server_config = REMOTE_MCP_PERMISSIONS[server_url]

        # 2a. Check for tool-specific override
        if "tools" in server_config and tool_name in server_config["tools"]:
            return server_config["tools"][tool_name]

        # 2b. Use server default
        if "default" in server_config:
            return server_config["default"]

    # 3. Fall back to ADMIN for unknown tools
    return {Permission.ADMIN}


def check_tool_permission(
    tool_name: str,
    permissions: set[Permission] | list[Permission],
    server_url: str | None = None,
) -> tuple[bool, set[Permission]]:
    """Check if a permission set allows execution of a tool.

    Args:
        tool_name: Name of the tool to check
        permissions: The caller's permissions
        server_url: Optional URL of the remote MCP server (for remote tools)

    Returns:
        Tuple of (allowed, missing_permissions)

    Example:
        allowed, missing = check_tool_permission(
            "send_email",
            {Permission.READ}
        )
        # allowed = False
        # missing = {Permission.SEND}
    """
    required = get_required_permissions(tool_name, server_url)
    caller_perms = set(permissions)
    missing = required - caller_perms

    return len(missing) == 0, missing


def get_allowed_tools(permissions: set[Permission] | list[Permission]) -> list[str]:
    """Get list of tools allowed by a permission set.

    Args:
        permissions: The caller's permissions

    Returns:
        List of tool names that can be executed
    """
    caller_perms = set(permissions)
    allowed = []

    for tool_name, required in TOOL_PERMISSIONS.items():
        if required <= caller_perms:  # All required perms are present
            allowed.append(tool_name)

    return sorted(allowed)


def get_tool_permissions_by_category() -> dict[str, dict[str, set[Permission]]]:
    """Get tool permissions organized by category.

    Useful for documentation and debugging.

    Returns:
        Dict mapping category names to {tool_name: permissions}
    """
    categories: dict[str, dict[str, set[Permission]]] = {
        "web_analysis": {},
        "memory": {},
        "rag": {},
        "email": {},
        "communication": {},
        "social_media": {},
        "content": {},
        "claude_code": {},
    }

    category_prefixes = {
        "web_analysis": ["fetch_web", "analyze_website"],
        "memory": [
            "save_memory",
            "get_memories",
            "search_memories",
            "recall_memories",
            "delete_memory",
            "get_memory_stats",
            "configure_memory",
        ],
        "rag": [
            "add_document",
            "search_documents",
            "get_document",
            "list_documents",
            "delete_document",
            "get_rag_stats",
        ],
        "email": [
            "list_mailboxes",
            "get_email",
            "search_emails",
            "send_email",
            "send_agent_report",
            "move_email",
            "update_email_flags",
            "delete_email",
        ],
        "communication": ["send_slack"],
        "social_media": ["get_social_media"],
        "content": ["suggest_content"],
        "claude_code": [
            "run_claude_code",
            "list_claude_code",
            "create_claude_code",
            "delete_claude_code",
            "get_claude_code",
        ],
    }

    for tool_name, perms in TOOL_PERMISSIONS.items():
        categorized = False
        for category, prefixes in category_prefixes.items():
            for prefix in prefixes:
                if tool_name.startswith(prefix) or tool_name == prefix:
                    categories[category][tool_name] = perms
                    categorized = True
                    break
            if categorized:
                break

    return categories
