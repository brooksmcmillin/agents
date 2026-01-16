#!/usr/bin/env python3
"""CLI runner for agents with voice I/O via chasm.

This script wraps any agent from the registry with the VoiceAdapter from
the chasm library, providing push-to-talk voice interaction.

Usage:
    uv run python run_voice_agent.py chatbot      # Voice chatbot
    uv run python run_voice_agent.py pr           # Voice PR agent
    uv run python run_voice_agent.py --list       # List available agents

Requires:
    - chasm library installed (uv pip install -e ../chasm)
    - ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY in .env
"""

import argparse
import os
import sys
from pathlib import Path

# Add chasm to path
chasm_path = Path(__file__).parent.parent / "chasm" / "src"
if chasm_path.exists():
    sys.path.insert(0, str(chasm_path))

try:
    from chasm.gui import create_gui
    from chasm.voice_adapter import VoiceAdapter
except ImportError as e:
    print(f"Error: Could not import chasm library: {e}")
    print("\nMake sure chasm is installed:")
    print("  cd ../chasm && uv pip install -e .")
    sys.exit(1)

from agents.business_advisor.main import BusinessAdvisorAgent
from agents.chatbot.main import ChatbotAgent
from agents.pr_agent.main import PRAgent
from agents.security_researcher.main import SecurityResearcherAgent
from agents.task_manager.main import TaskManagerAgent
from shared import DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL

# Registry of available agents (same as run_agent.py)
AGENTS: dict[str, tuple[type, dict | None]] = {
    "chatbot": (ChatbotAgent, None),
    "pr": (PRAgent, None),
    "tasks": (
        TaskManagerAgent,
        {
            "mcp_urls": [os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)],
            "mcp_client_config": {
                "prefer_device_flow": True,
            },
        },
    ),
    "security": (SecurityResearcherAgent, None),
    "business": (
        BusinessAdvisorAgent,
        {
            "mcp_urls": ["https://api.githubcopilot.com/mcp/"],
            "mcp_client_config": {
                "auth_token": os.getenv("GITHUB_MCP_PAT"),
            },
        },
    ),
}

# Voice-optimized system prompt additions
VOICE_PROMPT_ADDITION = """
## Voice Conversation Guidelines

You are being used in a voice conversation pipeline. Your responses will be
converted to speech via TTS.

- Keep responses concise and conversational. Aim for 1-3 sentences unless
  more detail is explicitly requested.
- Avoid markdown formatting, bullet points, numbered lists, and code blocks.
- Don't use parenthetical asides or complex nested sentences.
- Avoid saying "here's a list" and then listing things - integrate information
  naturally into prose.
- The user's speech is being transcribed, so minor disfluencies or incomplete
  sentences are normal. Interpret intent generously.
- When discussing code or technical terms, optimize for TTS clarity by
  describing concepts rather than quoting exact syntax when possible.
"""


def list_agents() -> None:
    """Print available agents."""
    print("Available agents:")
    for name in AGENTS:
        print(f"  • {name}")


def create_voice_agent(agent_name: str) -> object:
    """Instantiate an agent from the registry with voice-optimized prompt.

    Args:
        agent_name: Name of the agent from AGENTS registry.

    Returns:
        Agent instance ready for voice interaction.
    """
    if agent_name not in AGENTS:
        print(f"Error: Unknown agent '{agent_name}'")
        print("Run with --list to see available agents")
        sys.exit(1)

    agent_class, agent_kwargs = AGENTS[agent_name]

    # Instantiate agent
    if agent_kwargs:
        agent = agent_class(**agent_kwargs)
    else:
        agent = agent_class()

    # Modify system prompt to add voice guidance
    original_prompt = agent.get_system_prompt()

    # Create a wrapper that adds voice guidance
    class VoiceOptimizedAgent(agent.__class__):
        def get_system_prompt(self) -> str:
            return original_prompt + VOICE_PROMPT_ADDITION

    # Replace agent's class (preserving all instance state)
    agent.__class__ = VoiceOptimizedAgent

    return agent


def main() -> None:
    """Parse arguments and run the specified agent with voice I/O."""
    parser = argparse.ArgumentParser(
        description="Run a specific agent with voice I/O from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run python run_voice_agent.py chatbot    # Voice chatbot
    uv run python run_voice_agent.py pr         # Voice PR agent
    uv run python run_voice_agent.py --list     # List available agents

Requirements:
    - ANTHROPIC_API_KEY in .env
    - DEEPGRAM_API_KEY in .env
    - CARTESIA_API_KEY in .env
""",
    )
    parser.add_argument(
        "agent",
        nargs="?",
        choices=list(AGENTS.keys()),
        help="Agent to run with voice I/O",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available agents",
    )

    args = parser.parse_args()

    if args.list:
        list_agents()
        return

    if not args.agent:
        parser.print_help()
        sys.exit(1)

    # Create voice-optimized agent
    print(f"Starting {args.agent} agent with voice I/O...")
    agent = create_voice_agent(args.agent)

    # Launch GUI with voice adapter
    print("\nVoice assistant ready!")
    print("Hold the button or press Space/Enter to talk.\n")

    try:
        create_gui(agent)
    except Exception as e:
        print(f"\n❌ Error creating GUI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
