"""Tests for the backup model fallback module."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from agent_framework.core.backup_model import (
    call_backup_model,
    convert_messages_to_openai,
    convert_response_to_anthropic,
    convert_tools_to_openai,
)


class TestConvertMessagesToOpenAI:
    """Tests for Anthropic -> OpenAI message conversion."""

    def test_system_prompt_becomes_system_message(self):
        result = convert_messages_to_openai("You are helpful.", [])
        assert result == [{"role": "system", "content": "You are helpful."}]

    def test_empty_system_prompt_omitted(self):
        result = convert_messages_to_openai("", [{"role": "user", "content": "hi"}])
        assert result[0]["role"] == "user"

    def test_simple_user_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = convert_messages_to_openai("sys", messages)
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_user_message_with_content_blocks(self):
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello world"}],
            }
        ]
        result = convert_messages_to_openai("", messages)
        assert result[0]["content"] == "Hello world"

    def test_assistant_message_with_text(self):
        messages = [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "I can help."}],
            }
        ]
        result = convert_messages_to_openai("", messages)
        assert result[0] == {"role": "assistant", "content": "I can help."}

    def test_assistant_message_with_tool_use(self):
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "get_weather",
                        "input": {"city": "NYC"},
                    },
                ],
            }
        ]
        result = convert_messages_to_openai("", messages)
        msg = result[0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me check."
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["id"] == "toolu_123"
        assert msg["tool_calls"][0]["function"]["name"] == "get_weather"
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"city": "NYC"}

    def test_tool_result_message(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "72°F and sunny",
                    }
                ],
            }
        ]
        result = convert_messages_to_openai("", messages)
        assert result[0] == {
            "role": "tool",
            "tool_call_id": "toolu_123",
            "content": "72°F and sunny",
        }

    def test_tool_result_with_content_blocks(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_456",
                        "content": [{"type": "text", "text": "Result data"}],
                    }
                ],
            }
        ]
        result = convert_messages_to_openai("", messages)
        assert result[0]["content"] == "Result data"

    def test_full_conversation_round_trip(self):
        """Test a full conversation with user, assistant tool_use, and tool_result."""
        messages = [
            {"role": "user", "content": "What's the weather in NYC?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check the weather."},
                    {
                        "type": "tool_use",
                        "id": "toolu_abc",
                        "name": "get_weather",
                        "input": {"city": "NYC"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc",
                        "content": '{"temp": 72, "condition": "sunny"}',
                    }
                ],
            },
        ]
        result = convert_messages_to_openai("You are a weather bot.", messages)

        assert len(result) == 4  # system + user + assistant + tool
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[2]["role"] == "assistant"
        assert result[2]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert result[3]["role"] == "tool"
        assert result[3]["tool_call_id"] == "toolu_abc"


class TestConvertToolsToOpenAI:
    """Tests for Anthropic -> OpenAI tool definition conversion."""

    def test_basic_tool_conversion(self):
        tools = [
            {
                "name": "get_weather",
                "description": "Get the weather for a city",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ]
        result = convert_tools_to_openai(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"
        assert result[0]["function"]["description"] == "Get the weather for a city"
        assert result[0]["function"]["parameters"]["properties"]["city"]["type"] == "string"

    def test_skips_web_search_tool(self):
        tools = [
            {"type": "web_search_20250305", "name": "web_search"},
            {"name": "other_tool", "description": "A tool", "input_schema": {}},
        ]
        result = convert_tools_to_openai(tools)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "other_tool"

    def test_empty_tools(self):
        assert convert_tools_to_openai([]) == []


class TestConvertResponseToAnthropic:
    """Tests for OpenAI -> Anthropic response conversion."""

    def _make_response(
        self,
        content="Hello!",
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=20,
    ):
        """Build a mock LiteLLM response."""
        msg = MagicMock()
        msg.content = content
        msg.tool_calls = tool_calls

        choice = MagicMock()
        choice.finish_reason = finish_reason
        choice.message = msg

        usage = MagicMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens

        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        response.id = "chatcmpl-abc123"
        response.model = "gpt-4o"
        return response

    def test_text_response(self):
        response = self._make_response(content="Hello world!")
        result = convert_response_to_anthropic(response)

        assert isinstance(result, Message)
        assert result.stop_reason == "end_turn"
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "Hello world!"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 20

    def test_tool_call_response(self):
        tc = MagicMock()
        tc.id = "call_123"
        tc.function.name = "get_weather"
        tc.function.arguments = '{"city": "NYC"}'

        response = self._make_response(
            content=None,
            tool_calls=[tc],
            finish_reason="tool_calls",
        )
        result = convert_response_to_anthropic(response)

        assert result.stop_reason == "tool_use"
        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "get_weather"
        assert tool_blocks[0].input == {"city": "NYC"}
        assert tool_blocks[0].id == "call_123"

    def test_mixed_text_and_tool_response(self):
        tc = MagicMock()
        tc.id = "call_456"
        tc.function.name = "search"
        tc.function.arguments = '{"q": "test"}'

        response = self._make_response(
            content="Let me search for that.",
            tool_calls=[tc],
            finish_reason="tool_calls",
        )
        result = convert_response_to_anthropic(response)

        assert result.stop_reason == "tool_use"
        assert len(result.content) == 2
        assert isinstance(result.content[0], TextBlock)
        assert isinstance(result.content[1], ToolUseBlock)

    def test_length_stop_reason(self):
        response = self._make_response(finish_reason="length")
        result = convert_response_to_anthropic(response)
        assert result.stop_reason == "max_tokens"

    def test_empty_content_gets_fallback(self):
        response = self._make_response(content=None, tool_calls=None)
        result = convert_response_to_anthropic(response)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == ""


class TestCallBackupModel:
    """Tests for the main call_backup_model function."""

    @pytest.mark.asyncio
    async def test_non_streaming_call(self):
        mock_response = MagicMock()
        msg = MagicMock()
        msg.content = "Backup response"
        msg.tool_calls = None
        choice = MagicMock()
        choice.finish_reason = "stop"
        choice.message = msg
        usage = MagicMock()
        usage.prompt_tokens = 5
        usage.completion_tokens = 15
        mock_response.choices = [choice]
        mock_response.usage = usage
        mock_response.id = "backup-123"
        mock_response.model = "gpt-4o"

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            result = await call_backup_model(
                model="openai/gpt-4o",
                api_key="test-key",
                system_prompt="You are helpful.",
                messages=[{"role": "user", "content": "Hello"}],
                tools=[],
            )

            assert isinstance(result, Message)
            assert result.content[0].text == "Backup response"
            assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_streaming_call(self):
        # Build mock streaming chunks
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = MagicMock()
        chunk1.choices[0].delta.content = "Hello "
        chunk1.choices[0].delta.tool_calls = None
        chunk1.id = "stream-1"
        chunk1.model = "gpt-4o"
        chunk1.usage = None

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock()
        chunk2.choices[0].delta.content = "world!"
        chunk2.choices[0].delta.tool_calls = None
        chunk2.id = "stream-1"
        chunk2.model = "gpt-4o"
        chunk2.usage = MagicMock()
        chunk2.usage.prompt_tokens = 8
        chunk2.usage.completion_tokens = 12

        async def mock_stream():
            for chunk in [chunk1, chunk2]:
                yield chunk

        collected_text = []

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_stream()):
            result = await call_backup_model(
                model="openai/gpt-4o",
                api_key="test-key",
                system_prompt="You are helpful.",
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                on_text_delta=collected_text.append,
            )

            assert isinstance(result, Message)
            assert result.content[0].text == "Hello world!"
            assert collected_text == ["Hello ", "world!"]
            assert result.stop_reason == "end_turn"


class TestAgentFallbackIntegration:
    """Tests for the Agent._call_claude fallback path."""

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_connection_error(self, env_with_api_key):
        """Verify _call_claude falls back when Anthropic API has a connection error."""
        from anthropic import APIConnectionError

        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_cls:
            with patch("agent_framework.core.agent.MCPClient"):
                from agent_framework.core.agent import Agent

                class TestAgent(Agent):
                    def get_system_prompt(self) -> str:
                        return "test"

                    def get_agent_name(self) -> str:
                        return "TestAgent"

                    def get_greeting(self) -> str:
                        return "hi"

                agent = TestAgent(backup_model="openai/gpt-4o", backup_api_key="test")
                agent.messages = [{"role": "user", "content": "hello"}]

                # Make Anthropic client raise connection error
                mock_client = mock_cls.return_value
                mock_client.messages.create = AsyncMock(
                    side_effect=APIConnectionError(request=MagicMock())
                )

                # Mock the backup model call
                backup_msg = Message(
                    id="backup-1",
                    type="message",
                    role="assistant",
                    content=[TextBlock(type="text", text="Backup reply")],
                    model="gpt-4o",
                    stop_reason="end_turn",
                    stop_sequence=None,
                    usage=Usage(
                        input_tokens=5,
                        output_tokens=10,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0,
                    ),
                )

                with patch(
                    "agent_framework.core.backup_model.call_backup_model",
                    new_callable=AsyncMock,
                    return_value=backup_msg,
                ) as mock_backup:
                    result = await agent._call_claude(tools=[])

                    assert result.content[0].text == "Backup reply"
                    mock_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_500_error(self, env_with_api_key):
        """Verify _call_claude falls back on 500 server errors."""
        import httpx
        from anthropic import APIStatusError

        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_cls:
            with patch("agent_framework.core.agent.MCPClient"):
                from agent_framework.core.agent import Agent

                class TestAgent(Agent):
                    def get_system_prompt(self) -> str:
                        return "test"

                    def get_agent_name(self) -> str:
                        return "TestAgent"

                    def get_greeting(self) -> str:
                        return "hi"

                agent = TestAgent(backup_model="openai/gpt-4o", backup_api_key="test")
                agent.messages = [{"role": "user", "content": "hello"}]

                # Make Anthropic client raise 500 error
                mock_response = httpx.Response(
                    status_code=500, request=httpx.Request("POST", "https://api.anthropic.com")
                )
                mock_client = mock_cls.return_value
                mock_client.messages.create = AsyncMock(
                    side_effect=APIStatusError(
                        message="Internal Server Error",
                        response=mock_response,
                        body=None,
                    )
                )

                backup_msg = Message(
                    id="backup-2",
                    type="message",
                    role="assistant",
                    content=[TextBlock(type="text", text="Backup on 500")],
                    model="gpt-4o",
                    stop_reason="end_turn",
                    stop_sequence=None,
                    usage=Usage(
                        input_tokens=5,
                        output_tokens=10,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0,
                    ),
                )

                with patch(
                    "agent_framework.core.backup_model.call_backup_model",
                    new_callable=AsyncMock,
                    return_value=backup_msg,
                ) as mock_backup:
                    result = await agent._call_claude(tools=[])
                    assert result.content[0].text == "Backup on 500"

    @pytest.mark.asyncio
    async def test_no_fallback_on_auth_error(self, env_with_api_key):
        """Verify _call_claude does NOT fall back on 401 auth errors."""
        import httpx
        from anthropic import APIStatusError

        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_cls:
            with patch("agent_framework.core.agent.MCPClient"):
                from agent_framework.core.agent import Agent

                class TestAgent(Agent):
                    def get_system_prompt(self) -> str:
                        return "test"

                    def get_agent_name(self) -> str:
                        return "TestAgent"

                    def get_greeting(self) -> str:
                        return "hi"

                agent = TestAgent(backup_model="openai/gpt-4o", backup_api_key="test")
                agent.messages = [{"role": "user", "content": "hello"}]

                # Make Anthropic client raise 401 error
                mock_response = httpx.Response(
                    status_code=401, request=httpx.Request("POST", "https://api.anthropic.com")
                )
                mock_client = mock_cls.return_value
                mock_client.messages.create = AsyncMock(
                    side_effect=APIStatusError(
                        message="Unauthorized",
                        response=mock_response,
                        body=None,
                    )
                )

                with pytest.raises(APIStatusError):
                    await agent._call_claude(tools=[])

    @pytest.mark.asyncio
    async def test_no_fallback_when_backup_not_configured(self, env_with_api_key):
        """Verify _call_claude raises when no backup is configured."""
        from anthropic import APIConnectionError

        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_cls:
            with patch("agent_framework.core.agent.MCPClient"):
                with patch("agent_framework.core.agent.settings") as mock_settings:
                    mock_settings.backup_model = None
                    mock_settings.backup_api_key = None
                    mock_settings.log_dir = MagicMock()
                    mock_settings.log_dir.mkdir = MagicMock()
                    mock_settings.get_log_file = MagicMock(return_value="/tmp/test.log")

                    from agent_framework.core.agent import Agent

                    class TestAgent(Agent):
                        def get_system_prompt(self) -> str:
                            return "test"

                        def get_agent_name(self) -> str:
                            return "TestAgent"

                        def get_greeting(self) -> str:
                            return "hi"

                    agent = TestAgent()
                    agent.messages = [{"role": "user", "content": "hello"}]

                    mock_client = mock_cls.return_value
                    mock_client.messages.create = AsyncMock(
                        side_effect=APIConnectionError(request=MagicMock())
                    )

                    with pytest.raises(APIConnectionError):
                        await agent._call_claude(tools=[])

    @pytest.mark.asyncio
    async def test_use_backup_model_skips_anthropic(self, env_with_api_key):
        """Verify USE_BACKUP_MODEL=true routes directly to backup without calling Anthropic."""
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_cls:
            with patch("agent_framework.core.agent.MCPClient"):
                from agent_framework.core.agent import Agent

                class TestAgent(Agent):
                    def get_system_prompt(self) -> str:
                        return "test"

                    def get_agent_name(self) -> str:
                        return "TestAgent"

                    def get_greeting(self) -> str:
                        return "hi"

                agent = TestAgent(backup_model="openai/gpt-4o", backup_api_key="test")
                agent.use_backup_model = True
                agent.messages = [{"role": "user", "content": "hello"}]

                backup_msg = Message(
                    id="direct-backup",
                    type="message",
                    role="assistant",
                    content=[TextBlock(type="text", text="Direct backup response")],
                    model="gpt-4o",
                    stop_reason="end_turn",
                    stop_sequence=None,
                    usage=Usage(
                        input_tokens=5,
                        output_tokens=10,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=0,
                    ),
                )

                with patch(
                    "agent_framework.core.backup_model.call_backup_model",
                    new_callable=AsyncMock,
                    return_value=backup_msg,
                ) as mock_backup:
                    result = await agent._call_claude(tools=[])

                    assert result.content[0].text == "Direct backup response"
                    mock_backup.assert_called_once()

                    # Anthropic client should NOT have been called
                    mock_client = mock_cls.return_value
                    mock_client.messages.create.assert_not_called()
