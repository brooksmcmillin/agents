"""Configuration management for agents and MCP servers."""

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
    anthropic_api_key: str | None = Field(
        default=None, repr=False, description="Anthropic API key for Claude"
    )

    # Backup Model Fallback
    backup_model: str | None = Field(
        default=None,
        description="LiteLLM model identifier for fallback when Anthropic API is unavailable. "
        "Examples: 'openai/gpt-4o', 'gemini/gemini-2.0-flash', 'groq/llama-3.3-70b'. "
        "See https://docs.litellm.ai/docs/providers for supported providers.",
    )
    backup_api_key: str | None = Field(
        default=None,
        repr=False,
        description="API key for the backup model provider. "
        "E.g., OpenAI API key if backup_model is 'openai/gpt-4o'.",
    )
    use_backup_model: bool = Field(
        default=False,
        description="When True, route ALL requests through the backup model instead of "
        "Anthropic. Useful for testing full agent flows with the backup provider "
        "before an actual outage. Requires BACKUP_MODEL to be set.",
    )

    # MCP Server Configuration
    mcp_server_host: str = Field(default="localhost", description="MCP server host")
    mcp_server_port: int = Field(default=8000, description="MCP server port")

    # Token Storage
    token_storage_path: Path = Field(
        default=Path.home() / ".agents" / "tokens",
        description="Path to store OAuth tokens",
    )
    token_encryption_key: str | None = Field(
        default=None, repr=False, description="Key for encrypting stored tokens"
    )

    # Memory Storage
    memory_storage_path: Path = Field(
        default=Path.home() / ".agents" / "memories",
        description="Path to store memories",
    )
    memory_backend: str = Field(
        default="file",
        description="Memory storage backend. Options: 'file' (default, local JSON) or "
        "'database' (PostgreSQL, enables cross-machine portability).",
    )

    # RAG (Retrieval-Augmented Generation) Storage
    rag_database_url: str | None = Field(
        default=None,
        repr=False,  # May contain password in URL
        description="PostgreSQL connection URL for RAG storage (e.g., postgresql://user:pass@localhost:5432/dbname)",  # pragma: allowlist secret
    )
    openai_api_key: str | None = Field(
        default=None, repr=False, description="OpenAI API key for generating embeddings"
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
        repr=False,
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
        default="yourdomain.com",
        description="Domain for agent email addresses. Each agent sends from "
        "{agent_name}@{domain} (e.g., chatbot@yourdomain.com).",
    )
    allowed_email_recipients: str | None = Field(
        default=None,
        description="Comma-separated list of allowed email recipients for send_email. "
        "If set, only these addresses can receive emails. Supports wildcards for domains "
        "(e.g., '*@example.com,admin@company.com'). If not set, email sending is disabled "
        "for security. The admin_email_address is always implicitly allowed.",
    )
    intake_email_address: str | None = Field(
        default=None,
        description="Email address monitored by the email intake agent. "
        "Emails sent to this address from ADMIN_EMAIL_ADDRESS will be processed.",
    )
    intake_shared_secret: str | None = Field(
        default=None,
        repr=False,
        description="Shared secret that must be present in email body for intake processing. "
        "Required for security - prevents email spoofing attacks. Generate a random string.",
    )

    # Slack Integration
    slack_webhook_url: str | None = Field(
        default=None, repr=False, description="Default Slack incoming webhook URL"
    )
    slack_bot_token: str | None = Field(
        default=None, repr=False, description="Slack Bot User OAuth Token (xoxb-...)"
    )
    slack_app_token: str | None = Field(
        default=None, repr=False, description="Slack App-Level Token for Socket Mode (xapp-...)"
    )
    slack_signing_secret: str | None = Field(
        default=None, repr=False, description="Slack Signing Secret for request verification"
    )

    # Twilio Integration (SMS and Voice)
    twilio_account_sid: str | None = Field(
        default=None,
        description="Twilio Account SID. Get from: https://console.twilio.com/",
    )
    twilio_auth_token: str | None = Field(
        default=None,
        repr=False,
        description="Twilio Auth Token. Get from: https://console.twilio.com/",
    )
    twilio_phone_number: str | None = Field(
        default=None,
        description="Twilio phone number in E.164 format (e.g., +15551234567). "
        "Used as the 'from' number for SMS messages.",
    )
    admin_phone_number: str | None = Field(
        default=None,
        description="Admin phone number in E.164 format (e.g., +15551234567). "
        "SMS messages from agents are sent only to this number for security.",
    )

    # SMS Phone Pool for two-way conversations
    twilio_phone_pool: str | None = Field(
        default=None,
        description="Comma-separated list of Twilio phone numbers for the SMS phone pool. "
        "E.164 format (e.g., +15551234567,+15551234568). Used for two-way SMS conversations "
        "where admin replies need to be routed back to the correct agent conversation.",
    )
    sms_lock_timeout_minutes: int = Field(
        default=30,
        description="Default timeout in minutes for SMS phone locks. After this time, "
        "the phone is released back to the pool if no reply is received.",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_dir: Path = Field(
        default=Path.home() / ".agents" / "logs",
        description="Directory for log files",
    )
    loki_enabled: bool = Field(
        default=False,
        description="Enable Loki-compatible JSON logging. When True, log files use "
        "structured JSON format for aggregation with Grafana Loki.",
    )
    log_format: str = Field(
        default="text",
        description="Log format for file output: 'text' (human-readable) or 'json' "
        "(Loki-compatible). JSON format is automatically enabled when loki_enabled=True.",
    )

    # Security - Lakera Guard
    lakera_api_key: str | None = Field(
        default=None,
        repr=False,
        description="Lakera Guard API key for prompt injection detection. "
        "If not set, security checks are skipped.",
    )
    lakera_project_id: str | None = Field(
        default=None,
        description="Lakera Guard project ID for request tracking and analytics.",
    )
    lakera_fail_open: bool = Field(
        default=False,
        description="If True, allow content through when Lakera API errors occur. "
        "If False, block content on API failures (secure default).",
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
        repr=False,
        description="Langfuse secret key for tracing.",
    )
    langfuse_host: str | None = Field(
        default=None,
        description="Langfuse host URL. Accepts LANGFUSE_HOST or LANGFUSE_BASE_URL. "
        "Defaults to Langfuse Cloud. Set for regional endpoints or self-hosted.",
        validation_alias=AliasChoices("langfuse_host", "langfuse_base_url"),
    )

    @field_validator("memory_backend")
    @classmethod
    def validate_memory_backend(cls, v: str) -> str:
        """Normalize and validate the memory backend setting.

        Lowercases the value (so ``MEMORY_BACKEND=DATABASE`` works) and
        rejects strings that are not one of the known backends.
        """
        normalized = v.lower()
        valid_backends = ("file", "database")
        if normalized not in valid_backends:
            raise ValueError(f"Invalid memory_backend '{v}'. Must be one of: {valid_backends}")
        return normalized

    @field_validator("langfuse_host")
    @classmethod
    def validate_langfuse_host(cls, v: str | None) -> str | None:
        """Validate that langfuse_host is a valid HTTPS URL."""
        if v is None:
            return v
        if not v.startswith("https://"):
            raise ValueError("Langfuse host URL must start with https://")
        return v

    def __init__(self, **kwargs) -> None:
        """Initialize settings and create necessary directories."""
        super().__init__(**kwargs)
        # Ensure storage directories exist with restrictive permissions.
        # The storage classes (TokenStore, MemoryStore) also enforce 0o700 on
        # init, but setting it here closes the race-condition window between
        # directory creation and first use.
        self.token_storage_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.token_storage_path.chmod(0o700)
        # Only create memory_storage_path if using file backend
        if self.memory_backend == "file":
            self.memory_storage_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.memory_storage_path.chmod(0o700)
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log_dir.chmod(0o700)

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
