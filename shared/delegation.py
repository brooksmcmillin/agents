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
    - Permission propagation uses ExecutionContext.delegate_to() for proper
      intersection semantics.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_DELEGATION_DEPTH = 3
DELEGATION_TOOL_NAME = "request_agent"
DELEGATION_TIMEOUT_SECONDS = 120

# Module-level registry cache to avoid rebuilding on every delegation call
_registry_cache: dict[str, Any] | None = None


def _get_registry() -> dict[str, Any]:
    """Get or build the agent registry (cached at module level)."""
    global _registry_cache
    if _registry_cache is None:
        from shared.registry import build_agent_registry

        _registry_cache = build_agent_registry()
    return _registry_cache


def seed_registry_cache(registry: dict[str, Any]) -> None:
    """Pre-populate the registry cache (called by build_agent_registry)."""
    global _registry_cache
    _registry_cache = registry


def build_delegation_tool_schema(exclude_class_name: str | None = None) -> dict[str, Any]:
    """Build the request_agent tool schema listing available agents.

    Args:
        exclude_class_name: __name__ of the calling agent's class, used to
            remove itself from the available agents list.

    Returns:
        Tool definition dict in Anthropic tool format, or empty dict if
        no agents are available.
    """
    registry = _get_registry()
    available: dict[str, str] = {}
    for name, (cls, _, desc) in registry.items():
        if exclude_class_name and cls.__name__ == exclude_class_name:
            continue
        available[name] = desc

    if not available:
        return {}

    agent_list = "\n".join(f"  - {name}: {desc}" for name, desc in sorted(available.items()))

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
    3. Propagates permissions via ExecutionContext.delegate_to() (intersection)
    4. Runs the target agent's full agentic loop
    5. Returns the response

    Args:
        agent_name: Short registry name of the target agent.
        message: The request to send to the agent.
        calling_agent: The Agent instance making the delegation call.

    Returns:
        Dict with agent name, description, and response (or error key).
    """
    from shared.registry import GITHUB_MCP_AGENTS, github_mcp_config

    # Resolve agent from registry
    registry = _get_registry()
    entry = registry.get(agent_name)
    if entry is None:
        return {"error": f"Unknown agent '{agent_name}'. Use the agent_name enum values."}

    agent_class, kwargs, description = entry

    # Prevent self-delegation
    if type(calling_agent) is agent_class:
        return {"error": f"Cannot delegate to yourself ('{agent_name}')"}

    # Check delegation depth and cycles
    context = calling_agent.get_execution_context()
    chain: list[str] = list(context.metadata.get("delegation_chain", []))

    if agent_name in chain:
        return {
            "error": (
                f"Circular delegation detected: '{agent_name}' is already in the delegation chain."
            ),
        }

    if len(chain) >= MAX_DELEGATION_DEPTH:
        return {
            "error": (
                f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) reached. "
                f"Handle this request directly instead of delegating further."
            ),
        }

    # Build kwargs for target agent
    target_kwargs: dict[str, Any] = dict(kwargs or {})

    # Handle lazy GitHub MCP config for security/business agents
    if agent_name in GITHUB_MCP_AGENTS and not kwargs:
        try:
            target_kwargs = github_mcp_config()
        except ValueError:
            return {"error": f"Agent '{agent_name}' is currently unavailable."}

    # Only enable delegation on target if its registry entry has it enabled
    registry_kwargs = kwargs or {}
    if registry_kwargs.get("enable_delegation"):
        target_kwargs["enable_delegation"] = True

    # Find calling agent's registry short name for chain tracking
    calling_short_name = calling_agent.get_agent_name()
    for name, (cls, _, _) in registry.items():
        if type(calling_agent) is cls:
            calling_short_name = name
            break

    # Build updated delegation chain
    new_chain = [*chain, calling_short_name]

    # Instantiate target agent
    try:
        target_agent = agent_class(**target_kwargs)
    except Exception as e:
        logger.error(f"Failed to instantiate agent '{agent_name}': {e}")
        return {"error": f"Failed to initialize agent '{agent_name}'."}

    # Create delegated execution context using delegate_to() for proper
    # permission intersection (most restrictive wins)
    delegated_context = context.delegate_to(
        agent_name,
        agent_permissions=target_agent.get_default_permissions(),
    )
    # Update metadata with delegation chain
    delegated_context.metadata["delegation_chain"] = new_chain

    # Delegate the request
    logger.info(
        f"Delegating from {calling_agent.get_agent_name()} to {agent_name} ({len(message)} chars)"
    )

    try:
        response = await asyncio.wait_for(
            target_agent.process_message(
                message,
                execution_context=delegated_context,
            ),
            timeout=DELEGATION_TIMEOUT_SECONDS,
        )
        return {
            "agent": agent_name,
            "agent_description": description,
            "response": response,
        }
    except TimeoutError:
        logger.error(
            f"Agent '{agent_name}' timed out during delegation after {DELEGATION_TIMEOUT_SECONDS}s"
        )
        return {"error": f"Agent '{agent_name}' timed out."}
    except Exception as e:
        logger.error(f"Agent '{agent_name}' failed during delegation: {e}")
        return {"error": f"Agent '{agent_name}' encountered an error during processing."}


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
