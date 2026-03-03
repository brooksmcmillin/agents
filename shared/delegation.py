"""Agent-to-agent delegation support.

Allows agents to consult other specialized agents during their agentic loop.
Delegation preserves the permission model: delegated agents receive intersected
permissions (most restrictive wins).

Setup is automatic — build_agent_registry() calls setup_delegation() which
configures the Agent base class with the handler and schema builder.

Architecture:
    - The Agent base class (in agent_framework) has a class-level
      _delegation_config dict, set by setup_delegation() at registry build time.
    - Agents with enable_delegation=True get the request_agent tool added to
      their tool list and intercept calls to it in _execute_tool_calls().
    - The handler runs in-process (not via MCP subprocess), instantiating
      the target agent from the registry and calling process_message().
    - Permission propagation uses ExecutionContext intersection semantics.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_DELEGATION_DEPTH = 3
DELEGATION_TOOL_NAME = "request_agent"


def build_delegation_tool_schema(exclude_class_name: str | None = None) -> dict[str, Any]:
    """Build the request_agent tool schema listing available agents.

    Args:
        exclude_class_name: __name__ of the calling agent's class, used to
            remove itself from the available agents list.

    Returns:
        Tool definition dict in Anthropic tool format, or empty dict if
        no agents are available.
    """
    from shared.registry import build_agent_registry

    registry = build_agent_registry()
    available: dict[str, str] = {}
    for name, (cls, _, desc) in registry.items():
        if exclude_class_name and cls.__name__ == exclude_class_name:
            continue
        available[name] = desc

    if not available:
        return {}

    agent_list = "\n".join(
        f"  - {name}: {desc}" for name, desc in sorted(available.items())
    )

    return {
        "name": DELEGATION_TOOL_NAME,
        "description": (
            "Consult another specialized agent and get their expert response. "
            "Use this when a question or task would benefit from another agent's "
            "domain expertise. The agent will process your request using its own "
            "tools and knowledge, then return its response.\n\n"
            f"Available agents:\n{agent_list}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Short name of the agent to consult (from the list above)",
                    "enum": sorted(available.keys()),
                },
                "message": {
                    "type": "string",
                    "description": (
                        "The request or question to send to the agent. Be specific "
                        "about what you need - the agent will see only this message, "
                        "not your full conversation history."
                    ),
                },
            },
            "required": ["agent_name", "message"],
        },
    }


async def handle_delegation(
    agent_name: str,
    message: str,
    calling_agent: Any,
) -> dict[str, Any]:
    """Handle a request_agent tool call by delegating to another agent.

    1. Resolves the target agent from the registry
    2. Checks for circular delegation and depth limits
    3. Propagates permissions via ExecutionContext (intersection semantics)
    4. Runs the target agent's full agentic loop
    5. Returns the response

    Args:
        agent_name: Short registry name of the target agent.
        message: The request to send to the agent.
        calling_agent: The Agent instance making the delegation call.

    Returns:
        Dict with agent name, description, and response (or error key).
    """
    from agent_framework.permissions import AgentIdentity, ExecutionContext
    from shared.registry import GITHUB_MCP_AGENTS, build_agent_registry, github_mcp_config

    # Resolve agent from registry
    registry = build_agent_registry()
    entry = registry.get(agent_name)
    if entry is None:
        available = sorted(registry.keys())
        return {"error": f"Unknown agent '{agent_name}'. Available agents: {available}"}

    agent_class, kwargs, description = entry

    # Prevent self-delegation
    for name, (cls, _, _) in registry.items():
        if type(calling_agent) is cls and name == agent_name:
            return {"error": f"Cannot delegate to yourself ('{agent_name}')"}

    # Check delegation depth and cycles
    context = calling_agent.get_execution_context()
    chain: list[str] = list(context.metadata.get("delegation_chain", []))

    if agent_name in chain:
        return {
            "error": (
                f"Circular delegation detected: '{agent_name}' is already in the "
                f"delegation chain {chain}."
            ),
        }

    if len(chain) >= MAX_DELEGATION_DEPTH:
        return {
            "error": (
                f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) reached. "
                f"Current chain: {chain}. Handle this request directly instead "
                f"of delegating further."
            ),
        }

    # Build kwargs for target agent
    target_kwargs: dict[str, Any] = dict(kwargs or {})

    # Handle lazy GitHub MCP config for security/business agents
    if agent_name in GITHUB_MCP_AGENTS and not kwargs:
        try:
            target_kwargs = github_mcp_config()
        except ValueError as e:
            return {"error": f"Agent '{agent_name}' is unavailable: {e}"}

    # Enable delegation for the target agent (allows multi-hop)
    target_kwargs["enable_delegation"] = True

    # Find calling agent's registry short name for chain tracking
    calling_short_name = calling_agent.get_agent_name()
    for name, (cls, _, _) in registry.items():
        if type(calling_agent) is cls:
            calling_short_name = name
            break

    # Build updated delegation chain
    new_chain = [*chain, calling_short_name]

    # Create delegated execution context with permission propagation
    delegated_context = ExecutionContext(
        caller=AgentIdentity(
            name=calling_agent.get_agent_name(),
            source="delegation",
            metadata={"target_agent": agent_name, "delegation_chain": new_chain},
        ),
        permissions=context.permissions,
        parent=context,
        metadata={**context.metadata, "delegation_chain": new_chain},
    )

    # Instantiate target agent
    try:
        target_agent = agent_class(**target_kwargs)
    except Exception as e:
        logger.error(f"Failed to instantiate agent '{agent_name}': {e}")
        return {"error": f"Failed to initialize agent '{agent_name}': {e}"}

    # Delegate the request
    logger.info(
        f"Delegating from {calling_agent.get_agent_name()} to {agent_name}: "
        f"{message[:100]}{'...' if len(message) > 100 else ''}"
    )

    try:
        response = await target_agent.process_message(
            message,
            execution_context=delegated_context,
        )
        return {
            "agent": agent_name,
            "agent_description": description,
            "response": response,
        }
    except Exception as e:
        logger.error(f"Agent '{agent_name}' failed during delegation: {e}")
        return {"error": f"Agent '{agent_name}' encountered an error: {e}"}


def setup_delegation() -> None:
    """Configure the Agent base class for delegation support.

    Sets class-level configuration on Agent that enables the request_agent
    tool for agents with enable_delegation=True. Called automatically by
    build_agent_registry().
    """
    from agent_framework import Agent

    Agent._delegation_config = {
        "handler": handle_delegation,
        "schema_builder": build_delegation_tool_schema,
    }
