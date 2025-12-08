"""Configuration management for MCP server."""

import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # MCP Server Configuration
    mcp_server_host: str = Field(default="localhost", description="MCP server host")
    mcp_server_port: int = Field(default=8000, description="MCP server port")

    # OAuth Configuration
    twitter_client_id: Optional[str] = Field(default=None, description="Twitter OAuth client ID")
    twitter_client_secret: Optional[str] = Field(default=None, description="Twitter OAuth client secret")
    linkedin_client_id: Optional[str] = Field(default=None, description="LinkedIn OAuth client ID")
    linkedin_client_secret: Optional[str] = Field(default=None, description="LinkedIn OAuth client secret")

    # Token Storage
    token_storage_path: Path = Field(default=Path("./tokens"), description="Path to store OAuth tokens")
    token_encryption_key: Optional[str] = Field(default=None, description="Key for encrypting stored tokens")

    # Slack Integration
    slack_webhook_url: str | None = Field(default=None, description="Default Slack incoming webhook URL")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="pr_agent.log", description="Log file path")

    def __init__(self, **kwargs):
        """Initialize settings and create necessary directories."""
        super().__init__(**kwargs)
        # Ensure token storage directory exists
        self.token_storage_path.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
