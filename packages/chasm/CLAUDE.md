# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chasm is a voice assistant that uses:
- **Deepgram** for speech-to-text
- **Claude (Anthropic)** for LLM responses
- **Cartesia** for text-to-speech

## Running the Application

```bash
# GUI version (push-to-talk interface)
uv run src/chasm/gui.py

# Pipecat streaming version (continuous listening with VAD)
uv run src/chasm/main.py
```

Requires `.env` file with `DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`, and `CARTESIA_API_KEY`.

## Architecture

Two implementations exist:

- **src/chasm/gui.py**: Standalone push-to-talk GUI using tkinter. Records audio on button press, processes sequentially (transcribe → LLM → TTS), plays response. Uses threading for async processing.

- **src/chasm/main.py**: Real-time streaming pipeline using [pipecat-ai](https://github.com/pipecat-ai/pipecat). Uses Silero VAD for voice activity detection, enabling continuous listening with interruption support.

Both use the same voice ID (`79a125e8-cd45-4c13-8a67-188112f4dd22` - "British Lady") and similar system prompts optimized for TTS output.
