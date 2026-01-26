# Voice-Enabled Agents

This document describes how to run agents with voice I/O using the chasm audio pipeline.

## Overview

The agents repository now includes:
1. **Chatbot Agent** (`agents/chatbot/`) - A simple, general-purpose Claude chatbot with all MCP tools enabled
2. **Voice Agent Runner** (`bin/run-voice-agent`) - Wraps any agent with the chasm VoiceAdapter for voice interaction

## Quick Start

### Running the Chatbot (Text)

```bash
# List available agents
uv run bin/run-agent --list

# Run the chatbot with text I/O
uv run bin/run-agent chatbot
```

### Running with Voice I/O

```bash
# List agents available for voice mode
uv run bin/run-voice-agent --list

# Run the chatbot with voice I/O
uv run bin/run-voice-agent chatbot

# Or run any other agent with voice
uv run bin/run-voice-agent pr
uv run bin/run-voice-agent security
```

## Requirements

Voice mode requires additional API keys in your `.env` file:

```bash
# Required for all agents
ANTHROPIC_API_KEY=your_key_here

# Required for voice mode
DEEPGRAM_API_KEY=your_key_here  # Speech-to-text
CARTESIA_API_KEY=your_key_here  # Text-to-speech
```

## Architecture

### Chatbot Agent

The chatbot agent is a minimal wrapper around the agent-framework's `Agent` class:

- **Location**: `agents/chatbot/`
- **Tools**: All MCP tools enabled (no restrictions)
- **Purpose**: General-purpose conversational AI with access to:
  - Web content fetching and analysis
  - Persistent memory (save/retrieve/search)
  - Document search
  - Social media stats
  - Content suggestions
  - Slack notifications

### Voice Integration

The voice integration uses the `chasm` library's `VoiceAdapter`:

```
User Voice → PyAudio → Deepgram (STT) → Agent (Claude + MCP Tools) → Cartesia (TTS) → PyAudio → Speaker
                                              ↓
                                         MCP Server
                                         (All Tools)
```

**Key Components:**

1. **VoiceAdapter** (`chasm/src/chasm/voice_adapter.py`)
   - Wraps any agent-framework Agent
   - Handles audio capture via PyAudio (push-to-talk)
   - Speech-to-text via Deepgram
   - Text-to-speech via Cartesia
   - Delegates all LLM interaction to the wrapped Agent

2. **GUI** (`chasm/src/chasm/gui.py`)
   - Tkinter-based push-to-talk interface
   - Live conversation transcript
   - Status indicators
   - Keyboard shortcuts (Space/Enter to talk)

3. **Voice Runner** (`bin/run-voice-agent`)
   - Instantiates agents from the AGENTS registry
   - Adds voice-optimized system prompt
   - Launches GUI with VoiceAdapter

## Voice-Optimized Prompts

When running in voice mode, agents receive additional guidance to optimize for TTS:

- Keep responses concise and conversational (1-3 sentences)
- Avoid markdown, bullet points, code blocks
- No parenthetical asides or complex nested sentences
- Integrate information into prose rather than lists
- Handle transcription disfluencies gracefully
- Describe concepts rather than quoting exact syntax

This guidance is automatically added by `bin/run-voice-agent`.

## Adding New Agents

To make a new agent available for voice mode:

1. Create the agent in `agents/your_agent/`
2. Add it to the AGENTS registry in both:
   - `bin/run-agent` (for text mode)
   - `bin/run-voice-agent` (for voice mode)

Example:

```python
# In both run_agent.py and run_voice_agent.py
AGENTS: dict[str, tuple[type, dict | None]] = {
    # ... existing agents ...
    "your_agent": (YourAgent, None),
}
```

## Implementation Details

### How Voice Wrapping Works

The `bin/run-voice-agent` script:

1. Looks up the agent class in the AGENTS registry
2. Instantiates the agent with any required configuration
3. Dynamically modifies the agent's system prompt to add voice guidance
4. Passes the agent to chasm's `create_gui()` function
5. The GUI creates a `VoiceAdapter` wrapping the agent
6. User interactions flow through: Audio → STT → Agent → TTS → Audio

### Agent State Preservation

The voice wrapper preserves all agent functionality:
- MCP tool access
- Conversation history
- Memory persistence
- Security checks
- Token tracking

## Files Changed/Created

**New Files:**
- `agents/chatbot/` - New chatbot agent package
  - `__init__.py` - Package marker
  - `main.py` - ChatbotAgent implementation
  - `prompts.py` - System and greeting prompts
- `bin/run-voice-agent` - Voice-enabled agent runner

**Modified Files:**
- `bin/run-agent` - Added chatbot to registry

## Future Enhancements

Possible improvements:
- [ ] VAD (Voice Activity Detection) for automatic recording start/stop
- [ ] Alternative audio backends (PortAudio, PulseAudio direct)
- [ ] Streaming TTS for lower latency
- [ ] Voice activity visualization
- [ ] Recording/playback of conversations
- [ ] Multi-turn conversation context in voice mode
- [ ] Custom voice IDs per agent

## Troubleshooting

### "Could not import chasm library"

The chasm library must be available in your Python path. It's configured as an editable dependency in `pyproject.toml`:

```bash
# Verify chasm is installed
uv pip list | grep chasm

# If missing, sync dependencies
uv sync
```

### Audio Device Issues

The voice adapter will log which audio devices it's using:

```
Audio input:  Built-in Microphone
Audio output: Built-in Speakers
```

If you have issues:
- Check your system audio settings
- Ensure PyAudio is properly installed
- On Linux, verify PulseAudio/PipeWire is running

### API Key Errors

Voice mode requires three API keys. Check your `.env`:

```bash
# Verify all keys are set
grep -E "(ANTHROPIC|DEEPGRAM|CARTESIA)_API_KEY" .env
```

## Related Documentation

- [CLAUDE.md](CLAUDE.md) - Main project documentation
- [chasm/CLAUDE.md](../chasm/CLAUDE.md) - Chasm library documentation
- [agent-framework](../agent-framework/) - Core agent framework
