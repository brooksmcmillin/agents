"""Tests for the Agent base class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic.types import TextBlock, ToolUseBlock


class ConcreteAgent:
    """Concrete implementation of Agent for testing."""

    def __init__(self, *args, **kwargs):
        # Import here to avoid import issues during test collection
        from agent_framework.core.agent import Agent

        class _ConcreteAgent(Agent):
            def get_system_prompt(self) -> str:
                return "You are a test agent."

            def get_agent_name(self) -> str:
                return "TestAgent"

            def get_greeting(self) -> str:
                return "Hello, I am a test agent!"

        self._agent_class = _ConcreteAgent
        self._instance = None

    def create(self, *args, **kwargs):
        return self._agent_class(*args, **kwargs)


class TestAgentInitialization:
    """Tests for Agent initialization."""

    def test_agent_initialization_with_api_key(self, env_with_api_key):
        """Test Agent initialization with API key from environment."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                assert agent.api_key == "test-api-key-12345"
                assert agent.model == "claude-sonnet-4-5-20250929"
                assert agent.messages == []
                assert agent.total_input_tokens == 0
                assert agent.total_output_tokens == 0

    def test_agent_initialization_with_explicit_api_key(self, env_without_api_key):
        """Test Agent initialization with explicit API key."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create(api_key="explicit-key")

                assert agent.api_key == "explicit-key"

    def test_agent_initialization_without_api_key_raises(self, env_without_api_key):
        """Test Agent initialization raises error when API key is missing."""
        from agent_framework.utils.errors import MissingAPIKeyError

        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                with pytest.raises(MissingAPIKeyError, match="ANTHROPIC_API_KEY"):
                    ConcreteAgent().create()

    def test_agent_initialization_with_custom_model(self, env_with_api_key):
        """Test Agent initialization with custom model."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create(model="claude-opus-4-20250514")

                assert agent.model == "claude-opus-4-20250514"

    def test_agent_initialization_with_custom_mcp_server(self, env_with_api_key):
        """Test Agent initialization with custom MCP server path."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                agent = ConcreteAgent().create(mcp_server_path="custom/server.py")

                assert agent.mcp_server_path == "custom/server.py"
                mock_mcp.assert_called_once()
                # Verify the first argument is the custom server path
                call_args = mock_mcp.call_args
                assert call_args[0][0] == "custom/server.py"


class TestAgentMethods:
    """Tests for Agent methods."""

    def test_get_system_prompt(self, env_with_api_key):
        """Test get_system_prompt returns correct prompt."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                assert agent.get_system_prompt() == "You are a test agent."

    def test_get_agent_name(self, env_with_api_key):
        """Test get_agent_name returns correct name."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                assert agent.get_agent_name() == "TestAgent"

    def test_get_greeting(self, env_with_api_key):
        """Test get_greeting returns correct greeting."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                assert agent.get_greeting() == "Hello, I am a test agent!"

    def test_reset_conversation(self, env_with_api_key):
        """Test reset_conversation clears messages."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()
                agent.messages = [{"role": "user", "content": "test"}]

                agent.reset_conversation()

                assert agent.messages == []

    def test_extract_text_from_response(self, env_with_api_key):
        """Test _extract_text_from_response extracts text correctly."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                # Create mock TextBlock objects
                content = [
                    TextBlock(type="text", text="First part."),
                    TextBlock(type="text", text="Second part."),
                ]

                result = agent._extract_text_from_response(content)

                assert result == "First part.\n\nSecond part."

    def test_extract_text_from_response_empty(self, env_with_api_key):
        """Test _extract_text_from_response handles empty content with fallback."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                result = agent._extract_text_from_response([])

                # Returns fallback to prevent API errors with empty content
                assert result == "<No text in response>"

    def test_ensure_non_empty_content_with_content(self, env_with_api_key):
        """Test _ensure_non_empty_content passes through non-empty content."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()
                content = [TextBlock(type="text", text="Hello")]

                result = agent._ensure_non_empty_content(content)

                assert result is content

    def test_ensure_non_empty_content_empty(self, env_with_api_key):
        """Test _ensure_non_empty_content returns fallback for empty content."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                result = agent._ensure_non_empty_content([])

                assert len(result) == 1
                assert result[0].type == "text"
                assert result[0].text == "<No text in response>"

    def test_print_stats(self, env_with_api_key, capsys):
        """Test _print_stats outputs correct statistics."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()
                agent.total_input_tokens = 100
                agent.total_output_tokens = 50
                agent.messages = [
                    {"role": "user", "content": "msg1"},
                    {"role": "assistant", "content": "resp1"},
                    {"role": "user", "content": "msg2"},
                ]

                agent._print_stats()

                captured = capsys.readouterr()
                assert "Input tokens:  100" in captured.out
                assert "Output tokens: 50" in captured.out
                assert "Total tokens:  150" in captured.out
                assert "Conversations: 2" in captured.out


class TestAgentProcessMessage:
    """Tests for Agent.process_message method."""

    @pytest.mark.asyncio
    async def test_process_message_simple_response(self, env_with_api_key):
        """Test process_message with a simple text response."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                # Set up mocks
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                mock_response = MagicMock()
                mock_response.stop_reason = "end_turn"
                mock_response.content = [TextBlock(type="text", text="Test response")]
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5
                mock_client.messages.create = AsyncMock(return_value=mock_response)

                # Mock MCP client
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.connect = AsyncMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock()
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()
                mock_mcp_instance.available_tools = {}

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance

                # Mock the connect context manager
                async def mock_connect():
                    return mock_mcp_instance

                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                result = await agent.process_message("Hello")

                assert result == "Test response"
                assert agent.total_input_tokens == 10
                assert agent.total_output_tokens == 5
                assert len(agent.messages) == 2  # user message + assistant response

    @pytest.mark.asyncio
    async def test_process_message_max_iterations(self, env_with_api_key):
        """Test process_message handles max iterations."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # Always return tool_use to trigger max iterations
                mock_response = MagicMock()
                mock_response.stop_reason = "tool_use"
                mock_response.content = [
                    ToolUseBlock(
                        type="tool_use",
                        id="tool_123",
                        name="test_tool",
                        input={"arg": "value"},
                    )
                ]
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5
                mock_client.messages.create = AsyncMock(return_value=mock_response)

                # Mock MCP client
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.available_tools = {"test_tool": MagicMock()}
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()
                mock_mcp_instance.call_tool = AsyncMock(return_value={"result": "ok"})

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance

                # Mock _call_mcp_tool_with_reconnect
                agent._call_mcp_tool_with_reconnect = AsyncMock(return_value={"result": "ok"})

                result = await agent.process_message("Run many tools")

                assert "having trouble completing this request" in result

    @pytest.mark.asyncio
    async def test_process_message_handles_errors(self, env_with_api_key):
        """Test process_message handles API errors gracefully."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client
                mock_client.messages.create = AsyncMock(side_effect=Exception("API Error"))

                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.available_tools = {}
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance

                result = await agent.process_message("Test")

                assert "encountered an error" in result


class TestAgentMemoryIsolation:
    """Tests for automatic agent_name injection in memory tools."""

    @pytest.mark.asyncio
    async def test_memory_tool_auto_injects_agent_name(self, env_with_api_key):
        """Test that memory tools get agent_name auto-injected."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.call_tool = AsyncMock(return_value={"status": "success"})
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance
                agent.tools = {"local": ["save_memory", "get_memories"]}

                # Call save_memory without agent_name
                await agent._call_mcp_tool_with_reconnect(
                    "save_memory",
                    {"key": "test_key", "value": "test_value"},
                )

                # Verify agent_name was injected
                call_args = mock_mcp_instance.call_tool.call_args
                assert call_args[0][1]["agent_name"] == "TestAgent"

    @pytest.mark.asyncio
    async def test_memory_tool_does_not_override_explicit_agent_name(self, env_with_api_key):
        """Test that explicitly provided agent_name is not overwritten."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.call_tool = AsyncMock(return_value={"status": "success"})
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance
                agent.tools = {"local": ["save_memory"]}

                # Call save_memory with explicit agent_name
                await agent._call_mcp_tool_with_reconnect(
                    "save_memory",
                    {"key": "test_key", "value": "test_value", "agent_name": "custom_agent"},
                )

                # Verify explicit agent_name was preserved
                call_args = mock_mcp_instance.call_tool.call_args
                assert call_args[0][1]["agent_name"] == "custom_agent"

    @pytest.mark.asyncio
    async def test_non_memory_tool_no_agent_name_injection(self, env_with_api_key):
        """Test that non-memory tools don't get agent_name injected."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.call_tool = AsyncMock(return_value={"result": "ok"})
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance
                agent.tools = {"local": ["fetch_web_content"]}

                # Call non-memory tool
                await agent._call_mcp_tool_with_reconnect(
                    "fetch_web_content",
                    {"url": "https://example.com"},
                )

                # Verify agent_name was NOT injected
                call_args = mock_mcp_instance.call_tool.call_args
                assert "agent_name" not in call_args[0][1]

    @pytest.mark.asyncio
    async def test_all_memory_tools_get_agent_name_injected(self, env_with_api_key):
        """Test that all memory tools get agent_name injected."""
        from agent_framework.core.agent import MEMORY_TOOLS

        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.call_tool = AsyncMock(return_value={"status": "success"})
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_instance
                agent.tools = {"local": list(MEMORY_TOOLS)}

                # Test each memory tool
                for tool_name in MEMORY_TOOLS:
                    mock_mcp_instance.call_tool.reset_mock()

                    # Build minimal args for each tool
                    if tool_name == "save_memory":
                        args = {"key": "k", "value": "v"}
                    elif tool_name == "search_memories":
                        args = {"query": "test"}
                    elif tool_name == "delete_memory":
                        args = {"key": "k"}
                    else:
                        args = {}

                    await agent._call_mcp_tool_with_reconnect(tool_name, args)

                    # Verify agent_name was injected
                    call_args = mock_mcp_instance.call_tool.call_args
                    assert call_args[0][1].get("agent_name") == "TestAgent", (
                        f"{tool_name} did not get agent_name injected"
                    )
