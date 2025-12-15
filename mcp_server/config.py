"""Configuration management for MCP server."""

from typing import Optional

from agent_framework import Settings as BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OAuth Configuration
    twitter_client_id: Optional[str] = Field(default=None, description="Twitter OAuth client ID")
    twitter_client_secret: Optional[str] = Field(default=None, description="Twitter OAuth client secret")
    linkedin_client_id: Optional[str] = Field(default=None, description="LinkedIn OAuth client ID")
    linkedin_client_secret: Optional[str] = Field(default=None, description="LinkedIn OAuth client secret")

# Global settings instance
settings = Settings()
