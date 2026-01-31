"""Execution context for permission propagation.

The ExecutionContext carries identity and permissions through agent chains,
ensuring that delegated agents inherit appropriate restrictions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .identity import AgentIdentity
from .permissions import Permission, PermissionSet

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Context that propagates identity and permissions through agent chains.

    When an agent delegates work to another agent, the ExecutionContext ensures:
    1. The caller's identity is tracked for auditing
    2. Permissions are restricted (intersection of caller and callee permissions)
    3. Metadata propagates through the chain

    Attributes:
        caller: Identity of the agent making the request
        permissions: What operations are allowed
        parent: The context this was derived from (for chain tracking)
        metadata: Additional context data

    Example:
        # Email intake agent with read-only permissions
        intake_context = ExecutionContext(
            caller=AgentIdentity(name="EmailIntakeAgent", source="email"),
            permissions=PermissionSet.read_only(),
        )

        # When delegating to PR agent, permissions are intersected
        pr_context = intake_context.delegate_to(
            agent_name="PRAgent",
            agent_permissions=PermissionSet.full_access(),
        )
        # pr_context has only READ permission (intersection)
    """

    caller: AgentIdentity
    permissions: PermissionSet
    parent: ExecutionContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def default(cls, agent_name: str, source: str = "cli") -> ExecutionContext:
        """Create a default context for direct agent invocation.

        Used when an agent is invoked directly (CLI, API) rather than
        through delegation. Grants full access permissions.

        Args:
            agent_name: Name of the agent being invoked
            source: How the agent was invoked (cli, api, etc.)

        Returns:
            ExecutionContext with full access permissions
        """
        return cls(
            caller=AgentIdentity(name=agent_name, source=source),
            permissions=PermissionSet.full_access(),
        )

    @classmethod
    def cli(cls, agent_name: str) -> ExecutionContext:
        """Create context for CLI invocation with admin permissions.

        CLI users are trusted and get admin access by default.

        Args:
            agent_name: Name of the agent

        Returns:
            ExecutionContext with admin permissions
        """
        return cls(
            caller=AgentIdentity(name=agent_name, source="cli"),
            permissions=PermissionSet.admin(),
        )

    @classmethod
    def api(cls, agent_name: str, permissions: PermissionSet | None = None) -> ExecutionContext:
        """Create context for API invocation.

        API calls can have restricted permissions based on authentication.

        Args:
            agent_name: Name of the agent
            permissions: Permission set for this API call (defaults to standard)

        Returns:
            ExecutionContext for API invocation
        """
        return cls(
            caller=AgentIdentity(name=agent_name, source="api"),
            permissions=permissions or PermissionSet.standard(),
        )

    def delegate_to(
        self,
        agent_name: str,
        agent_permissions: PermissionSet | None = None,
    ) -> ExecutionContext:
        """Create a new context for delegating to another agent.

        The new context:
        - Has the delegated agent's identity
        - Has permissions = intersection(caller, agent)
        - References this context as parent for chain tracking

        This ensures agents can't gain MORE permissions through delegation.

        Args:
            agent_name: Name of the agent being delegated to
            agent_permissions: The agent's own permission set (optional).
                If provided, the resulting permissions are the intersection
                of the caller's permissions and the agent's permissions.

        Returns:
            New ExecutionContext for the delegated agent

        Example:
            # Email intake (read-only) delegating to PR agent (full access)
            pr_context = intake_context.delegate_to(
                "PRAgent",
                agent_permissions=PermissionSet.full_access(),
            )
            # PR agent can only READ because intake was read-only
        """
        # Calculate effective permissions
        if agent_permissions is not None:
            effective_permissions = self.permissions.intersection(agent_permissions)
            logger.debug(
                f"Permission intersection: {self.permissions} & {agent_permissions} "
                f"= {effective_permissions}"
            )
        else:
            effective_permissions = self.permissions

        # Create delegated identity
        delegated_identity = self.caller.delegate_to(agent_name)

        # Create new context with parent reference
        new_context = ExecutionContext(
            caller=delegated_identity,
            permissions=effective_permissions,
            parent=self,
            metadata=dict(self.metadata),  # Inherit metadata
        )

        logger.info(
            f"Delegating from {self.caller.name} to {agent_name} "
            f"with permissions: {effective_permissions}"
        )

        return new_context

    def can(self, permission: Permission) -> bool:
        """Check if this context allows a specific permission.

        Args:
            permission: The permission to check

        Returns:
            True if the permission is allowed
        """
        return self.permissions.has(permission)

    def require(self, *permissions: Permission) -> None:
        """Require that all specified permissions are present.

        Args:
            *permissions: Permissions that must be present

        Raises:
            PermissionError: If any required permission is missing
        """
        missing = [p for p in permissions if not self.can(p)]
        if missing:
            missing_names = [p.name for p in missing]
            raise PermissionError(
                f"Permission denied: {self.caller.name} lacks required permissions: "
                f"{', '.join(missing_names)}"
            )

    def with_metadata(self, **kwargs: Any) -> ExecutionContext:
        """Create a new context with additional metadata.

        Args:
            **kwargs: Metadata to add

        Returns:
            New ExecutionContext with updated metadata
        """
        new_metadata = dict(self.metadata)
        new_metadata.update(kwargs)
        return ExecutionContext(
            caller=self.caller,
            permissions=self.permissions,
            parent=self.parent,
            metadata=new_metadata,
        )

    def get_chain(self) -> list[ExecutionContext]:
        """Get the full delegation chain from root to current.

        Returns:
            List of ExecutionContext from oldest ancestor to self
        """
        chain = []
        current: ExecutionContext | None = self
        while current is not None:
            chain.append(current)
            current = current.parent
        return list(reversed(chain))

    def get_chain_summary(self) -> str:
        """Get a human-readable summary of the delegation chain.

        Returns:
            String showing the delegation chain

        Example:
            "EmailIntakeAgent(email) -> PRAgent(agent)"
        """
        chain = self.get_chain()
        parts = [str(ctx.caller) for ctx in chain]
        return " -> ".join(parts)

    @property
    def is_delegated(self) -> bool:
        """Check if this context represents a delegated request.

        Returns:
            True if this agent was called by another agent
        """
        return self.caller.is_delegated

    @property
    def root_caller(self) -> str:
        """Get the name of the original caller in the chain.

        Returns:
            Name of the agent that started the chain
        """
        return self.caller.root_caller

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization/logging.

        Returns:
            Dict representation (excludes parent to avoid recursion)
        """
        return {
            "caller": self.caller.to_dict(),
            "permissions": self.permissions.to_list(),
            "is_delegated": self.is_delegated,
            "root_caller": self.root_caller,
            "chain": self.get_chain_summary(),
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"ExecutionContext({self.caller}, permissions={self.permissions})"
