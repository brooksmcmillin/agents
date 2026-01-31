"""Agent identity for permission tracking.

Provides identity information that propagates through agent chains
to enable auditing and access control decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AgentIdentity:
    """Represents the identity of an agent making a request.

    Identity is immutable and propagates through agent chains to track
    the original caller for auditing and access control.

    Attributes:
        name: The agent's name (e.g., "EmailIntakeAgent", "PRAgent")
        source: How the request originated (e.g., "cli", "api", "email", "agent")
        original_caller: The first agent in the chain (for delegation tracking)
        metadata: Additional context (user_id, session_id, etc.)
        created_at: When this identity was created

    Example:
        # Direct CLI invocation
        identity = AgentIdentity(
            name="PRAgent",
            source="cli",
        )

        # Agent delegating to another agent
        delegated = AgentIdentity(
            name="PRAgent",
            source="agent",
            original_caller="EmailIntakeAgent",
        )
    """

    name: str
    source: str = "unknown"
    original_caller: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def delegate_to(self, agent_name: str) -> AgentIdentity:
        """Create a new identity for delegation to another agent.

        The new identity:
        - Has the new agent's name
        - Has source="agent" to indicate delegation
        - Preserves the original caller for audit trail
        - Inherits metadata from the parent

        Args:
            agent_name: The name of the agent being delegated to

        Returns:
            New AgentIdentity for the delegated agent

        Example:
            # Email intake delegating to PR agent
            intake = AgentIdentity(name="EmailIntakeAgent", source="email")
            pr = intake.delegate_to("PRAgent")
            # pr.original_caller == "EmailIntakeAgent"
        """
        return AgentIdentity(
            name=agent_name,
            source="agent",
            original_caller=self.original_caller or self.name,
            metadata=dict(self.metadata),  # Copy metadata
        )

    def with_metadata(self, **kwargs: Any) -> AgentIdentity:
        """Create a new identity with additional metadata.

        Args:
            **kwargs: Key-value pairs to add to metadata

        Returns:
            New AgentIdentity with updated metadata
        """
        new_metadata = dict(self.metadata)
        new_metadata.update(kwargs)
        return AgentIdentity(
            name=self.name,
            source=self.source,
            original_caller=self.original_caller,
            metadata=new_metadata,
            created_at=self.created_at,
        )

    @property
    def is_delegated(self) -> bool:
        """Check if this identity represents a delegated request.

        Returns:
            True if this agent was called by another agent
        """
        return self.source == "agent" and self.original_caller is not None

    @property
    def root_caller(self) -> str:
        """Get the name of the agent at the root of the delegation chain.

        Returns:
            The original caller's name, or this agent's name if not delegated
        """
        return self.original_caller or self.name

    def __str__(self) -> str:
        """Human-readable representation."""
        if self.is_delegated:
            return f"{self.name} (delegated from {self.original_caller})"
        return f"{self.name} ({self.source})"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization/logging.

        Returns:
            Dict representation of the identity
        """
        return {
            "name": self.name,
            "source": self.source,
            "original_caller": self.original_caller,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentIdentity:
        """Create from dictionary (for deserialization).

        Args:
            data: Dict with identity fields

        Returns:
            AgentIdentity instance
        """
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return cls(
            name=data["name"],
            source=data.get("source", "unknown"),
            original_caller=data.get("original_caller"),
            metadata=data.get("metadata", {}),
            created_at=created_at,
        )
