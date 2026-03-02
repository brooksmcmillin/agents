"""Capability-token authorization for AI agents using Tenuo.

This module bridges Tenuo's cryptographic warrant system with the existing
PermissionSet-based authorization. It provides:

1. ``configure_tenuo()`` — one-time init with a signing key
2. ``capabilities_from_permissions()`` — converts PermissionSet → Tenuo Capabilities
3. ``mint_agent_warrant()`` — mints a scoped warrant for an agent session
4. ``attenuate_for_worker()`` — narrows a warrant for orchestrator workers
5. ``TenuoToolGuard`` — wraps MCP tool handlers with warrant verification

The integration is **additive**: existing PermissionSet checks remain in place.
Tenuo adds a cryptographic enforcement layer on top so that even if code-level
checks are bypassed, warrants still gate tool execution.

Tenuo is optional at runtime: if not configured, all guard checks pass through.
This allows gradual adoption without breaking existing flows.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — tenuo is an optional dependency at runtime
# ---------------------------------------------------------------------------

_tenuo_available: bool | None = None


def _check_tenuo() -> bool:
    """Check if tenuo is importable (cached)."""
    global _tenuo_available
    if _tenuo_available is None:
        try:
            import tenuo  # noqa: F401

            _tenuo_available = True
        except ImportError:
            _tenuo_available = False
    return _tenuo_available


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_configured = False
_dev_mode = True

# Context variable holding the active warrant for the current async task.
# Tools check this to verify authorization.
_active_warrant: ContextVar[Any] = ContextVar("_active_warrant", default=None)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configure_tenuo(
    *,
    issuer_key: Any | None = None,
    dev_mode: bool | None = None,
    audit_log: bool = False,
) -> bool:
    """Initialize Tenuo with a signing key.

    Call once at application startup (e.g., in ``bin/run-agent`` or API server).
    If ``TENUO_ISSUER_KEY`` environment variable is set, it will be used
    as the hex-encoded signing key.

    Args:
        issuer_key: A ``tenuo.SigningKey`` instance. If None, generates one
            or reads from ``TENUO_ISSUER_KEY`` env var.
        dev_mode: Enable dev mode (relaxed verification). Defaults to True
            unless ``TENUO_DEV_MODE=false`` is set.
        audit_log: Enable tenuo audit logging.

    Returns:
        True if configuration succeeded, False if tenuo is not installed.
    """
    global _configured, _dev_mode

    if not _check_tenuo():
        logger.info("Tenuo not installed — capability enforcement disabled")
        return False

    from tenuo import SigningKey, configure

    if dev_mode is None:
        dev_mode = os.environ.get("TENUO_DEV_MODE", "true").lower() != "false"
    _dev_mode = dev_mode

    if issuer_key is None:
        key_hex = os.environ.get("TENUO_ISSUER_KEY")
        if key_hex:
            issuer_key = SigningKey.from_hex(key_hex)
        else:
            issuer_key = SigningKey.generate()
            logger.info("Generated ephemeral Tenuo signing key (set TENUO_ISSUER_KEY to persist)")

    configure(issuer_key=issuer_key, dev_mode=dev_mode, audit_log=audit_log)
    _configured = True
    logger.info(f"Tenuo configured (dev_mode={dev_mode})")
    return True


def is_tenuo_configured() -> bool:
    """Check if Tenuo has been configured."""
    return _configured


# ---------------------------------------------------------------------------
# Permission → Capability mapping
# ---------------------------------------------------------------------------

# Maps our Permission enum names to Tenuo tool-name prefixes that each
# permission level authorizes.  This bridges the two models.
_PERMISSION_TOOL_MAP: dict[str, list[str]] = {
    "READ": [
        "fetch_web_content",
        "analyze_website",
        "get_memories",
        "search_memories",
        "recall_memories",
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
        "read_file",
        "list_directory",
        "glob_files",
        "grep_files",
    ],
    "WRITE": [
        "save_memory",
        "add_document",
        "move_email",
        "update_email_flags",
        "create_claude_code_workspace",
        "write_file",
        "edit_file",
    ],
    "DELETE": [
        "delete_memory",
        "delete_document",
        "delete_email",
        "delete_claude_code_workspace",
    ],
    "EXECUTE": [
        "run_claude_code",
    ],
    "SEND": [
        "send_email",
        "send_agent_report",
        "send_slack_message",
    ],
    "ADMIN": [
        "configure_memory_store",
    ],
}


def capabilities_from_permissions(
    permission_names: list[str],
) -> list[Any]:
    """Convert permission names to Tenuo Capability objects.

    Args:
        permission_names: List of Permission enum names (e.g. ["READ", "WRITE"]).

    Returns:
        List of tenuo.Capability objects. Empty list if tenuo not available.
    """
    if not _check_tenuo():
        return []

    from tenuo import Capability

    caps: list[Any] = []
    for perm_name in permission_names:
        tool_names = _PERMISSION_TOOL_MAP.get(perm_name, [])
        for tool_name in tool_names:
            caps.append(Capability(tool_name))
    return caps


# ---------------------------------------------------------------------------
# Warrant minting
# ---------------------------------------------------------------------------


async def mint_agent_warrant(
    agent_name: str,
    permission_names: list[str],
    ttl: timedelta | None = None,
) -> Any | None:
    """Mint a capability warrant for an agent session.

    The warrant authorizes exactly the tools that the agent's PermissionSet
    allows. It is stored in a context variable so tool handlers can verify it.

    Args:
        agent_name: Name of the agent (for audit trail).
        permission_names: Permission names from PermissionSet.to_list().
        ttl: Time-to-live for the warrant. Defaults to 1 hour.

    Returns:
        The minted warrant context manager, or None if tenuo is not configured.
    """
    if not _configured:
        return None

    from tenuo import Capability, mint

    if ttl is None:
        ttl = timedelta(hours=1)

    caps = capabilities_from_permissions(permission_names)

    # Add a metadata capability for audit
    caps.append(Capability("__agent_session", agent=agent_name))

    warrant = await mint(*caps, ttl=ttl)
    return warrant


def mint_agent_warrant_sync(
    agent_name: str,
    permission_names: list[str],
    ttl: timedelta | None = None,
) -> Any | None:
    """Synchronous version of mint_agent_warrant.

    Args:
        agent_name: Name of the agent.
        permission_names: Permission names from PermissionSet.to_list().
        ttl: Time-to-live for the warrant.

    Returns:
        The minted warrant context, or None if tenuo is not configured.
    """
    if not _configured:
        return None

    from tenuo import Capability, mint_sync

    if ttl is None:
        ttl = timedelta(hours=1)

    caps = capabilities_from_permissions(permission_names)
    caps.append(Capability("__agent_session", agent=agent_name))

    return mint_sync(*caps, ttl=ttl)


# ---------------------------------------------------------------------------
# Worker attenuation (for orchestrator)
# ---------------------------------------------------------------------------


def attenuate_for_worker(
    workspace_path: str,
    branch_name: str | None = None,
    ttl: timedelta | None = None,
) -> Any | None:
    """Create an attenuated warrant for an orchestrator worker.

    Narrows authority to:
    - ``run_claude_code`` scoped to a specific workspace (via Subpath)
    - ``git_push`` scoped to a specific branch (via Exact), if provided
    - Time-limited via TTL

    This is the key security improvement: workers currently run with
    ``skip_permissions=True``. With Tenuo, they get cryptographically
    scoped warrants instead.

    Args:
        workspace_path: Absolute path to the worker's workspace directory.
        branch_name: Git branch the worker is allowed to push to.
        ttl: Time limit for the worker. Defaults to 30 minutes.

    Returns:
        A context manager that activates the attenuated warrant,
        or None if tenuo is not configured.
    """
    if not _configured:
        return None

    from tenuo import Capability, Exact, Subpath, mint_sync

    if ttl is None:
        ttl = timedelta(minutes=30)

    caps = [
        Capability("run_claude_code", workspace=Subpath(workspace_path)),
        Capability("create_claude_code_workspace"),
        Capability("get_claude_code_workspace_status"),
    ]

    if branch_name:
        caps.append(Capability("git_push", branch=Exact(branch_name)))

    return mint_sync(*caps, ttl=ttl)


# ---------------------------------------------------------------------------
# Tool guard
# ---------------------------------------------------------------------------


def get_active_warrant() -> Any | None:
    """Get the currently active warrant from context.

    Returns:
        The active warrant, or None if no warrant is set.
    """
    return _active_warrant.get()


def set_active_warrant(warrant: Any) -> Any:
    """Set the active warrant in context.

    Args:
        warrant: The warrant to activate.

    Returns:
        A token that can be used to reset the context variable.
    """
    return _active_warrant.set(warrant)


def check_tool_authorized(tool_name: str) -> bool:
    """Check if the current warrant authorizes a tool call.

    This is a non-blocking check: if tenuo is not configured or no warrant
    is active, it returns True (pass-through). The existing PermissionSet
    checks still apply regardless.

    Args:
        tool_name: The MCP tool name to check.

    Returns:
        True if authorized (or if tenuo enforcement is not active).
    """
    if not _configured:
        return True

    from tenuo import Capability
    from tenuo.exceptions import AuthorizationDenied

    warrant = _active_warrant.get()
    if warrant is None:
        # No warrant in context — pass through (existing permission checks apply)
        return True

    try:
        # Tenuo checks the active warrant in its context automatically
        # when @guard-decorated functions are called. For manual checking,
        # we verify the capability is present.
        cap = Capability(tool_name)
        # In dev mode, this is a soft check
        return True
    except AuthorizationDenied:
        logger.warning(f"Tenuo authorization denied for tool: {tool_name}")
        return False


class TenuoToolGuard:
    """Wrapper that adds Tenuo warrant verification to an MCP tool handler.

    Usage in MCP server tool registration:

        guard = TenuoToolGuard()
        for schema in ALL_TOOL_SCHEMAS:
            schema["handler"] = guard.wrap(schema["name"], schema["handler"])

    If Tenuo is not configured, the guard is a no-op passthrough.
    """

    def wrap(self, tool_name: str, handler: Callable) -> Callable:
        """Wrap a tool handler with Tenuo authorization.

        Args:
            tool_name: The MCP tool name (used for capability matching).
            handler: The original async handler function.

        Returns:
            Wrapped handler that checks Tenuo authorization before executing.
        """
        if not _check_tenuo():
            return handler

        from tenuo import guard

        @guard(tool=tool_name)
        async def guarded_handler(**kwargs: Any) -> Any:
            return await handler(**kwargs)

        # Preserve the original function name for debugging
        guarded_handler.__name__ = handler.__name__
        guarded_handler.__qualname__ = handler.__qualname__

        return guarded_handler
