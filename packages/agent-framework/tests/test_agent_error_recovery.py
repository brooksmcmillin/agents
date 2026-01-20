"""Tests for Agent error recovery and edge cases.

This module tests error handling and recovery in the Agent class including:
- Tool execution failures and error handling
- API errors and graceful degradation
- Context management and trimming
- Max iterations safety
- Authentication errors in tool calls
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic.types import TextBlock, ToolUseBlock


class ConcreteAgent:
    """Concrete implementation of Agent for testing."""

    def __init__(self):
        from agent_framework.core.agent import Agent

        class _ConcreteAgent(Agent):
            def get_system_prompt(self) -> str:
                return "You are a test agent."

            def get_agent_name(self) -> str:
                return "TestAgent"

            def get_greeting(self) -> str:
                return "Hello, I am a test agent!"

        self._agent_class = _ConcreteAgent

    def create(self, *args, **kwargs):
        return self._agent_class(*args, **kwargs)


@pytest.fixture
def env_with_api_key(monkeypatch):
    """Set up environment with API key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key-12345")


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCP client."""
    mock_instance = MagicMock()
    mock_instance.available_tools = {}
    mock_instance.connect = MagicMock()
    mock_instance.connect.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.connect.return_value.__aexit__ = AsyncMock()
    mock_instance.call_tool = AsyncMock(return_value={"result": "ok"})
    mock_instance.get_available_tools = MagicMock(return_value=[])
    return mock_instance


class TestToolExecutionErrors:
    """Tests for tool execution error handling."""

    @pytest.mark.asyncio
    async def test_tool_failure_returns_error_to_claude(self, env_with_api_key, mock_mcp_client):
        """Test that tool failures are reported back to Claude for handling."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # First response: tool use
                tool_response = MagicMock()
                tool_response.stop_reason = "tool_use"
                tool_response.content = [
                    ToolUseBlock(
                        type="tool_use",
                        id="tool_123",
                        name="failing_tool",
                        input={"arg": "value"},
                    )
                ]
                tool_response.usage.input_tokens = 10
                tool_response.usage.output_tokens = 5

                # Second response: final text after seeing error
                final_response = MagicMock()
                final_response.stop_reason = "end_turn"
                final_response.content = [
                    TextBlock(type="text", text="I see the tool failed. Let me help another way.")
                ]
                final_response.usage.input_tokens = 15
                final_response.usage.output_tokens = 10

                mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client
                agent.tools = {"local": ["failing_tool"]}

                # Make tool fail
                mock_mcp_client.call_tool = AsyncMock(
                    side_effect=Exception("Tool execution failed: connection timeout")
                )

                result = await agent.process_message("Use the tool")

                # Agent should gracefully handle and Claude should respond
                assert "help another way" in result
                # Tool error should have been reported back to Claude
                assert mock_client.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_permission_error_in_tool(self, env_with_api_key, mock_mcp_client):
        """Test that permission errors are handled specially."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # First response: tool use
                tool_response = MagicMock()
                tool_response.stop_reason = "tool_use"
                tool_response.content = [
                    ToolUseBlock(
                        type="tool_use",
                        id="tool_123",
                        name="auth_tool",
                        input={},
                    )
                ]
                tool_response.usage.input_tokens = 10
                tool_response.usage.output_tokens = 5

                # Second response: handle auth error
                final_response = MagicMock()
                final_response.stop_reason = "end_turn"
                final_response.content = [
                    TextBlock(type="text", text="Authentication is required for this action.")
                ]
                final_response.usage.input_tokens = 15
                final_response.usage.output_tokens = 10

                mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client
                agent.tools = {"local": ["auth_tool"]}

                # Make tool fail with PermissionError
                mock_mcp_client.call_tool = AsyncMock(
                    side_effect=PermissionError("OAuth token expired")
                )

                result = await agent.process_message("Use auth tool")

                # Should handle auth error gracefully
                assert "Authentication" in result or "auth" in result.lower()

    @pytest.mark.asyncio
    async def test_multiple_tools_partial_failure(self, env_with_api_key, mock_mcp_client):
        """Test handling when some tools succeed and others fail."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # Response with multiple tool calls
                tool_response = MagicMock()
                tool_response.stop_reason = "tool_use"
                tool_response.content = [
                    ToolUseBlock(type="tool_use", id="tool_1", name="good_tool", input={}),
                    ToolUseBlock(type="tool_use", id="tool_2", name="bad_tool", input={}),
                ]
                tool_response.usage.input_tokens = 10
                tool_response.usage.output_tokens = 5

                final_response = MagicMock()
                final_response.stop_reason = "end_turn"
                final_response.content = [
                    TextBlock(type="text", text="First tool worked, second failed.")
                ]
                final_response.usage.input_tokens = 15
                final_response.usage.output_tokens = 10

                mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client
                agent.tools = {"local": ["good_tool", "bad_tool"]}

                # Track calls and selectively fail
                call_count = 0

                async def selective_failure(name, args):
                    nonlocal call_count
                    call_count += 1
                    if name == "bad_tool":
                        raise Exception("Tool failed")
                    return {"result": "success"}

                # Mock _call_mcp_tool_with_reconnect directly to bypass routing
                agent._call_mcp_tool_with_reconnect = selective_failure

                result = await agent.process_message("Use both tools")

                # Both tools should have been attempted
                assert call_count == 2
                # Agent should report mixed results
                assert "worked" in result or "failed" in result


class TestAPIErrors:
    """Tests for Anthropic API error handling."""

    @pytest.mark.asyncio
    async def test_api_error_returns_user_friendly_message(self, env_with_api_key, mock_mcp_client):
        """Test that API errors return a user-friendly message."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client
                mock_client.messages.create = AsyncMock(
                    side_effect=Exception("API rate limit exceeded")
                )

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                result = await agent.process_message("Hello")

                assert "encountered an error" in result
                assert "rate limit" in result or "API" in result

    @pytest.mark.asyncio
    async def test_network_error_handling(self, env_with_api_key, mock_mcp_client):
        """Test handling of network errors."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client
                mock_client.messages.create = AsyncMock(
                    side_effect=ConnectionError("Network unreachable")
                )

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                result = await agent.process_message("Hello")

                assert "encountered an error" in result

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self, env_with_api_key, mock_mcp_client):
        """Test handling of timeout errors."""

        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client
                mock_client.messages.create = AsyncMock(
                    side_effect=TimeoutError("Request timed out")
                )

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                result = await agent.process_message("Hello")

                assert "encountered an error" in result


class TestMaxIterationsSafety:
    """Tests for max iterations safety mechanism."""

    @pytest.mark.asyncio
    async def test_max_iterations_prevents_infinite_loop(self, env_with_api_key, mock_mcp_client):
        """Test that max iterations prevents infinite tool loops."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # Always return tool_use - should hit max iterations
                mock_response = MagicMock()
                mock_response.stop_reason = "tool_use"
                mock_response.content = [
                    ToolUseBlock(
                        type="tool_use",
                        id="tool_infinite",
                        name="loop_tool",
                        input={},
                    )
                ]
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5

                mock_client.messages.create = AsyncMock(return_value=mock_response)

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client
                agent.tools = {"local": ["loop_tool"]}
                agent._call_mcp_tool_with_reconnect = AsyncMock(return_value={"result": "ok"})

                result = await agent.process_message("Loop forever")

                # Should stop at MAX_AGENT_ITERATIONS (10)
                assert mock_client.messages.create.call_count == 10
                assert "having trouble completing" in result

    @pytest.mark.asyncio
    async def test_iteration_count_resets_between_messages(self, env_with_api_key, mock_mcp_client):
        """Test that iteration count resets for each new message."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # First message: normal response
                response1 = MagicMock()
                response1.stop_reason = "end_turn"
                response1.content = [TextBlock(type="text", text="Response 1")]
                response1.usage.input_tokens = 10
                response1.usage.output_tokens = 5

                # Second message: also normal
                response2 = MagicMock()
                response2.stop_reason = "end_turn"
                response2.content = [TextBlock(type="text", text="Response 2")]
                response2.usage.input_tokens = 10
                response2.usage.output_tokens = 5

                mock_client.messages.create = AsyncMock(side_effect=[response1, response2])

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                result1 = await agent.process_message("Message 1")
                result2 = await agent.process_message("Message 2")

                assert result1 == "Response 1"
                assert result2 == "Response 2"
                # Each message should get its own iteration count
                assert mock_client.messages.create.call_count == 2


class TestContextManagement:
    """Tests for context trimming and memory injection."""

    @pytest.mark.asyncio
    async def test_context_trimming_removes_old_messages(self, env_with_api_key, mock_mcp_client):
        """Test that context trimming removes oldest messages."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                mock_response = MagicMock()
                mock_response.stop_reason = "end_turn"
                mock_response.content = [TextBlock(type="text", text="Response")]
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5

                mock_client.messages.create = AsyncMock(return_value=mock_response)

                mock_mcp.return_value = mock_mcp_client

                # Create agent with small context limit
                agent = ConcreteAgent().create(max_context_messages=5)
                agent.mcp_client = mock_mcp_client

                # Add many messages
                for i in range(10):
                    await agent.process_message(f"Message {i}")

                # Should have trimmed to max_context_messages
                # Each process_message adds 2 messages (user + assistant)
                # After trimming, should be around max_context_messages
                assert len(agent.messages) <= 7  # Some buffer for timing

    @pytest.mark.asyncio
    async def test_context_trimming_disabled(self, env_with_api_key, mock_mcp_client):
        """Test that context trimming can be disabled."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                mock_response = MagicMock()
                mock_response.stop_reason = "end_turn"
                mock_response.content = [TextBlock(type="text", text="Response")]
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5

                mock_client.messages.create = AsyncMock(return_value=mock_response)

                mock_mcp.return_value = mock_mcp_client

                # Create agent with trimming disabled
                agent = ConcreteAgent().create(max_context_messages=None)
                agent.mcp_client = mock_mcp_client

                # Add many messages
                for i in range(10):
                    await agent.process_message(f"Message {i}")

                # Should keep all messages (20 = 10 user + 10 assistant)
                assert len(agent.messages) == 20

    def test_get_context_stats(self, env_with_api_key, mock_mcp_client):
        """Test context statistics reporting."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create(max_context_messages=30)
                agent.mcp_client = mock_mcp_client

                # Add some messages manually
                agent.messages = [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                    {"role": "user", "content": "How are you?"},
                    {"role": "assistant", "content": "I'm doing well."},
                ]

                stats = agent.get_context_stats()

                assert stats["total_messages"] == 4
                assert stats["user_messages"] == 2
                assert stats["assistant_messages"] == 2
                assert stats["max_messages"] == 30
                assert "estimated_context_tokens" in stats


class TestUnexpectedStopReasons:
    """Tests for handling unexpected API response stop reasons."""

    @pytest.mark.asyncio
    async def test_unexpected_stop_reason_handled(self, env_with_api_key, mock_mcp_client):
        """Test handling of unexpected stop reasons."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                mock_response = MagicMock()
                mock_response.stop_reason = "max_tokens"  # Unusual stop reason
                mock_response.content = [TextBlock(type="text", text="Partial response...")]
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5

                mock_client.messages.create = AsyncMock(return_value=mock_response)

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                result = await agent.process_message("Hello")

                # Should still return the partial response
                assert result == "Partial response..."

    @pytest.mark.asyncio
    async def test_tool_use_without_tools_handled(self, env_with_api_key, mock_mcp_client):
        """Test handling tool_use stop reason with no actual tools in response."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                mock_response = MagicMock()
                mock_response.stop_reason = "tool_use"
                mock_response.content = [
                    TextBlock(type="text", text="I was going to use a tool but...")
                ]  # No actual ToolUseBlock
                mock_response.usage.input_tokens = 10
                mock_response.usage.output_tokens = 5

                mock_client.messages.create = AsyncMock(return_value=mock_response)

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                result = await agent.process_message("Use a tool")

                # Should return the text even though stop_reason was tool_use
                assert "I was going to use a tool" in result


class TestInvalidToolName:
    """Tests for handling invalid tool names."""

    @pytest.mark.asyncio
    async def test_invalid_tool_name_raises_error(self, env_with_api_key, mock_mcp_client):
        """Test that calling an invalid tool name is handled."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_anthropic:
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_client = AsyncMock()
                mock_anthropic.return_value = mock_client

                # Response requesting a tool that doesn't exist
                tool_response = MagicMock()
                tool_response.stop_reason = "tool_use"
                tool_response.content = [
                    ToolUseBlock(
                        type="tool_use",
                        id="tool_123",
                        name="nonexistent_tool",
                        input={},
                    )
                ]
                tool_response.usage.input_tokens = 10
                tool_response.usage.output_tokens = 5

                final_response = MagicMock()
                final_response.stop_reason = "end_turn"
                final_response.content = [TextBlock(type="text", text="The tool was not found.")]
                final_response.usage.input_tokens = 15
                final_response.usage.output_tokens = 10

                mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])

                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client
                agent.tools = {"local": []}  # No tools available

                result = await agent.process_message("Use a tool")

                # Should handle the error and Claude should respond
                assert "not found" in result.lower() or mock_client.messages.create.call_count == 2


class TestConversationReset:
    """Tests for conversation reset functionality."""

    def test_reset_clears_messages(self, env_with_api_key, mock_mcp_client):
        """Test that reset_conversation clears message history."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                # Add some messages
                agent.messages = [
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi!"},
                ]

                agent.reset_conversation()

                assert len(agent.messages) == 0

    def test_reset_preserves_token_counts(self, env_with_api_key, mock_mcp_client):
        """Test that reset doesn't clear token usage stats."""
        with patch("agent_framework.core.agent.AsyncAnthropic"):
            with patch("agent_framework.core.agent.MCPClient") as mock_mcp:
                mock_mcp.return_value = mock_mcp_client

                agent = ConcreteAgent().create()
                agent.mcp_client = mock_mcp_client

                agent.total_input_tokens = 1000
                agent.total_output_tokens = 500

                agent.reset_conversation()

                # Token counts should be preserved for session tracking
                assert agent.total_input_tokens == 1000
                assert agent.total_output_tokens == 500
