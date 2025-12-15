"""Shared utilities and base classes for all agents.

This module contains common code that can be reused across multiple agents,
including:
- Base agent classes
- Shared MCP client utilities (local and remote)
- Common configuration
- Utility functions

As you build more agents, extract common patterns here to avoid duplication.
"""

from .remote_mcp_client import RemoteMCPClient

__all__ = ["RemoteMCPClient"]
__version__ = "0.1.0"
