"""Adapters for connecting agents to external messaging platforms."""

from .multi_agent_slack_adapter import MultiAgentSlackAdapter, RoutingStrategy

__all__ = [
    "MultiAgentSlackAdapter",
    "RoutingStrategy",
]
