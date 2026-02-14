"""Tests for ExecutionContext permission propagation."""

import pytest

from agent_framework.permissions.context import ExecutionContext
from agent_framework.permissions.identity import AgentIdentity
from agent_framework.permissions.permissions import Permission, PermissionSet


class TestExecutionContextFactories:
    """Tests for ExecutionContext class factory methods."""

    def test_default_creates_full_access(self) -> None:
        ctx = ExecutionContext.default("TestAgent")
        assert ctx.caller.name == "TestAgent"
        assert ctx.caller.source == "cli"
        assert ctx.permissions.has(Permission.READ)
        assert ctx.permissions.has(Permission.WRITE)
        assert ctx.permissions.has(Permission.DELETE)
        assert ctx.permissions.has(Permission.EXECUTE)
        assert ctx.permissions.has(Permission.SEND)
        assert not ctx.permissions.has(Permission.ADMIN)

    def test_default_custom_source(self) -> None:
        ctx = ExecutionContext.default("TestAgent", source="webhook")
        assert ctx.caller.source == "webhook"

    def test_cli_creates_admin(self) -> None:
        ctx = ExecutionContext.cli("CLIAgent")
        assert ctx.caller.name == "CLIAgent"
        assert ctx.caller.source == "cli"
        assert ctx.permissions.has(Permission.ADMIN)
        assert ctx.permissions.has(Permission.READ)
        assert ctx.permissions.has(Permission.WRITE)

    def test_api_creates_standard(self) -> None:
        ctx = ExecutionContext.api("APIAgent")
        assert ctx.caller.name == "APIAgent"
        assert ctx.caller.source == "api"
        assert ctx.permissions.has(Permission.READ)
        assert ctx.permissions.has(Permission.WRITE)
        assert ctx.permissions.has(Permission.SEND)
        assert not ctx.permissions.has(Permission.DELETE)
        assert not ctx.permissions.has(Permission.ADMIN)

    def test_api_custom_permissions(self) -> None:
        perms = PermissionSet.read_only()
        ctx = ExecutionContext.api("APIAgent", permissions=perms)
        assert ctx.permissions.has(Permission.READ)
        assert not ctx.permissions.has(Permission.WRITE)


class TestDelegation:
    """Tests for permission delegation through agent chains."""

    def test_delegate_to_without_agent_permissions(self) -> None:
        """Delegating without agent_permissions inherits caller's permissions."""
        parent = ExecutionContext.cli("ParentAgent")
        child = parent.delegate_to("ChildAgent")

        assert child.caller.name == "ChildAgent"
        assert child.caller.source == "agent"
        assert child.parent is parent
        assert child.permissions == parent.permissions

    def test_delegate_to_with_permission_intersection(self) -> None:
        """Delegating with agent_permissions uses intersection."""
        parent = ExecutionContext(
            caller=AgentIdentity(name="EmailIntake", source="email"),
            permissions=PermissionSet.read_only(),
        )
        child = parent.delegate_to(
            "PRAgent",
            agent_permissions=PermissionSet.full_access(),
        )

        # Intersection of read_only and full_access = read_only
        assert child.permissions.has(Permission.READ)
        assert not child.permissions.has(Permission.WRITE)
        assert not child.permissions.has(Permission.DELETE)

    def test_delegate_cannot_escalate_permissions(self) -> None:
        """Agents can't gain MORE permissions through delegation."""
        restricted = ExecutionContext(
            caller=AgentIdentity(name="Restricted", source="api"),
            permissions=PermissionSet([Permission.READ]),
        )
        delegated = restricted.delegate_to(
            "PrivilegedAgent",
            agent_permissions=PermissionSet.admin(),
        )

        # Even though agent has admin, delegation should only give READ
        assert delegated.permissions.has(Permission.READ)
        assert not delegated.permissions.has(Permission.ADMIN)
        assert not delegated.permissions.has(Permission.WRITE)

    def test_delegate_preserves_metadata(self) -> None:
        parent = ExecutionContext(
            caller=AgentIdentity(name="Parent", source="cli"),
            permissions=PermissionSet.full_access(),
            metadata={"session_id": "abc123"},
        )
        child = parent.delegate_to("Child")

        assert child.metadata == {"session_id": "abc123"}
        # Metadata should be a copy, not a reference
        child.metadata["extra"] = "value"
        assert "extra" not in parent.metadata

    def test_delegate_chain_tracking(self) -> None:
        root = ExecutionContext.cli("Root")
        mid = root.delegate_to("Middle")
        leaf = mid.delegate_to("Leaf")

        assert leaf.parent is mid
        assert mid.parent is root
        assert root.parent is None


class TestPermissionChecks:
    """Tests for can() and require() methods."""

    def test_can_returns_true_for_present_permission(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        assert ctx.can(Permission.READ) is True
        assert ctx.can(Permission.ADMIN) is True

    def test_can_returns_false_for_missing_permission(self) -> None:
        ctx = ExecutionContext(
            caller=AgentIdentity(name="Limited", source="api"),
            permissions=PermissionSet.read_only(),
        )
        assert ctx.can(Permission.READ) is True
        assert ctx.can(Permission.WRITE) is False

    def test_require_passes_with_all_permissions(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        # Should not raise
        ctx.require(Permission.READ, Permission.WRITE, Permission.ADMIN)

    def test_require_raises_for_missing_permission(self) -> None:
        ctx = ExecutionContext(
            caller=AgentIdentity(name="ReadOnly", source="api"),
            permissions=PermissionSet.read_only(),
        )
        with pytest.raises(PermissionError, match="ReadOnly lacks required permissions"):
            ctx.require(Permission.READ, Permission.WRITE)

    def test_require_error_lists_missing_permissions(self) -> None:
        ctx = ExecutionContext(
            caller=AgentIdentity(name="Agent", source="api"),
            permissions=PermissionSet.read_only(),
        )
        with pytest.raises(PermissionError) as exc_info:
            ctx.require(Permission.WRITE, Permission.DELETE)
        assert "WRITE" in str(exc_info.value)
        assert "DELETE" in str(exc_info.value)


class TestMetadata:
    """Tests for with_metadata()."""

    def test_with_metadata_creates_new_context(self) -> None:
        original = ExecutionContext.cli("Agent")
        updated = original.with_metadata(request_id="req-1")

        assert updated.metadata == {"request_id": "req-1"}
        assert original.metadata == {}
        assert updated is not original

    def test_with_metadata_preserves_other_fields(self) -> None:
        original = ExecutionContext.cli("Agent")
        updated = original.with_metadata(key="value")

        assert updated.caller == original.caller
        assert updated.permissions == original.permissions
        assert updated.parent == original.parent

    def test_with_metadata_merges(self) -> None:
        ctx = ExecutionContext(
            caller=AgentIdentity(name="Agent", source="cli"),
            permissions=PermissionSet.full_access(),
            metadata={"existing": "data"},
        )
        updated = ctx.with_metadata(new_key="new_val")

        assert updated.metadata == {"existing": "data", "new_key": "new_val"}


class TestChainTracking:
    """Tests for get_chain() and get_chain_summary()."""

    def test_get_chain_single_context(self) -> None:
        ctx = ExecutionContext.cli("Solo")
        chain = ctx.get_chain()

        assert len(chain) == 1
        assert chain[0] is ctx

    def test_get_chain_delegation(self) -> None:
        root = ExecutionContext.cli("Root")
        child = root.delegate_to("Child")
        grandchild = child.delegate_to("Grandchild")

        chain = grandchild.get_chain()

        assert len(chain) == 3
        assert chain[0] is root
        assert chain[1] is child
        assert chain[2] is grandchild

    def test_get_chain_summary_single(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        summary = ctx.get_chain_summary()

        assert "Agent" in summary
        assert "cli" in summary

    def test_get_chain_summary_delegation(self) -> None:
        root = ExecutionContext(
            caller=AgentIdentity(name="EmailIntake", source="email"),
            permissions=PermissionSet.read_only(),
        )
        child = root.delegate_to("PRAgent")

        summary = child.get_chain_summary()
        assert "EmailIntake" in summary
        assert "PRAgent" in summary
        assert "->" in summary


class TestProperties:
    """Tests for is_delegated and root_caller properties."""

    def test_is_delegated_false_for_direct(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        assert ctx.is_delegated is False

    def test_is_delegated_true_for_delegation(self) -> None:
        root = ExecutionContext.cli("Root")
        child = root.delegate_to("Child")
        assert child.is_delegated is True

    def test_root_caller_direct(self) -> None:
        ctx = ExecutionContext.cli("MyAgent")
        assert ctx.root_caller == "MyAgent"

    def test_root_caller_delegated(self) -> None:
        root = ExecutionContext.cli("OriginalCaller")
        child = root.delegate_to("Delegate")
        assert child.root_caller == "OriginalCaller"


class TestSerialization:
    """Tests for to_dict()."""

    def test_to_dict_basic(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        d = ctx.to_dict()

        assert d["caller"]["name"] == "Agent"
        assert d["caller"]["source"] == "cli"
        assert isinstance(d["permissions"], list)
        assert "ADMIN" in d["permissions"]
        assert d["is_delegated"] is False
        assert d["root_caller"] == "Agent"
        assert "Agent" in d["chain"]
        assert isinstance(d["metadata"], dict)

    def test_to_dict_delegated(self) -> None:
        root = ExecutionContext.cli("Root")
        child = root.delegate_to("Child")
        d = child.to_dict()

        assert d["caller"]["name"] == "Child"
        assert d["is_delegated"] is True
        assert d["root_caller"] == "Root"
        assert "Root" in d["chain"]
        assert "Child" in d["chain"]

    def test_to_dict_with_metadata(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        ctx = ctx.with_metadata(session="abc")
        d = ctx.to_dict()

        assert d["metadata"] == {"session": "abc"}


class TestStr:
    """Tests for __str__ representation."""

    def test_str_includes_caller_and_permissions(self) -> None:
        ctx = ExecutionContext.cli("Agent")
        s = str(ctx)
        assert "ExecutionContext" in s
        assert "Agent" in s
