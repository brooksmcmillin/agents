"""Permission definitions and permission sets.

Provides granular capabilities that can be combined into permission sets
for different agent roles.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class Permission(Enum):
    """Individual permissions that can be granted to agents.

    Permissions are organized hierarchically:
    - READ: View/fetch data without modification
    - WRITE: Create or modify data
    - DELETE: Remove data
    - EXECUTE: Run external commands or code
    - SEND: Send communications (email, slack, etc.)
    - ADMIN: Full system access (required for unknown tools)

    Example:
        # Check if an agent can read web content
        if Permission.READ in agent_permissions:
            result = await fetch_web_content(url)
    """

    # Data access
    READ = auto()  # Read/fetch data
    WRITE = auto()  # Create or modify data
    DELETE = auto()  # Remove data

    # External interactions
    EXECUTE = auto()  # Run code/commands (Claude Code)
    SEND = auto()  # Send messages (email, slack)

    # Full access
    ADMIN = auto()  # Unrestricted access


class PermissionSet:
    """A collection of permissions with set operations.

    Provides factory methods for common permission profiles and
    supports intersection operations for permission propagation.

    Example:
        # Create a read-only permission set
        read_only = PermissionSet.read_only()

        # Check permissions
        if read_only.has(Permission.READ):
            print("Can read!")

        # Intersection (used when propagating through agent chains)
        restricted = full_access.intersection(read_only)
        # restricted now only has READ permission
    """

    def __init__(self, permissions: Iterable[Permission] | None = None):
        """Initialize with a collection of permissions.

        Args:
            permissions: Iterable of Permission enum values.
                If None, creates an empty permission set.
        """
        self._permissions: frozenset[Permission] = (
            frozenset(permissions) if permissions else frozenset()
        )

    @classmethod
    def empty(cls) -> PermissionSet:
        """Create a permission set with no permissions.

        Returns:
            Empty PermissionSet
        """
        return cls()

    @classmethod
    def read_only(cls) -> PermissionSet:
        """Create a read-only permission set.

        Allows:
        - Fetching web content
        - Reading memories
        - Searching documents
        - Analyzing websites

        Does NOT allow:
        - Writing/modifying data
        - Sending emails or messages
        - Executing code
        - Deleting anything

        Returns:
            PermissionSet with only READ permission
        """
        return cls([Permission.READ])

    @classmethod
    def read_write(cls) -> PermissionSet:
        """Create a read-write permission set.

        Allows everything in read_only plus:
        - Saving memories
        - Adding documents
        - Modifying data

        Does NOT allow:
        - Sending communications
        - Executing code
        - Deleting data

        Returns:
            PermissionSet with READ and WRITE permissions
        """
        return cls([Permission.READ, Permission.WRITE])

    @classmethod
    def standard(cls) -> PermissionSet:
        """Create a standard permission set for interactive agents.

        Allows:
        - All read/write operations
        - Sending emails and messages

        Does NOT allow:
        - Executing code (Claude Code)
        - Deleting data
        - Admin operations

        Returns:
            PermissionSet with READ, WRITE, SEND permissions
        """
        return cls([Permission.READ, Permission.WRITE, Permission.SEND])

    @classmethod
    def full_access(cls) -> PermissionSet:
        """Create a permission set with all permissions except ADMIN.

        Allows:
        - All read/write/delete operations
        - Sending communications
        - Executing code

        Does NOT include ADMIN (which is reserved for system operations
        and unknown tools).

        Returns:
            PermissionSet with all permissions except ADMIN
        """
        return cls([Permission.READ, Permission.WRITE, Permission.DELETE,
                    Permission.EXECUTE, Permission.SEND])

    @classmethod
    def admin(cls) -> PermissionSet:
        """Create a permission set with all permissions including ADMIN.

        This should only be used for:
        - Direct CLI invocation
        - System administration tasks
        - Testing

        Returns:
            PermissionSet with all permissions
        """
        return cls(list(Permission))

    def has(self, permission: Permission) -> bool:
        """Check if this set includes a specific permission.

        Args:
            permission: The permission to check

        Returns:
            True if the permission is in this set
        """
        return permission in self._permissions

    def has_all(self, permissions: Iterable[Permission]) -> bool:
        """Check if this set includes all specified permissions.

        Args:
            permissions: The permissions to check

        Returns:
            True if ALL permissions are in this set
        """
        return all(p in self._permissions for p in permissions)

    def has_any(self, permissions: Iterable[Permission]) -> bool:
        """Check if this set includes any of the specified permissions.

        Args:
            permissions: The permissions to check

        Returns:
            True if ANY permission is in this set
        """
        return any(p in self._permissions for p in permissions)

    def intersection(self, other: PermissionSet) -> PermissionSet:
        """Return the intersection of two permission sets.

        Used when propagating permissions through agent chains.
        The result contains only permissions present in BOTH sets.

        Args:
            other: Another PermissionSet

        Returns:
            New PermissionSet with common permissions

        Example:
            full = PermissionSet.full_access()
            readonly = PermissionSet.read_only()
            result = full.intersection(readonly)
            # result only has READ permission
        """
        return PermissionSet(self._permissions & other._permissions)

    def union(self, other: PermissionSet) -> PermissionSet:
        """Return the union of two permission sets.

        Args:
            other: Another PermissionSet

        Returns:
            New PermissionSet with all permissions from both sets
        """
        return PermissionSet(self._permissions | other._permissions)

    def __contains__(self, permission: Permission) -> bool:
        """Support 'in' operator: if Permission.READ in permission_set."""
        return permission in self._permissions

    def __iter__(self):
        """Iterate over permissions in this set."""
        return iter(self._permissions)

    def __len__(self) -> int:
        """Return the number of permissions in this set."""
        return len(self._permissions)

    def __eq__(self, other: object) -> bool:
        """Check equality with another PermissionSet."""
        if not isinstance(other, PermissionSet):
            return NotImplemented
        return self._permissions == other._permissions

    def __repr__(self) -> str:
        """Return string representation."""
        perms = sorted(p.name for p in self._permissions)
        return f"PermissionSet({{{', '.join(perms)}}})"

    def to_list(self) -> list[str]:
        """Convert to a list of permission names (for serialization).

        Returns:
            List of permission names as strings
        """
        return sorted(p.name for p in self._permissions)

    @classmethod
    def from_list(cls, names: list[str]) -> PermissionSet:
        """Create from a list of permission names (for deserialization).

        Args:
            names: List of permission names as strings

        Returns:
            PermissionSet with the specified permissions

        Raises:
            ValueError: If any name is not a valid Permission
        """
        permissions = []
        for name in names:
            try:
                permissions.append(Permission[name])
            except KeyError:
                raise ValueError(f"Unknown permission: {name}") from None
        return cls(permissions)
