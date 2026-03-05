"""Agent Framework - Reusable LLM agent framework built on MCP."""

__version__ = "0.1.0"

from .adapters.multi_agent_slack_adapter import MultiAgentSlackAdapter, RoutingStrategy
from .core.agent import Agent
from .core.config import Settings
from .core.mcp_client import MCPClient
from .core.polling_agent import (
    PollingAgent,
    PollingAgentConfig,
    ProcessingRecord,
    WorkItemStatus,
)
from .logging import (
    AgentJsonFormatter,
    ContextualLoggerAdapter,
    correlation_id_var,
    create_json_handler,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
    setup_logging,
)
from .oauth import DeviceAuthorizationCallback, DeviceAuthorizationInfo
from .observability import (
    get_langfuse,
    init_observability,
    observe_tool_call,
    shutdown_observability,
    start_trace,
)
from .permissions import (
    REMOTE_MCP_PERMISSIONS,
    TOOL_PERMISSIONS,
    AgentIdentity,
    ExecutionContext,
    Permission,
    PermissionSet,
    get_required_permissions,
)
from .security import LakeraGuard, LakeraSecurityResult, SecurityCheckError
from .server.server import create_mcp_server
from .telemetry import (
    DECISION_TYPE_AUTONOMY_TIER,
    DECISION_TYPE_DECOMPOSITION,
    DECISION_TYPE_ERROR_HANDLING,
    DECISION_TYPE_ROUTING,
    DECISION_TYPE_TOOL_SELECTION,
    configure_decision_logger,
    get_decision_logger,
    log_decision,
    reset_decision_logger,
)
from .utils.errors import ContentPolicyError, PromptInjectionError, SecurityError

__all__ = [
    "Agent",
    "MCPClient",
    "PollingAgent",
    "PollingAgentConfig",
    "ProcessingRecord",
    "Settings",
    "WorkItemStatus",
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
    # Observability
    "init_observability",
    "shutdown_observability",
    "get_langfuse",
    "start_trace",
    "observe_tool_call",
    # Logging (Loki integration)
    "AgentJsonFormatter",
    "ContextualLoggerAdapter",
    "correlation_id_var",
    "set_correlation_id",
    "get_correlation_id",
    "reset_correlation_id",
    "create_json_handler",
    "setup_logging",
    # Permissions
    "AgentIdentity",
    "ExecutionContext",
    "Permission",
    "PermissionSet",
    "REMOTE_MCP_PERMISSIONS",
    "TOOL_PERMISSIONS",
    "get_required_permissions",
    # Decision logging
    "configure_decision_logger",
    "get_decision_logger",
    "log_decision",
    "reset_decision_logger",
    "DECISION_TYPE_TOOL_SELECTION",
    "DECISION_TYPE_ROUTING",
    "DECISION_TYPE_DECOMPOSITION",
    "DECISION_TYPE_AUTONOMY_TIER",
    "DECISION_TYPE_ERROR_HANDLING",
]
