"""Agent Framework - Reusable LLM agent framework built on MCP."""

__version__ = "0.1.0"

from .adapters.multi_agent_slack_adapter import MultiAgentSlackAdapter, RoutingStrategy
from .core.agent import Agent
from .core.config import Settings
from .core.mcp_client import MCPClient
from .oauth import DeviceAuthorizationCallback, DeviceAuthorizationInfo
from .security import LakeraGuard, LakeraSecurityResult, SecurityCheckError
from .server.server import create_mcp_server
from .utils.errors import ContentPolicyError, PromptInjectionError, SecurityError

__all__ = [
    "Agent",
    "MCPClient",
    "Settings",
    "MultiAgentSlackAdapter",
    "RoutingStrategy",
    "DeviceAuthorizationInfo",
    "DeviceAuthorizationCallback",
    "create_mcp_server",
    # Security
    "LakeraGuard",
    "LakeraSecurityResult",
    "SecurityCheckError",
    "SecurityError",
    "PromptInjectionError",
    "ContentPolicyError",
]
