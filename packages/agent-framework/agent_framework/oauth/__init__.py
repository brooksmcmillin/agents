"""OAuth 2.0 authentication support for MCP servers.

This package provides OAuth 2.0 authentication with support for:
- OAuth Authorization Server Metadata discovery (RFC 8414)
- OAuth Protected Resource Metadata discovery (RFC 9908)
- Authorization Code Flow with PKCE
- Device Authorization Grant (RFC 8628)
- Token refresh and storage
"""

from .device_flow import (
    DeviceAuthorizationCallback,
    DeviceAuthorizationInfo,
    DeviceFlowDeniedError,
    DeviceFlowError,
    DeviceFlowExpiredError,
    DeviceFlowHandler,
)
from .oauth_base import OAuthHandlerBase
from .oauth_config import OAuthConfig, discover_oauth_config
from .oauth_flow import OAuthFlowHandler, generate_pkce_pair
from .oauth_tokens import TokenSet, TokenStorage

__all__ = [
    # Base class
    "OAuthHandlerBase",
    # Device Flow (RFC 8628)
    "DeviceFlowHandler",
    "DeviceFlowError",
    "DeviceFlowExpiredError",
    "DeviceFlowDeniedError",
    "DeviceAuthorizationInfo",
    "DeviceAuthorizationCallback",
    # OAuth Config
    "OAuthConfig",
    "discover_oauth_config",
    # Authorization Code Flow
    "OAuthFlowHandler",
    "generate_pkce_pair",
    # Tokens
    "TokenSet",
    "TokenStorage",
]
