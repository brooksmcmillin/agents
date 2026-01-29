"""Tests for the configuration module."""

from pathlib import Path

from agent_framework.core.config import Settings


class TestSettings:
    """Tests for the Settings class."""

    def test_settings_defaults(self, temp_dir: Path, monkeypatch):
        """Test Settings with default values."""
        # Create an isolated environment without .env file
        # Save and clear all environment variables that Settings uses
        env_vars_to_clear = [
            "ANTHROPIC_API_KEY",
            "anthropic_api_key",
            "SLACK_WEBHOOK_URL",
            "slack_webhook_url",
            "TOKEN_ENCRYPTION_KEY",
            "token_encryption_key",
            "OPENAI_API_KEY",
            "openai_api_key",
            "SLACK_BOT_TOKEN",
            "slack_bot_token",
            "SLACK_APP_TOKEN",
            "slack_app_token",
            "LAKERA_API_KEY",
            "lakera_api_key",
        ]

        for key in env_vars_to_clear:
            monkeypatch.delenv(key, raising=False)

        # Patch _env_file to prevent loading from .env
        monkeypatch.setenv("TOKEN_STORAGE_PATH", str(temp_dir / "tokens"))
        monkeypatch.setenv("MEMORY_STORAGE_PATH", str(temp_dir / "memories"))

        # Create settings with explicit _env_file=None to skip .env loading

        with monkeypatch.context() as m:
            # Temporarily change the current directory to a temp location without .env
            m.chdir(str(temp_dir))

            settings = Settings(
                token_storage_path=temp_dir / "tokens",
                memory_storage_path=temp_dir / "memories",
                _env_file=None,  # Disable .env file loading
            )

        assert settings.anthropic_api_key is None
        assert settings.mcp_server_host == "localhost"
        assert settings.mcp_server_port == 8000
        assert settings.log_level == "INFO"
        assert isinstance(settings.log_dir, Path)
        assert settings.slack_webhook_url is None
        assert settings.token_encryption_key is None

    def test_settings_creates_directories(self, temp_dir: Path):
        """Test that Settings creates storage directories."""
        token_path = temp_dir / "new_tokens"
        memory_path = temp_dir / "new_memories"

        assert not token_path.exists()
        assert not memory_path.exists()

        Settings(token_storage_path=token_path, memory_storage_path=memory_path)

        assert token_path.exists()
        assert memory_path.exists()

    def test_settings_from_env(self, temp_dir: Path, monkeypatch):
        """Test Settings loads values from environment variables."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        monkeypatch.setenv("MCP_SERVER_HOST", "192.168.1.1")
        monkeypatch.setenv("MCP_SERVER_PORT", "9000")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        settings = Settings(
            token_storage_path=temp_dir / "tokens",
            memory_storage_path=temp_dir / "memories",
        )

        assert settings.anthropic_api_key == "test-key-123"
        assert settings.mcp_server_host == "192.168.1.1"
        assert settings.mcp_server_port == 9000
        assert settings.log_level == "DEBUG"
        assert settings.slack_webhook_url == "https://hooks.slack.com/test"

    def test_settings_case_insensitive(self, temp_dir: Path, monkeypatch):
        """Test that environment variable names are case-insensitive."""
        monkeypatch.setenv("anthropic_api_key", "lower-case-key")

        settings = Settings(
            token_storage_path=temp_dir / "tokens",
            memory_storage_path=temp_dir / "memories",
        )

        assert settings.anthropic_api_key == "lower-case-key"

    def test_settings_path_types(self, temp_dir: Path):
        """Test that storage paths are Path objects."""
        settings = Settings(
            token_storage_path=temp_dir / "tokens",
            memory_storage_path=temp_dir / "memories",
        )

        assert isinstance(settings.token_storage_path, Path)
        assert isinstance(settings.memory_storage_path, Path)
