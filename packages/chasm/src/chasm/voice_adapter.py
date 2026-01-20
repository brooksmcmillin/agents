"""Voice adapter for agent-framework agents.

This module provides a VoiceAdapter class that wraps any agent-framework Agent
with voice I/O capabilities:
- Audio capture via PyAudio
- Speech-to-text via Deepgram
- Text-to-speech via Cartesia

The adapter delegates all LLM interaction to the wrapped Agent, which handles
Claude API calls, tool execution, conversation history, etc.
"""

import asyncio
import io
import os
import queue
import subprocess
import threading
import wave
from collections.abc import Callable, Generator, Mapping
from typing import Any

import pyaudio
from cartesia import Cartesia
from deepgram import DeepgramClient
from dotenv import load_dotenv

from agent_framework import Agent

load_dotenv()

# Audio constants
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16


class VoiceAdapter:
    """Wraps an agent-framework Agent with voice I/O capabilities.

    This adapter handles:
    - Audio capture via PyAudio (push-to-talk style)
    - Speech-to-text via Deepgram
    - Text-to-speech via Cartesia
    - Delegates LLM interaction to the wrapped Agent

    The Agent handles all Claude API calls, tool execution, conversation
    history management, security checks, etc.

    Example:
        agent = MyAgent(mcp_server_path="path/to/server.py")
        adapter = VoiceAdapter(
            agent=agent,
            on_status_change=lambda s: print(f"Status: {s}"),
        )
        adapter.start_recording()
        # ... user speaks ...
        adapter.stop_recording()  # Triggers STT -> Agent -> TTS pipeline
    """

    def __init__(
        self,
        agent: Agent,
        *,
        voice_id: str = "79a125e8-cd45-4c13-8a67-188112f4dd22",  # British Lady
        on_user_transcript: Callable[[str], None] | None = None,
        on_assistant_response: Callable[[str], None] | None = None,
        on_status_change: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the voice adapter.

        Args:
            agent: An agent-framework Agent instance to wrap.
            voice_id: Cartesia voice ID for TTS. Defaults to "British Lady".
            on_user_transcript: Callback invoked with transcribed user speech.
            on_assistant_response: Callback invoked with agent's text response.
            on_status_change: Callback invoked with status updates
                ("Recording...", "Transcribing...", "Thinking...", etc.)
        """
        self.agent = agent
        self.voice_id = voice_id

        # Callbacks (no-op if not provided)
        self.on_user_transcript = on_user_transcript or (lambda _: None)
        self.on_assistant_response = on_assistant_response or (lambda _: None)
        self.on_status_change = on_status_change or (lambda _: None)

        # Audio setup
        self.pyaudio = pyaudio.PyAudio()
        self.recording = False
        self.audio_frames: list[bytes] = []

        # Get device info
        self.input_device_info = self.pyaudio.get_default_input_device_info()
        self.output_device_info = self.pyaudio.get_default_output_device_info()
        self._log_device_info()

        # Service clients
        self.deepgram = DeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY"))
        self.cartesia = Cartesia(api_key=os.getenv("CARTESIA_API_KEY"))

        # For running async agent methods from sync context
        self._loop: asyncio.AbstractEventLoop | None = None

    def _log_device_info(self) -> None:
        """Log audio device information."""
        input_name = (
            self._get_pulse_device_name("source") or self.input_device_info["name"]
        )
        output_name = (
            self._get_pulse_device_name("sink") or self.output_device_info["name"]
        )
        print(f"Audio input:  {input_name}")
        print(f"Audio output: {output_name}")

    def _get_pulse_device_name(self, device_type: str) -> str | None:
        """Get the actual device description from PulseAudio/PipeWire."""
        try:
            if device_type == "source":
                result = subprocess.run(
                    ["pactl", "get-default-source"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode != 0:
                    return None
                source_name = result.stdout.strip()
                result = subprocess.run(
                    ["pactl", "list", "sources"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode != 0:
                    return None
                in_target = False
                for line in result.stdout.splitlines():
                    if f"Name: {source_name}" in line:
                        in_target = True
                    elif in_target and "Description:" in line:
                        return line.split("Description:", 1)[1].strip()
                    elif in_target and line.startswith("Source #"):
                        break
            elif device_type == "sink":
                result = subprocess.run(
                    ["pactl", "get-default-sink"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode != 0:
                    return None
                sink_name = result.stdout.strip()
                result = subprocess.run(
                    ["pactl", "list", "sinks"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode != 0:
                    return None
                in_target = False
                for line in result.stdout.splitlines():
                    if f"Name: {sink_name}" in line:
                        in_target = True
                    elif in_target and "Description:" in line:
                        return line.split("Description:", 1)[1].strip()
                    elif in_target and line.startswith("Sink #"):
                        break
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def get_input_device_name(self) -> str:
        """Get the name of the current audio input device."""
        return self._get_pulse_device_name("source") or str(
            self.input_device_info["name"]
        )

    def get_output_device_name(self) -> str:
        """Get the name of the current audio output device."""
        return self._get_pulse_device_name("sink") or str(
            self.output_device_info["name"]
        )

    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create an event loop for async operations."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def start_recording(self) -> None:
        """Start recording audio from the microphone."""
        if self.recording:
            return
        self.recording = True
        self.audio_frames = []
        self.on_status_change("Recording...")

        self.input_stream = self.pyaudio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK,
            stream_callback=self._audio_callback,
        )

    def _audio_callback(
        self,
        in_data: bytes | None,
        frame_count: int,  # noqa: ARG002
        time_info: Mapping[str, Any],  # noqa: ARG002
        status: int,  # noqa: ARG002
    ) -> tuple[None, int]:
        """PyAudio callback for capturing audio frames."""
        if self.recording and in_data:
            self.audio_frames.append(in_data)
        return (None, pyaudio.paContinue)

    def stop_recording(self) -> None:
        """Stop recording and process the captured audio."""
        if not self.recording:
            return
        self.recording = False

        if hasattr(self, "input_stream"):
            self.input_stream.stop_stream()
            self.input_stream.close()

        if not self.audio_frames:
            self.on_status_change("No audio recorded")
            return

        self.on_status_change("Processing...")
        threading.Thread(target=self._process_audio, daemon=True).start()

    def _process_audio(self) -> None:
        """Process recorded audio: STT -> Agent -> TTS."""
        try:
            # Convert frames to WAV bytes
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.pyaudio.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(self.audio_frames))
            wav_bytes = wav_buffer.getvalue()

            # STT with Deepgram
            self.on_status_change("Transcribing...")
            # Modern Deepgram SDK API (v3+)
            response = self.deepgram.listen.rest.v("1").transcribe_file(
                source={"buffer": wav_bytes, "mimetype": "audio/wav"},
                options={"model": "nova-2", "smart_format": True},
            )
            transcript = response.results.channels[0].alternatives[0].transcript

            if not transcript.strip():
                self.on_status_change("No speech detected")
                return

            self.on_user_transcript(transcript)

            # Process with agent (handles Claude + tools)
            self.on_status_change("Thinking...")
            loop = self._get_event_loop()
            response_text = loop.run_until_complete(
                self.agent.process_message(transcript)
            )

            self.on_assistant_response(response_text)

            # TTS with Cartesia
            self.on_status_change("Speaking...")
            self._speak(response_text)

            self.on_status_change("Ready")

        except Exception as e:
            self.on_status_change(f"Error: {e}")
            raise

    def _speak(self, text: str) -> None:
        """Stream TTS audio with buffered playback.

        Uses a producer/consumer pattern to decouple network fetching from
        audio playback, preventing network jitter from causing audio crackling.
        """
        # Buffer settings (at 44100 Hz, 16-bit mono: 88200 bytes = 1 second)
        prebuffer_bytes = 88200  # Wait for this much audio before starting playback
        playback_chunk_size = 8820  # ~100ms chunks to PyAudio

        audio_queue: queue.Queue[bytes | None] = queue.Queue()
        producer_error: list[Exception] = []

        def producer() -> None:
            """Fetch audio from Cartesia and feed the queue."""
            try:
                audio_chunks: Generator[bytes, None, None] = self.cartesia.tts.bytes(
                    model_id="sonic-2",
                    transcript=text,
                    voice={"id": self.voice_id},
                    output_format={
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": 44100,
                    },
                )
                for chunk in audio_chunks:
                    audio_queue.put(chunk)
                audio_queue.put(None)  # Sentinel to signal end
            except Exception as e:
                producer_error.append(e)
                audio_queue.put(None)

        # Start producer thread
        producer_thread = threading.Thread(target=producer, daemon=True)
        producer_thread.start()

        output_stream = self.pyaudio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=44100,
            output=True,
            frames_per_buffer=4096,
        )

        try:
            buffer = b""
            started = False

            while True:
                # Get next chunk from queue (block until available)
                chunk = audio_queue.get()
                if chunk is None:
                    # End of stream
                    break
                buffer += chunk

                if not started:
                    # Wait until we have enough buffered before starting playback
                    if len(buffer) >= prebuffer_bytes:
                        started = True
                    else:
                        continue

                # Write in fixed-size chunks for consistent playback
                while len(buffer) >= playback_chunk_size:
                    output_stream.write(buffer[:playback_chunk_size])
                    buffer = buffer[playback_chunk_size:]

            # Drain remaining buffer
            if buffer:
                output_stream.write(buffer)

        finally:
            output_stream.stop_stream()
            output_stream.close()
            producer_thread.join(timeout=1.0)

        if producer_error:
            raise producer_error[0]

    def cleanup(self) -> None:
        """Clean up resources."""
        self.pyaudio.terminate()
        if self._loop and not self._loop.is_closed():
            self._loop.close()
