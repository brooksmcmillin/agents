"""Backup model fallback via LiteLLM.

When the Anthropic API is unavailable, this module provides a fallback path
that routes requests through LiteLLM to any supported provider (OpenAI,
Google, Groq, etc.) and converts responses back to Anthropic SDK types so
the rest of the agent code is unaffected.

The conversion handles:
- System prompts
- Multi-turn conversations with text and tool_use/tool_result blocks
- Tool definitions (Anthropic format -> OpenAI function-calling format)
- Streaming via callback
- Response mapping back to anthropic.types.Message
"""

import json
import logging
import uuid
from typing import Any, cast

from anthropic.types import (
    Message,
    TextBlock,
    ToolUseBlock,
    Usage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Anthropic -> OpenAI message conversion
# ---------------------------------------------------------------------------


def _convert_content_blocks_to_openai(content: list[Any] | str) -> str | list[dict[str, Any]]:
    """Convert Anthropic content blocks to OpenAI message content.

    Simple text-only content is returned as a plain string.
    Mixed content (text + images, etc.) returns a list of content parts.
    """
    if isinstance(content, str):
        return content

    texts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                texts.append(block["text"])
            elif block.get("type") == "tool_use":
                # Tool use blocks are handled separately as tool_calls
                continue
            elif block.get("type") == "tool_result":
                # Tool results are handled as separate messages
                continue
        elif isinstance(block, TextBlock):
            texts.append(block.text)

    return "\n".join(texts) if texts else ""


def _extract_tool_calls_from_content(content: list[Any]) -> list[dict[str, Any]]:
    """Extract tool_use blocks from Anthropic content and convert to OpenAI tool_calls."""
    tool_calls = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"]),
                    },
                }
            )
        elif isinstance(block, ToolUseBlock):
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                }
            )
    return tool_calls


def convert_messages_to_openai(
    system_prompt: str,
    messages: list[Any],
) -> list[dict[str, Any]]:
    """Convert Anthropic-format messages to OpenAI-format messages.

    Handles:
    - System prompt -> system message
    - User messages (text or content blocks)
    - Assistant messages with text and/or tool_use blocks
    - User messages containing tool_result blocks

    Args:
        system_prompt: The system prompt text.
        messages: Anthropic-format message list.

    Returns:
        OpenAI-format message list.
    """
    openai_messages: list[dict[str, Any]] = []

    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            # Check if content contains tool_result blocks
            if isinstance(content, list):
                tool_results = [
                    b for b in content if (isinstance(b, dict) and b.get("type") == "tool_result")
                ]
                if tool_results:
                    # Convert each tool_result to a separate tool message
                    for tr in tool_results:
                        result_content = tr.get("content", "")
                        if isinstance(result_content, list):
                            # Extract text from content blocks
                            parts = []
                            for part in result_content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    parts.append(part["text"])
                            result_content = "\n".join(parts) if parts else ""
                        openai_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr["tool_use_id"],
                                "content": str(result_content),
                            }
                        )
                    continue

            # Regular user message
            openai_messages.append(
                {
                    "role": "user",
                    "content": _convert_content_blocks_to_openai(content),
                }
            )

        elif role == "assistant":
            assistant_msg: dict[str, Any] = {"role": "assistant"}

            if isinstance(content, list):
                tool_calls = _extract_tool_calls_from_content(content)
                text = _convert_content_blocks_to_openai(content)
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                    if text:
                        assistant_msg["content"] = text
                    else:
                        assistant_msg["content"] = None
                else:
                    assistant_msg["content"] = text
            else:
                assistant_msg["content"] = content

            openai_messages.append(assistant_msg)

    return openai_messages


# ---------------------------------------------------------------------------
# Tool definition conversion
# ---------------------------------------------------------------------------


def convert_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic tool definitions to OpenAI function-calling format.

    Anthropic format:
        {"name": "...", "description": "...", "input_schema": {...}}

    OpenAI format:
        {"type": "function", "function": {"name": "...", "description": "...",
         "parameters": {...}}}

    Args:
        tools: Anthropic-format tool list.

    Returns:
        OpenAI-format tool list.
    """
    openai_tools: list[dict[str, Any]] = []
    for tool in tools:
        # Skip web search tool type (Anthropic-specific)
        if tool.get("type") in ("web_search_20250305",):
            continue
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            }
        )
    return openai_tools


# ---------------------------------------------------------------------------
# OpenAI response -> Anthropic Message conversion
# ---------------------------------------------------------------------------


def convert_response_to_anthropic(response: Any) -> Message:
    """Convert a LiteLLM/OpenAI response to an Anthropic Message.

    Maps:
    - choices[0].message.content -> TextBlock
    - choices[0].message.tool_calls -> ToolUseBlock(s)
    - finish_reason "tool_calls" -> stop_reason "tool_use"
    - finish_reason "stop" -> stop_reason "end_turn"
    - usage -> Usage

    Args:
        response: LiteLLM ModelResponse object.

    Returns:
        Anthropic Message with equivalent content.
    """
    choice = response.choices[0]
    finish_reason = choice.finish_reason
    message = choice.message

    # Build content blocks
    content: list[TextBlock | ToolUseBlock] = []

    if message.content:
        content.append(TextBlock(type="text", text=message.content))

    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                arguments = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            content.append(
                ToolUseBlock(
                    type="tool_use",
                    id=tc.id or f"toolu_{uuid.uuid4().hex[:24]}",
                    name=tc.function.name,
                    input=arguments,
                )
            )

    # If no content at all, add an empty text block
    if not content:
        content.append(TextBlock(type="text", text=""))

    # Map stop reason
    if finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"

    # Map usage
    usage_data = response.usage
    usage = Usage(
        input_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    return Message(
        id=response.id or f"msg_{uuid.uuid4().hex[:24]}",
        type="message",
        role="assistant",
        content=cast(Any, content),
        model=response.model or "backup-model",
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Main fallback call
# ---------------------------------------------------------------------------


async def call_backup_model(
    *,
    model: str,
    api_key: str | None,
    system_prompt: str,
    messages: list[Any],
    tools: list[Any],
    max_tokens: int = 16000,
    on_text_delta: Any | None = None,
) -> Message:
    """Call a backup model via LiteLLM and return an Anthropic-compatible Message.

    This is the main entry point for the fallback path. It:
    1. Converts messages and tools from Anthropic to OpenAI format
    2. Calls the model via LiteLLM (streaming or blocking)
    3. Converts the response back to an Anthropic Message

    Args:
        model: LiteLLM model identifier (e.g. "openai/gpt-4o").
        api_key: API key for the provider.
        system_prompt: System prompt text.
        messages: Anthropic-format message list.
        tools: Anthropic-format tool definitions.
        max_tokens: Maximum output tokens.
        on_text_delta: Optional streaming callback. If provided, text chunks
            are streamed via this callback.

    Returns:
        Anthropic Message with the backup model's response.
    """
    import litellm  # Lazy import to avoid load-time cost when not needed

    # Suppress LiteLLM's verbose logging
    litellm.suppress_debug_info = True

    openai_messages = convert_messages_to_openai(system_prompt, messages)
    openai_tools = convert_tools_to_openai(tools) if tools else None

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": max_tokens,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if openai_tools:
        kwargs["tools"] = openai_tools

    if on_text_delta is not None:
        # Streaming mode: collect chunks, fire callback for text
        kwargs["stream"] = True
        collected_content = ""
        collected_tool_calls: list[dict[str, Any]] = []
        prompt_tokens = 0
        completion_tokens = 0
        response_id = f"msg_{uuid.uuid4().hex[:24]}"
        response_model = model

        stream = await litellm.acompletion(**kwargs)
        async for chunk in cast(Any, stream):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Stream text content
            if delta and delta.content:
                collected_content += delta.content
                on_text_delta(delta.content)

            # Accumulate tool calls
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if hasattr(tc, "index") else 0
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append(
                            {"id": "", "function": {"name": "", "arguments": ""}}
                        )
                    if tc.id:
                        collected_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            collected_tool_calls[idx]["function"]["name"] = tc.function.name
                        if tc.function.arguments:
                            collected_tool_calls[idx]["function"]["arguments"] += (
                                tc.function.arguments
                            )

            # Capture usage from the final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0

            if hasattr(chunk, "id") and chunk.id:
                response_id = chunk.id
            if hasattr(chunk, "model") and chunk.model:
                response_model = chunk.model

        # Build Anthropic Message from collected data
        content: list[TextBlock | ToolUseBlock] = []
        if collected_content:
            content.append(TextBlock(type="text", text=collected_content))

        for tc_data in collected_tool_calls:
            try:
                arguments = json.loads(tc_data["function"]["arguments"])
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            content.append(
                ToolUseBlock(
                    type="tool_use",
                    id=tc_data["id"] or f"toolu_{uuid.uuid4().hex[:24]}",
                    name=tc_data["function"]["name"],
                    input=arguments,
                )
            )

        if not content:
            content.append(TextBlock(type="text", text=""))

        stop_reason = "tool_use" if collected_tool_calls else "end_turn"

        return Message(
            id=response_id,
            type="message",
            role="assistant",
            content=cast(Any, content),
            model=response_model,
            stop_reason=stop_reason,
            stop_sequence=None,
            usage=Usage(
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
        )

    else:
        # Non-streaming mode
        response = await litellm.acompletion(**kwargs)
        return convert_response_to_anthropic(response)
