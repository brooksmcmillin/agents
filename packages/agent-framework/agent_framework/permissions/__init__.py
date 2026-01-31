"""Agent permissions and identity system.

This module provides capability-based security for multi-agent systems:

- AgentIdentity: Identifies who is making a request
- Permission: Granular capabilities (read, write, execute, etc.)
- PermissionSet: Collection of permissions with set operations
- ExecutionContext: Propagates identity and permissions through agent chains

Example usage:
    # Define permissions for different agent roles
    read_only = PermissionSet.read_only()
    full_access = PermissionSet.full_access()

    # Create execution context for email intake agent
    context = ExecutionContext(
        caller=AgentIdentity("EmailIntakeAgent"),
        permissions=read_only,
    )

    # When calling another agent, permissions propagate
    pr_agent = PRAgent()
    response = await pr_agent.process_message(
        "Analyze my website",
        execution_context=context,  # PR agent inherits read_only permissions
    )

Security model:
- Permissions are the INTERSECTION when propagating (most restrictive wins)
- Tools check permissions at execution time via TOOL_PERMISSIONS mapping
- Unknown tools default to requiring Permission.ADMIN (fail-safe)
"""

from .context import ExecutionContext
from .identity import AgentIdentity
from .permissions import Permission, PermissionSet
from .tool_permissions import TOOL_PERMISSIONS, get_required_permissions

__all__ = [
    "AgentIdentity",
    "ExecutionContext",
    "Permission",
    "PermissionSet",
    "TOOL_PERMISSIONS",
    "get_required_permissions",
]
