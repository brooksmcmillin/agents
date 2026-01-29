"""Push-to-talk voice GUI for agent-framework agents.

This module provides a tkinter-based GUI that wraps an agent-framework Agent
with voice I/O capabilities via the VoiceAdapter.

Usage:
    uv run python gui.py

The GUI provides:
- Push-to-talk button (click and hold, or hold Space/Enter)
- Live conversation transcript display
- Status indicator showing current state
"""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tkinter import Event

from agent_framework import Agent
from dotenv import load_dotenv

from .voice_adapter import VoiceAdapter

load_dotenv()


# TTS-optimized system prompt
VOICE_SYSTEM_PROMPT = """You are being used in a voice conversation pipeline. Your responses will be
converted to speech via TTS.

Guidelines:
- Keep responses concise and conversational. Aim for 1-3 sentences unless
  more detail is explicitly requested.
- Avoid markdown formatting, bullet points, numbered lists, and code blocks.
- Don't use parenthetical asides or complex nested sentences.
- Avoid saying "here's a list" and then listing things - integrate information
  naturally into prose.
- The user's speech is being transcribed, so minor disfluencies or incomplete
  sentences are normal. Interpret intent generously.
- When discussing code, commands, or technical terms, optimize for TTS clarity:
  - Describe concepts rather than quoting exact syntax when possible.
  - For abbreviations, either expand them (zshrc -> "zsh config file") or add
    hyphens for pronunciation (compinit -> "comp-init").
  - Spell out symbols naturally: -U -> "dash U", -> -> "arrow", | -> "pipe".
  - If the user needs exact syntax, offer to spell it out or suggest they
    check documentation for the precise command."""


class VoiceAgent(Agent):
    """Agent with TTS-optimized system prompt for voice conversations."""

    def __init__(self, **kwargs: Any) -> None:
        # Default to no tools for simple voice conversations
        # Override mcp_server_path and allowed_tools if you want tool support
        super().__init__(**kwargs)

    def get_system_prompt(self) -> str:
        return VOICE_SYSTEM_PROMPT

    def get_greeting(self) -> str:
        return "Voice assistant ready."

    def get_agent_name(self) -> str:
        return "voice"


def create_gui(agent: Agent) -> None:
    """Create and run the voice assistant GUI.

    Args:
        agent: An agent-framework Agent instance to use for conversations.
    """
    root = tk.Tk()
    root.title("Voice Assistant")
    root.geometry("600x500")
    root.configure(bg="#1e1e1e")

    # Status label
    status_var = tk.StringVar(value="Ready - Hold button to speak")
    status_label = tk.Label(
        root,
        textvariable=status_var,
        font=("Helvetica", 12),
        fg="#888888",
        bg="#1e1e1e",
    )
    status_label.pack(pady=(10, 5))

    # Device info label
    device_var = tk.StringVar(value="")
    device_label = tk.Label(
        root,
        textvariable=device_var,
        font=("Helvetica", 9),
        fg="#666666",
        bg="#1e1e1e",
    )
    device_label.pack(pady=(0, 5))

    # Transcript display
    transcript_frame = tk.Frame(root, bg="#1e1e1e")
    transcript_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    transcript_label = tk.Label(
        transcript_frame,
        text="Conversation",
        font=("Helvetica", 11, "bold"),
        fg="#cccccc",
        bg="#1e1e1e",
        anchor="w",
    )
    transcript_label.pack(fill=tk.X)

    transcript_text = scrolledtext.ScrolledText(
        transcript_frame,
        wrap=tk.WORD,
        font=("Helvetica", 11),
        bg="#2d2d2d",
        fg="#ffffff",
        insertbackground="#ffffff",
        relief=tk.FLAT,
        padx=10,
        pady=10,
    )
    transcript_text.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
    transcript_text.configure(state=tk.DISABLED)

    # Configure text tags for styling
    transcript_text.tag_configure("user", foreground="#6eb5ff")
    transcript_text.tag_configure("assistant", foreground="#98c379")
    transcript_text.tag_configure("label", foreground="#888888")

    def append_transcript(role: str, text: str) -> None:
        transcript_text.configure(state=tk.NORMAL)
        if transcript_text.get("1.0", tk.END).strip():
            transcript_text.insert(tk.END, "\n\n")
        label = "You: " if role == "user" else "Assistant: "
        transcript_text.insert(tk.END, label, "label")
        transcript_text.insert(tk.END, text, role)
        transcript_text.see(tk.END)
        transcript_text.configure(state=tk.DISABLED)

    def on_user_transcript(text: str) -> None:
        root.after(0, lambda: append_transcript("user", text))

    def on_assistant_response(text: str) -> None:
        root.after(0, lambda: append_transcript("assistant", text))

    def on_status_change(status: str) -> None:
        root.after(0, lambda: status_var.set(status))

    # Create voice adapter wrapping the agent
    adapter = VoiceAdapter(
        agent=agent,
        on_user_transcript=on_user_transcript,
        on_assistant_response=on_assistant_response,
        on_status_change=on_status_change,
    )

    # Update device info display
    device_var.set(f"Input: {adapter.get_input_device_name()}")

    # Push-to-talk button
    button_frame = tk.Frame(root, bg="#1e1e1e")
    button_frame.pack(pady=20)

    talk_button = tk.Button(
        button_frame,
        text="Hold to Talk",
        font=("Helvetica", 14, "bold"),
        bg="#4a9eff",
        fg="white",
        activebackground="#3a8eef",
        activeforeground="white",
        relief=tk.FLAT,
        padx=40,
        pady=15,
        cursor="hand2",
    )
    talk_button.pack()

    hint_label = tk.Label(
        button_frame,
        text="Or hold Space / Enter",
        font=("Helvetica", 9),
        fg="#666666",
        bg="#1e1e1e",
    )
    hint_label.pack(pady=(5, 0))

    # Button state tracking
    button_held = False

    def start_talk(event: Event | None = None) -> None:  # noqa: ARG001
        nonlocal button_held
        if not button_held:
            button_held = True
            talk_button.configure(bg="#2d7ad4", text="Recording...")
            adapter.start_recording()

    def stop_talk(event: Event | None = None) -> None:  # noqa: ARG001
        nonlocal button_held
        if button_held:
            button_held = False
            talk_button.configure(bg="#4a9eff", text="Hold to Talk")
            adapter.stop_recording()

    # Bind mouse events
    talk_button.bind("<ButtonPress-1>", start_talk)
    talk_button.bind("<ButtonRelease-1>", stop_talk)

    # Bind keyboard events
    root.bind("<KeyPress-space>", start_talk)
    root.bind("<KeyRelease-space>", stop_talk)
    root.bind("<KeyPress-Return>", start_talk)
    root.bind("<KeyRelease-Return>", stop_talk)

    # Handle window close
    def on_closing() -> None:
        adapter.cleanup()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    root.mainloop()


if __name__ == "__main__":
    import os
    from pathlib import Path

    # Configure MCP server path - use the agents repo's MCP server
    # Adjust this path if your setup is different
    mcp_server_path = Path(__file__).parent.parent / "agents" / "mcp_server" / "server.py"

    if not mcp_server_path.exists():
        print(f"Warning: MCP server not found at {mcp_server_path}")
        print("The agent will work but won't have access to tools.")
        print("Set MCP_SERVER_PATH environment variable to override.")
        # Fall back to a non-existent path - agent will fail to get tools
        # but we handle this gracefully
        mcp_server_path = Path(os.getenv("MCP_SERVER_PATH", "mcp_server/server.py"))

    # Create the voice agent
    agent = VoiceAgent(
        mcp_server_path=str(mcp_server_path),
        model="claude-sonnet-4-20250514",
        enable_web_search=False,  # Not useful for voice
        allowed_tools=[],  # No tools by default - add tools here if needed
    )

    create_gui(agent)
