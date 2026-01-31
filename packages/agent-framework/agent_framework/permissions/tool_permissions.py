"""Tool-to-permission mappings.

Defines which permissions are required to execute each MCP tool.
Tools check these mappings before execution.
"""

from __future__ import annotations

from .permissions import Permission

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
    # Claude Code Tools - EXECUTE required for running code
    # =========================================================================
    "run_claude_code": {Permission.EXECUTE},
    "list_claude_code_workspaces": {Permission.READ},
    "create_claude_code_workspace": {Permission.WRITE},
    "delete_claude_code_workspace": {Permission.DELETE},
    "get_claude_code_workspace_status": {Permission.READ},
}


def get_required_permissions(tool_name: str) -> set[Permission]:
    """Get the permissions required to execute a tool.

    If a tool is not in the mapping, returns {Permission.ADMIN} as a
    fail-safe default (unknown tools require admin access).

    Args:
        tool_name: Name of the tool

    Returns:
        Set of required permissions

    Example:
        perms = get_required_permissions("fetch_web_content")
        # Returns {Permission.READ}

        perms = get_required_permissions("unknown_tool")
        # Returns {Permission.ADMIN} (fail-safe)
    """
    return TOOL_PERMISSIONS.get(tool_name, {Permission.ADMIN})


def check_tool_permission(
    tool_name: str,
    permissions: set[Permission] | list[Permission],
) -> tuple[bool, set[Permission]]:
    """Check if a permission set allows execution of a tool.

    Args:
        tool_name: Name of the tool to check
        permissions: The caller's permissions

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
    required = get_required_permissions(tool_name)
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
        "memory": ["save_memory", "get_memories", "search_memories",
                   "delete_memory", "get_memory_stats", "configure_memory"],
        "rag": ["add_document", "search_documents", "get_document",
                "list_documents", "delete_document", "get_rag_stats"],
        "email": ["list_mailboxes", "get_email", "search_emails",
                  "send_email", "send_agent_report", "move_email",
                  "update_email_flags", "delete_email"],
        "communication": ["send_slack"],
        "social_media": ["get_social_media"],
        "content": ["suggest_content"],
        "claude_code": ["run_claude_code", "list_claude_code",
                        "create_claude_code", "delete_claude_code",
                        "get_claude_code"],
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
