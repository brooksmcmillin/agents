"""Shared constants for the agents project.

Contains common configuration values, URLs, and environment variable names.
"""

# Environment variable names (not actual secrets, just the env var keys)
ENV_MCP_SERVER_URL = "MCP_SERVER_URL"
ENV_MCP_AUTH_TOKEN = "MCP_AUTH_TOKEN"  # nosec B105  # pragma: allowlist secret
ENV_SLACK_WEBHOOK_URL = "SLACK_WEBHOOK_URL"
ENV_SLACK_BOT_TOKEN = "SLACK_BOT_TOKEN"  # nosec B105  # pragma: allowlist secret
ENV_SLACK_APP_TOKEN = "SLACK_APP_TOKEN"  # nosec B105  # pragma: allowlist secret
ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"  # pragma: allowlist secret

# Default URLs
DEFAULT_MCP_SERVER_URL = "https://mcp.brooksmcmillin.com/mcp"
DEFAULT_MCP_RELAY_URL = "https://mcp-relay.brooksmcmillin.com/mcp"

# ---------------------------------------------------------------------------
# MCP Relay sender field — SECURITY NOTE
#
# The MCP relay server accepts a ``sender`` field on relay tool calls that
# identifies the agent sending the message. This field is UNTRUSTED and
# ADVISORY ONLY. Because the relay server does not validate the sender
# against the authenticated OAuth identity, any caller can set sender to an
# arbitrary value — including reserved names like "system" — to impersonate
# a privileged identity.
#
# Downstream consumers MUST NOT make authorization decisions based on the
# sender field. It is useful only as an informational/display hint.
#
# RESERVED_RELAY_SENDER_NAMES lists names that are semantically reserved and
# SHOULD NOT be used by regular agents. If a well-behaved agent wants to
# include a sender, use the agent's own canonical name (e.g. "ChatbotAgent")
# rather than any name in this set.
# ---------------------------------------------------------------------------

RESERVED_RELAY_SENDER_NAMES: frozenset[str] = frozenset(
    {
        "system",
        "admin",
        "root",
        "relay",
    }
)
# Comparison in validate_relay_sender() is case-insensitive (casefold).
# This frozenset stores lowercase canonical names only; do not add explicit
# case variants — they are unnecessary with casefold comparison.

# Service identifiers
SERVICE_NAME_SLACK_ADAPTER = "slack-adapter"
SERVICE_NAME_TASK_NOTIFIER = "task-notifier"

# ---------------------------------------------------------------------------
# Tool group constants
#
# Named groups of MCP tools for composing agent allowlists. Agents combine
# these groups instead of maintaining raw string lists independently.
# ---------------------------------------------------------------------------

MEMORY_TOOLS = [
    "get_memories",
    "save_memory",
    "search_memories",
]

RAG_TOOLS = [
    "add_document",
    "delete_document",
    "get_document",
    "get_rag_stats",
    "list_documents",
    "search_documents",
]

CONTENT_TOOLS = [
    "analyze_website",
    "fetch_web_content",
    "get_social_media_stats",
    "suggest_content_topics",
]

COMMUNICATION_TOOLS = [
    "send_slack_message",
]

SMS_TOOLS = [
    "send_sms_to_admin",
    "get_sms_status",
]

EMAIL_TOOLS = [
    "send_agent_report",
]

# Full FastMail email tools for agents that need complete email access
FASTMAIL_TOOLS = [
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

CLAUDE_CODE_TOOLS = [
    "run_claude_code",
    "list_claude_code_workspaces",
    "create_claude_code_workspace",
    "delete_claude_code_workspace",
    "get_claude_code_workspace_status",
]

HTTP_CLIENT_TOOLS = [
    "http_request",
    "http_session_login",
    "http_upload_file",
    "http_inspect_headers",
    "http_fuzz_parameter",
    "http_check_rate_limit",
    "http_clear_session",
]

FILESYSTEM_TOOLS = [
    "read_file",
    "list_directory",
    "glob_files",
    "grep_files",
]

WEB_RESEARCH_TOOLS = [
    "fetch_web_content",
    "analyze_website",
]

BROWSER_TESTING_TOOLS = [
    "browser_screenshot",
    "browser_accessibility_audit",
    "browser_performance_audit",
    "browser_console_errors",
    "browser_check_links",
    "browser_crawl_site",
]

NETWORK_ADMIN_TOOLS = [
    "network_discover_hosts",
    "network_scan_ports",
    "network_check_tls",
    "network_grab_banners",
    "network_check_dns",
    "system_get_info",
    "system_check_ssh_config",
    "system_check_file_permissions",
    "system_check_firewall",
    "network_check_default_credentials",
    "network_generate_report",
]

DELEGATION_TOOLS = [
    "request_agent",
]

# ---------------------------------------------------------------------------
# Model aliases
#
# Canonical mapping of short model names to full Anthropic model IDs.
# Use resolve_model() to convert short names before calling the API.
# ---------------------------------------------------------------------------

# Short name -> full Anthropic model ID mapping
MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# All recognized model identifiers (short names + full IDs)
KNOWN_MODELS: frozenset[str] = frozenset(set(MODEL_ALIASES.keys()) | set(MODEL_ALIASES.values()))


def resolve_model(model: str) -> str:
    """Resolve a short model name to a full Anthropic API model ID.

    Passes through full model IDs unchanged. Short names (haiku, sonnet, opus)
    are mapped to their canonical full IDs.

    Args:
        model: Short model name (e.g. "haiku") or full model ID.

    Returns:
        Full Anthropic model ID string.
    """
    return MODEL_ALIASES.get(model, model)


def validate_relay_sender(sender: str) -> str:
    """Check whether a relay sender value is safe to use and return it.

    This performs a best-effort check to prevent well-behaved agents from
    accidentally using reserved names that could be misread as authoritative
    system identities. It does NOT provide security guarantees — the relay
    server cannot authenticate the sender field, so callers must never
    rely on it for access-control decisions.

    The sender field is UNTRUSTED and ADVISORY ONLY. Use it only for
    informational display, not for authorization.

    Comparison is case-insensitive and strips leading/trailing whitespace so
    that variants like ``"SYSTEM"``, ``"sYsTeM"``, or ``" system "`` are all
    rejected alongside the canonical lowercase form.

    Args:
        sender: The proposed sender name (e.g. an agent's class name).

    Returns:
        The sender string (unchanged, including original casing) if it passes
        validation.

    Raises:
        ValueError: If ``sender`` is empty/whitespace-only, or if its stripped
            casefolded form matches any entry in ``RESERVED_RELAY_SENDER_NAMES``.

    Example:
        # Safe — returns the name unchanged
        validate_relay_sender("ChatbotAgent")

        # All raise ValueError — "system" is reserved regardless of casing
        validate_relay_sender("system")
        validate_relay_sender("SYSTEM")
        validate_relay_sender("sYsTeM")
        validate_relay_sender(" system ")
    """
    stripped = sender.strip()
    if not stripped:
        raise ValueError(
            "Relay sender must not be empty or whitespace-only. "
            "Use your agent's canonical class name (e.g. 'ChatbotAgent')."
        )
    if stripped.casefold() in {n.casefold() for n in RESERVED_RELAY_SENDER_NAMES}:
        raise ValueError(
            f"Relay sender '{sender}' is a reserved name and must not be used by agents. "
            f"Reserved base names: {sorted(RESERVED_RELAY_SENDER_NAMES)}. "
            "Use your agent's own canonical class name instead (e.g. 'ChatbotAgent'). "
            "Note: the sender field is advisory-only and cannot be authenticated by the "
            "relay server — do not use it for authorization decisions."
        )
    return sender
