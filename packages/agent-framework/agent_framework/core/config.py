"""Configuration management for agents and MCP servers."""

import os
from datetime import datetime
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # LLM Configuration
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API key for Claude")

    # MCP Server Configuration
    mcp_server_host: str = Field(default="localhost", description="MCP server host")
    mcp_server_port: int = Field(default=8000, description="MCP server port")

    # Token Storage
    token_storage_path: Path = Field(
        default=Path.home() / ".agents" / "tokens",
        description="Path to store OAuth tokens",
    )
    token_encryption_key: str | None = Field(
        default=None, description="Key for encrypting stored tokens"
    )

    # Memory Storage
    memory_storage_path: Path = Field(
        default=Path.home() / ".agents" / "memories",
        description="Path to store memories",
    )

    # RAG (Retrieval-Augmented Generation) Storage
    rag_database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL for RAG storage (e.g., postgresql://user:pass@localhost:5432/dbname)",  # pragma: allowlist secret
    )
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key for generating embeddings"
    )
    rag_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model to use for RAG",
    )
    rag_table_name: str = Field(
        default="rag_documents", description="PostgreSQL table name for RAG documents"
    )

    # FastMail Integration (JMAP API)
    fastmail_api_token: str | None = Field(
        default=None,
        description="FastMail API token for JMAP access. Generate at: "
        "Settings -> Privacy & Security -> Integrations -> API tokens",
    )

    # Agent Email Configuration
    admin_email_address: str | None = Field(
        default=None,
        description="Admin email address that agents send reports/notifications to. "
        "Used by send_agent_report tool.",
    )
    agent_email_domain: str = Field(
        default="brooksmcmillin.com",
        description="Domain for agent email addresses. Each agent sends from "
        "{agent_name}@{domain} (e.g., chatbot@brooksmcmillin.com).",
    )

    # Slack Integration
    slack_webhook_url: str | None = Field(
        default=None, description="Default Slack incoming webhook URL"
    )
    slack_bot_token: str | None = Field(
        default=None, description="Slack Bot User OAuth Token (xoxb-...)"
    )
    slack_app_token: str | None = Field(
        default=None, description="Slack App-Level Token for Socket Mode (xapp-...)"
    )
    slack_signing_secret: str | None = Field(
        default=None, description="Slack Signing Secret for request verification"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_dir: Path = Field(
        default=Path.home() / ".agents" / "logs",
        description="Directory for log files",
    )

    # Security - Lakera Guard
    lakera_api_key: str | None = Field(
        default=None,
        description="Lakera Guard API key for prompt injection detection. "
        "If not set, security checks are skipped.",
    )
    lakera_project_id: str | None = Field(
        default=None,
        description="Lakera Guard project ID for request tracking and analytics.",
    )
    lakera_fail_open: bool = Field(
        default=True,
        description="If True, allow content through when Lakera API errors occur. "
        "If False, block content on API failures.",
    )

    # Observability - Langfuse
    langfuse_enabled: bool = Field(
        default=False,
        description="Enable Langfuse observability. Requires LANGFUSE_PUBLIC_KEY and "
        "LANGFUSE_SECRET_KEY to be set.",
    )
    langfuse_public_key: str | None = Field(
        default=None,
        description="Langfuse public key for tracing.",
    )
    langfuse_secret_key: str | None = Field(
        default=None,
        description="Langfuse secret key for tracing.",
    )
    langfuse_host: str | None = Field(
        default=None,
        description="Langfuse host URL. Accepts LANGFUSE_HOST or LANGFUSE_BASE_URL. "
        "Defaults to Langfuse Cloud. Set for regional endpoints or self-hosted.",
        validation_alias=AliasChoices("langfuse_host", "langfuse_base_url"),
    )

    @field_validator("langfuse_host")
    @classmethod
    def validate_langfuse_host(cls, v: str | None) -> str | None:
        """Validate that langfuse_host is a valid HTTPS URL."""
        if v is None:
            return v
        if not v.startswith("https://"):
            raise ValueError("Langfuse host URL must start with https://")
        return v

    def __init__(self, **kwargs):
        """Initialize settings and create necessary directories."""
        super().__init__(**kwargs)
        # Ensure storage directories exist
        self.token_storage_path.mkdir(parents=True, exist_ok=True)
        # Only create memory_storage_path if using file backend
        if os.environ.get("MEMORY_BACKEND", "file").lower() == "file":
            self.memory_storage_path.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def get_log_file(self, component_name: str = "agent") -> Path:
        """Get a log file path for a specific component.

        Creates log files with the format: {component_name}_{date}.log
        e.g., pr_agent_2024-01-15.log, mcp_server_2024-01-15.log

        Args:
            component_name: Name of the component (agent name, server name, etc.)

        Returns:
            Path to the log file
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        # Sanitize component name for filesystem
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in component_name)
        return self.log_dir / f"{safe_name}_{date_str}.log"


# Global settings instance
settings = Settings()
