"""Factory function for creating simple agent classes.

This module provides utilities to eliminate boilerplate when creating
agents that only differ in their prompts and tool configurations.
"""

from typing import Any

from agent_framework import Agent, PermissionSet


def create_simple_agent(
    name: str,
    system_prompt: str,
    greeting: str,
    allowed_tools: list[str] | None = None,
    permissions: PermissionSet | None = None,
    enable_delegation: bool = False,
) -> type[Agent]:
    """Factory function for creating simple agent classes.

    This eliminates boilerplate for agents that only customize
    prompts and tool lists. Use this when your agent doesn't need
    custom initialization logic beyond setting prompts and tools.

    Args:
        name: Name of the agent (e.g., "PRAgent", "TaskManager")
        system_prompt: The system prompt that defines agent behavior
        greeting: The greeting message shown to users at startup
        allowed_tools: Optional list of MCP tool names to allow
        permissions: Optional PermissionSet for the agent's default permissions.
            Defaults to PermissionSet.full_access() if not specified.
        enable_delegation: If True, the agent gets a ``request_agent`` tool
            that lets it consult other specialized agents. Default: False.
            Can be overridden at instantiation time via kwargs.

    Returns:
        An Agent subclass configured with the provided settings

    Example:
        ```python
        from shared.agent_factory import create_simple_agent
        from agent_framework import PermissionSet
        from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

        PRAgent = create_simple_agent(
            name="PRAgent",
            system_prompt=SYSTEM_PROMPT,
            greeting=USER_GREETING_PROMPT,
            allowed_tools=[
                "analyze_website",
                "fetch_web_content",
                "get_memories",
                "save_memory",
            ],
            permissions=PermissionSet.admin(),  # For remote MCP tools
        )

        async def main() -> None:
            await run_agent(PRAgent)
        ```
    """
    # Capture permissions in closure for get_default_permissions
    agent_permissions = permissions
    default_delegation = enable_delegation

    class SimpleAgent(Agent):
        """Dynamically created agent class."""

        def __init__(self, **kwargs: Any) -> None:
            """Initialize the agent with configured tools."""
            if allowed_tools:
                kwargs["allowed_tools"] = allowed_tools
            # Set correct MCP server path for this project structure
            if "mcp_server_path" not in kwargs:
                kwargs["mcp_server_path"] = "mcp_server/server.py"
            # Enable delegation unless explicitly overridden in kwargs
            if "enable_delegation" not in kwargs:
                kwargs["enable_delegation"] = default_delegation
            super().__init__(**kwargs)

        def get_system_prompt(self) -> str:
            """Return the configured system prompt."""
            return system_prompt

        def get_greeting(self) -> str:
            """Return the configured greeting message."""
            return greeting

        def get_agent_name(self) -> str:
            """Return the agent name."""
            return name

        def get_default_permissions(self) -> PermissionSet:
            """Return the configured permissions."""
            if agent_permissions is not None:
                return agent_permissions
            return PermissionSet.full_access()

    # Set the class name for better debugging and introspection
    SimpleAgent.__name__ = name
    SimpleAgent.__qualname__ = name

    return SimpleAgent
