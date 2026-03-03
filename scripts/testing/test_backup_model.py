#!/usr/bin/env python3
"""Live integration test for the backup model fallback.

Verifies that the backup model can handle real requests end-to-end,
including text generation and tool calling, by calling the configured
BACKUP_MODEL provider via LiteLLM.

Requires BACKUP_MODEL and BACKUP_API_KEY to be set in .env or environment.

Usage:
    # Run all checks (text + tool calling)
    uv run python scripts/testing/test_backup_model.py

    # Text generation only
    uv run python scripts/testing/test_backup_model.py --text-only

    # Simulate a full agent fallback (forces Anthropic failure)
    uv run python scripts/testing/test_backup_model.py --simulate-fallback
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Ensure project root for imports
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def _check_config() -> tuple[str, str | None]:
    """Validate that backup model is configured."""
    from agent_framework.core.config import settings

    model = settings.backup_model
    api_key = settings.backup_api_key
    if not model:
        print("ERROR: BACKUP_MODEL is not set in .env or environment.")
        print("Example: BACKUP_MODEL=openai/gpt-4o")
        sys.exit(1)
    return model, api_key


async def test_text_generation(model: str, api_key: str | None) -> bool:
    """Test basic text generation via the backup model."""
    from agent_framework.core.backup_model import call_backup_model

    print(f"\n--- Test 1: Text generation ({model}) ---")
    start = time.monotonic()
    try:
        result = await call_backup_model(
            model=model,
            api_key=api_key,
            system_prompt="You are a helpful assistant. Reply in one short sentence.",
            messages=[{"role": "user", "content": "What is 2 + 2?"}],
            tools=[],
            max_tokens=100,
        )
        elapsed = time.monotonic() - start
        text = result.content[0].text if result.content else "(empty)"
        print(f"  Response: {text}")
        print(f"  Tokens: {result.usage.input_tokens} in / {result.usage.output_tokens} out")
        print(f"  Latency: {elapsed:.2f}s")
        print(f"  Stop reason: {result.stop_reason}")
        print("  PASS")
        return True
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  FAIL ({elapsed:.2f}s): {type(e).__name__}: {e}")
        return False


async def test_streaming(model: str, api_key: str | None) -> bool:
    """Test streaming text generation."""
    from agent_framework.core.backup_model import call_backup_model

    print(f"\n--- Test 2: Streaming ({model}) ---")
    chunks: list[str] = []
    start = time.monotonic()
    try:
        result = await call_backup_model(
            model=model,
            api_key=api_key,
            system_prompt="Reply in one sentence.",
            messages=[{"role": "user", "content": "Say hello."}],
            tools=[],
            max_tokens=100,
            on_text_delta=chunks.append,
        )
        elapsed = time.monotonic() - start
        full_text = "".join(chunks)
        print(f"  Chunks received: {len(chunks)}")
        print(f"  Full response: {full_text}")
        print(f"  Latency: {elapsed:.2f}s")

        if len(chunks) == 0:
            print("  FAIL: No streaming chunks received")
            return False

        # Verify the final Message matches
        msg_text = result.content[0].text if result.content else ""
        if msg_text != full_text:
            print(
                f"  WARNING: Message text doesn't match chunks ({len(msg_text)} vs {len(full_text)} chars)"
            )

        print("  PASS")
        return True
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  FAIL ({elapsed:.2f}s): {type(e).__name__}: {e}")
        return False


async def test_tool_calling(model: str, api_key: str | None) -> bool:
    """Test that the backup model can generate tool calls."""
    from agent_framework.core.backup_model import call_backup_model
    from anthropic.types import ToolUseBlock

    print(f"\n--- Test 3: Tool calling ({model}) ---")
    tools = [
        {
            "name": "get_weather",
            "description": "Get current weather for a city. Always use this tool when asked about weather.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        }
    ]
    start = time.monotonic()
    try:
        result = await call_backup_model(
            model=model,
            api_key=api_key,
            system_prompt="You are a weather assistant. Use the get_weather tool to answer weather questions.",
            messages=[{"role": "user", "content": "What's the weather in Paris?"}],
            tools=tools,
            max_tokens=200,
        )
        elapsed = time.monotonic() - start
        print(f"  Stop reason: {result.stop_reason}")
        print(f"  Latency: {elapsed:.2f}s")

        tool_blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        if tool_blocks:
            for tb in tool_blocks:
                print(f"  Tool call: {tb.name}({tb.input})")
            print("  PASS")
            return True
        else:
            text = result.content[0].text if result.content else "(empty)"
            print(f"  No tool call generated. Response: {text[:200]}")
            print("  FAIL: Expected tool_use but got text response")
            return False
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  FAIL ({elapsed:.2f}s): {type(e).__name__}: {e}")
        return False


async def test_simulate_fallback(model: str, api_key: str | None) -> bool:
    """Simulate a full agent fallback by forcing the Anthropic client to fail."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from anthropic import APIConnectionError

    print(f"\n--- Test 4: Full agent fallback simulation ({model}) ---")
    start = time.monotonic()
    try:
        with patch("agent_framework.core.agent.AsyncAnthropic") as mock_cls:
            with patch("agent_framework.core.agent.MCPClient"):
                from agent_framework.core.agent import Agent

                class FallbackTestAgent(Agent):
                    def get_system_prompt(self) -> str:
                        return "You are a test agent. Reply briefly."

                    def get_agent_name(self) -> str:
                        return "FallbackTestAgent"

                    def get_greeting(self) -> str:
                        return "hi"

                agent = FallbackTestAgent(
                    backup_model=model,
                    backup_api_key=api_key,
                )
                agent.messages = [
                    {"role": "user", "content": "Say 'fallback works' if you can read this."}
                ]

                # Force Anthropic to fail
                mock_client = mock_cls.return_value
                mock_client.messages.create = AsyncMock(
                    side_effect=APIConnectionError(request=MagicMock())
                )

                result = await agent._call_claude(tools=[])

        elapsed = time.monotonic() - start
        text = result.content[0].text if result.content else "(empty)"
        print(f"  Response: {text[:200]}")
        print(f"  Model: {result.model}")
        print(f"  Latency: {elapsed:.2f}s")
        print("  PASS")
        return True
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  FAIL ({elapsed:.2f}s): {type(e).__name__}: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Test backup model fallback")
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Only test text generation (skip tool calling)",
    )
    parser.add_argument(
        "--simulate-fallback",
        action="store_true",
        help="Simulate a full agent fallback with forced Anthropic failure",
    )
    args = parser.parse_args()

    model, api_key = _check_config()
    print(f"Backup model: {model}")

    results: list[tuple[str, bool]] = []

    if args.simulate_fallback:
        ok = await test_simulate_fallback(model, api_key)
        results.append(("Fallback simulation", ok))
    else:
        ok = await test_text_generation(model, api_key)
        results.append(("Text generation", ok))

        ok = await test_streaming(model, api_key)
        results.append(("Streaming", ok))

        if not args.text_only:
            ok = await test_tool_calling(model, api_key)
            results.append(("Tool calling", ok))

    # Summary
    print("\n=== Summary ===")
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\nAll tests passed.")
    else:
        print("\nSome tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
