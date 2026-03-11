"""Load OAuth credentials from Claude Code's credential store.

Claude Code stores MCP OAuth tokens in ~/.claude/.credentials.json. This module
provides a fallback path so headless agents can reuse those tokens instead of
triggering an interactive OAuth flow.
"""

import json
import logging
import time
from pathlib import Path

from ..utils.sanitize import sanitize_log_input
from .oauth_tokens import TokenSet

logger = logging.getLogger(__name__)

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


def load_claude_credential(
    server_url: str,
    credentials_path: Path | None = None,
) -> TokenSet | None:
    """Load a valid OAuth token for *server_url* from Claude Code's credentials.

    Args:
        server_url: The MCP server URL to find credentials for.
        credentials_path: Override path to credentials file (for testing).

    Returns:
        A ``TokenSet`` if a matching, non-expired credential is found, else ``None``.
    """
    path = credentials_path or CREDENTIALS_PATH

    try:
        raw = path.read_text()
    except (OSError, FileNotFoundError):
        logger.debug("Claude auth file not found at %s", sanitize_log_input(str(path)))
        return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Claude auth file is not valid JSON")
        return None

    mcp_oauth: dict = data.get("mcpOAuth", {})
    if not mcp_oauth:
        logger.debug("No mcpOAuth entries in Claude auth file")
        return None

    # Normalize for comparison: strip trailing slashes
    normalized_url = server_url.rstrip("/")

    for entry in mcp_oauth.values():
        entry_url = (entry.get("serverUrl") or "").rstrip("/")
        if entry_url != normalized_url:
            continue

        access_token = entry.get("accessToken")
        if not access_token:
            logger.debug("Auth entry for %s has no access token", sanitize_log_input(server_url))
            return None

        # Check expiry — expiresAt is milliseconds since epoch
        expires_at_ms = entry.get("expiresAt")
        if expires_at_ms is not None:
            now_ms = time.time() * 1000
            if now_ms >= (expires_at_ms - 60_000):  # 60s buffer
                logger.debug("Auth entry for %s is expired", sanitize_log_input(server_url))
                return None

        # Compute expires_in from expiresAt for TokenSet
        expires_in: int | None = None
        if expires_at_ms is not None:
            expires_in = max(1, int((expires_at_ms / 1000) - time.time()))

        logger.info("Loaded Claude Code auth for %s", sanitize_log_input(server_url))
        return TokenSet(
            access_token=access_token,
            refresh_token=entry.get("refreshToken"),
            expires_in=expires_in,
            issued_at=time.time(),
            scope=entry.get("scope"),
            client_id=entry.get("clientId"),
            client_secret=entry.get("clientSecret"),
        )

    logger.debug("No Claude auth entry matching %s", sanitize_log_input(server_url))
    return None
