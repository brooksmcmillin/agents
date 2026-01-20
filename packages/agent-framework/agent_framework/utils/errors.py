"""Error types for the agent framework."""


class AgentError(Exception):
    """Base exception for agent framework errors."""

    pass


class ValidationError(AgentError):
    """Raised when tool input validation fails."""

    pass


class AuthenticationError(AgentError):
    """Raised when authentication is required or fails."""

    pass


class ToolExecutionError(AgentError):
    """Raised when tool execution fails."""

    pass


class SecurityError(AgentError):
    """Base exception for security-related errors."""

    pass


class PromptInjectionError(SecurityError):
    """Raised when a prompt injection attack is detected."""

    pass


class ContentPolicyError(SecurityError):
    """Raised when content violates security policies."""

    pass


# Initialization errors
class InitializationError(AgentError):
    """Raised when a component is not properly initialized."""

    def __init__(self, component: str, action: str = "Call initialize() first"):
        super().__init__(f"{component} not initialized. {action}")
        self.component = component


class DatabaseNotInitializedError(InitializationError):
    """Raised when database operation attempted without initialization."""

    def __init__(self):
        super().__init__("Database pool", "Call initialize() first")


class MCPSessionNotInitializedError(InitializationError):
    """Raised when MCP operation attempted without active session."""

    def __init__(self, hint: str = "Use 'async with client.connect():'"):
        super().__init__("MCP session", hint)


class OAuthNotInitializedError(InitializationError):
    """Raised when OAuth operation attempted without initialization."""

    def __init__(self):
        super().__init__("OAuth flow")


class NotConnectedError(AgentError):
    """Raised when operation requires an active connection."""

    def __init__(self, hint: str = "Use 'async with client' first"):
        super().__init__(f"Not connected. {hint}")


# Configuration errors
class ConfigurationError(AgentError):
    """Raised when configuration is missing or invalid."""

    pass


class MissingAPIKeyError(ConfigurationError):
    """Raised when required API key is not found."""

    def __init__(self, key_name: str):
        super().__init__(f"{key_name} not found in environment")
        self.key_name = key_name


class OAuthConfigurationError(ConfigurationError):
    """Raised when OAuth configuration is missing or invalid."""

    pass


class UnsupportedFeatureError(ConfigurationError):
    """Raised when server doesn't support required feature."""

    def __init__(self, feature: str):
        super().__init__(f"Server does not support {feature}")
        self.feature = feature


class MissingMetadataFieldError(ConfigurationError):
    """Raised when required metadata field is missing."""

    def __init__(self, field: str, metadata_type: str = "metadata"):
        super().__init__(f"{metadata_type} missing '{field}' field")
        self.field = field
        self.metadata_type = metadata_type
