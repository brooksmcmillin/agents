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
