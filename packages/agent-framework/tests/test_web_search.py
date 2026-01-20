"""Tests for web search functionality in the Agent class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic.types import TextBlock, WebSearchToolResultBlock


class ConcreteAgent:
    """Concrete implementation of Agent for testing."""

    def __init__(self, *args, **kwargs):
        from agent_framework.core.agent import Agent

        class _ConcreteAgent(Agent):
            def get_system_prompt(self) -> str:
                return "You are a test agent with web search."

            def get_agent_name(self) -> str:
                return "WebSearchTestAgent"

            def get_greeting(self) -> str:
                return "Hello, I can search the web!"

        self._agent_class = _ConcreteAgent

    def create(self, *args, **kwargs):
        return self._agent_class(*args, **kwargs)


class TestWebSearchInitialization:
    """Tests for Agent initialization with web search."""

    def test_agent_initialization_with_web_search_enabled(self, env_with_api_key):
        """Test Agent initialization with web search enabled."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create(enable_web_search=True)

                assert agent.enable_web_search is True
                assert agent.web_search_config == {}

    def test_agent_initialization_with_web_search_disabled(self, env_with_api_key):
        """Test Agent initialization with web search disabled (default)."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                assert agent.enable_web_search is True

    def test_agent_initialization_with_web_search_config(self, env_with_api_key):
        """Test Agent initialization with web search configuration."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                config = {
                    "max_uses": 3,
                    "allowed_domains": ["example.com", "test.com"],
                    "blocked_domains": ["spam.com"],
                    "user_location": {
                        "type": "approximate",
                        "city": "San Francisco",
                        "region": "California",
                        "country": "US",
                    },
                }
                agent = ConcreteAgent().create(enable_web_search=True, web_search_config=config)

                assert agent.enable_web_search is True
                assert agent.web_search_config == config


class TestBuildWebSearchTool:
    """Tests for the _build_web_search_tool method."""

    def test_build_web_search_tool_basic(self, env_with_api_key):
        """Test building basic web search tool configuration."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create(enable_web_search=True)

                tool = agent._build_web_search_tool()

                assert tool["type"] == "web_search_20250305"
                assert tool["name"] == "web_search"
                assert "max_uses" not in tool  # Not set by default

    def test_build_web_search_tool_with_max_uses(self, env_with_api_key):
        """Test building web search tool with max_uses."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create(
                    enable_web_search=True, web_search_config={"max_uses": 5}
                )

                tool = agent._build_web_search_tool()

                assert tool["max_uses"] == 5

    def test_build_web_search_tool_with_invalid_max_uses(self, env_with_api_key):
        """Test building web search tool ignores invalid max_uses."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                # Test value too high
                agent = ConcreteAgent().create(
                    enable_web_search=True, web_search_config={"max_uses": 20}
                )
                tool = agent._build_web_search_tool()
                assert "max_uses" not in tool

                # Test value too low
                agent = ConcreteAgent().create(
                    enable_web_search=True, web_search_config={"max_uses": 0}
                )
                tool = agent._build_web_search_tool()
                assert "max_uses" not in tool

                # Test non-integer value
                agent = ConcreteAgent().create(
                    enable_web_search=True, web_search_config={"max_uses": "five"}
                )
                tool = agent._build_web_search_tool()
                assert "max_uses" not in tool

    def test_build_web_search_tool_with_allowed_domains(self, env_with_api_key):
        """Test building web search tool with allowed_domains."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                domains = ["docs.python.org", "developer.mozilla.org"]
                agent = ConcreteAgent().create(
                    enable_web_search=True,
                    web_search_config={"allowed_domains": domains},
                )

                tool = agent._build_web_search_tool()

                assert tool["allowed_domains"] == domains

    def test_build_web_search_tool_with_blocked_domains(self, env_with_api_key):
        """Test building web search tool with blocked_domains."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                domains = ["spam.com", "ads.net"]
                agent = ConcreteAgent().create(
                    enable_web_search=True,
                    web_search_config={"blocked_domains": domains},
                )

                tool = agent._build_web_search_tool()

                assert tool["blocked_domains"] == domains

    def test_build_web_search_tool_with_user_location(self, env_with_api_key):
        """Test building web search tool with user_location."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                location = {
                    "type": "approximate",
                    "city": "New York",
                    "region": "New York",
                    "country": "US",
                }
                agent = ConcreteAgent().create(
                    enable_web_search=True,
                    web_search_config={"user_location": location},
                )

                tool = agent._build_web_search_tool()

                assert tool["user_location"] == location

    def test_build_web_search_tool_with_all_options(self, env_with_api_key):
        """Test building web search tool with all options."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                config = {
                    "max_uses": 7,
                    "allowed_domains": ["trusted.com"],
                    "blocked_domains": ["untrusted.com"],
                    "user_location": {
                        "type": "approximate",
                        "city": "London",
                        "country": "UK",
                    },
                }
                agent = ConcreteAgent().create(enable_web_search=True, web_search_config=config)

                tool = agent._build_web_search_tool()

                assert tool["type"] == "web_search_20250305"
                assert tool["name"] == "web_search"
                assert tool["max_uses"] == 7
                assert tool["allowed_domains"] == ["trusted.com"]
                assert tool["blocked_domains"] == ["untrusted.com"]
                assert tool["user_location"]["city"] == "London"


class TestConvertMCPToolsWithWebSearch:
    """Tests for _convert_mcp_tools_to_anthropic with web search."""

    @pytest.mark.asyncio
    async def test_convert_tools_includes_web_search_when_enabled(self, env_with_api_key):
        """Test that web search tool is included when enabled."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.available_tools = {}
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create(enable_web_search=True)
                agent.mcp_client = mock_mcp_instance

                tools = await agent._convert_mcp_tools_to_anthropic()

                # Should include web search tool
                web_search_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
                assert len(web_search_tools) == 1
                assert web_search_tools[0]["name"] == "web_search"

    @pytest.mark.asyncio
    async def test_convert_tools_excludes_web_search_when_disabled(self, env_with_api_key):
        """Test that web search tool is not included when disabled."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.available_tools = {}
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create(enable_web_search=False)
                agent.mcp_client = mock_mcp_instance

                tools = await agent._convert_mcp_tools_to_anthropic()

                # Should not include web search tool
                web_search_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
                assert len(web_search_tools) == 0


class TestExtractTextWithWebSearchResults:
    """Tests for _extract_text_from_response with web search results."""

    def test_extract_text_with_text_blocks_only(self, env_with_api_key):
        """Test extracting text when only TextBlocks are present."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                content = [
                    TextBlock(type="text", text="Here is the answer."),
                    TextBlock(type="text", text="More details here."),
                ]

                result = agent._extract_text_from_response(content)

                assert "Here is the answer." in result
                assert "More details here." in result

    def test_extract_text_handles_web_search_result_block(self, env_with_api_key):
        """Test extracting text handles WebSearchToolResultBlock gracefully."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                # Create mock WebSearchToolResultBlock
                mock_search_result = MagicMock(spec=WebSearchToolResultBlock)
                mock_search_result.content = None  # No content

                content = [
                    TextBlock(type="text", text="Search results:"),
                    mock_search_result,
                ]

                result = agent._extract_text_from_response(content)

                # Should still extract text blocks
                assert "Search results:" in result

    def test_extract_text_with_web_search_sources(self, env_with_api_key):
        """Test extracting text with web search sources."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                # Create mock search result content
                mock_result_content = MagicMock()
                mock_result_content.url = "https://example.com/article"
                mock_result_content.title = "Example Article"

                # Create mock WebSearchToolResultBlock
                mock_search_result = MagicMock(spec=WebSearchToolResultBlock)
                mock_search_result.content = [mock_result_content]

                content = [
                    TextBlock(type="text", text="Based on my search:"),
                    mock_search_result,
                ]

                result = agent._extract_text_from_response(content)

                assert "Based on my search:" in result
                assert "Sources:" in result
                assert "Example Article" in result
                assert "https://example.com/article" in result

    def test_extract_text_deduplicates_sources(self, env_with_api_key):
        """Test that duplicate sources are removed."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient"):
                agent = ConcreteAgent().create()

                # Create duplicate search results
                mock_result_content = MagicMock()
                mock_result_content.url = "https://example.com"
                mock_result_content.title = "Example"

                mock_search_result = MagicMock(spec=WebSearchToolResultBlock)
                mock_search_result.content = [mock_result_content, mock_result_content]

                content = [
                    TextBlock(type="text", text="Info:"),
                    mock_search_result,
                ]

                result = agent._extract_text_from_response(content)

                # Should only have one source entry
                assert result.count("[Example]") == 1


class TestWebSearchAgentIntegration:
    """Integration tests for web search agent."""

    @pytest.mark.asyncio
    async def test_process_message_with_web_search(self, env_with_api_key):
        """Test processing a message with web search enabled."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                # Set up mock response with text
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                mock_response = MagicMock()
                mock_response.stop_reason = "end_turn"
                mock_response.content = [
                    TextBlock(type="text", text="Based on my web search, here is the answer.")
                ]
                mock_response.usage.input_tokens = 50
                mock_response.usage.output_tokens = 25
                mock_client.messages.create = AsyncMock(return_value=mock_response)

                # Set up MCP mock
                mock_mcp_instance = MagicMock()
                mock_mcp.return_value = mock_mcp_instance
                mock_mcp_instance.available_tools = {}
                mock_mcp_instance.connect = MagicMock()
                mock_mcp_instance.connect.return_value.__aenter__ = AsyncMock(
                    return_value=mock_mcp_instance
                )
                mock_mcp_instance.connect.return_value.__aexit__ = AsyncMock()

                agent = ConcreteAgent().create(enable_web_search=True)
                agent.mcp_client = mock_mcp_instance

                result = await agent.process_message("Search for Python news")

                assert "Based on my web search" in result

                # Verify web search tool was included in the API call
                call_args = mock_client.messages.create.call_args
                tools = call_args.kwargs["tools"]
                web_search_tools = [t for t in tools if t.get("type") == "web_search_20250305"]
                assert len(web_search_tools) == 1
