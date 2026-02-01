"""Call adapter for agent-framework agents.

This module provides a CallAdapter class that handles voice calls with agents
using streaming STT/TTS for real-time conversation. Unlike VoiceAdapter which
uses local audio I/O, CallAdapter is designed for telephony integrations.

Supports:
- Twilio Media Streams (WebSocket-based audio streaming)
- Real-time speech-to-text via Deepgram streaming API
- Real-time text-to-speech via Cartesia streaming API
- Full-duplex audio (simultaneous send/receive)

Architecture:
    Phone Call → Twilio → WebSocket Media Stream → CallAdapter
                                                        ↓
                                                Deepgram STT (streaming)
                                                        ↓
                                                Agent.process_message()
                                                        ↓
                                                Cartesia TTS (streaming)
                                                        ↓
                                                Twilio ← Audio response
"""

import asyncio
import base64
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_framework import Agent
from cartesia import AsyncCartesia
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Twilio Media Stream audio format
TWILIO_SAMPLE_RATE = 8000  # Twilio uses 8kHz mulaw
TWILIO_ENCODING = "audio/x-mulaw"


class CallState(Enum):
    """States of a voice call."""

    IDLE = "idle"
    RINGING = "ringing"
    CONNECTED = "connected"
    ON_HOLD = "on_hold"
    ENDED = "ended"


@dataclass
class CallSession:
    """Represents an active call session."""

    call_sid: str
    stream_sid: str | None = None
    state: CallState = CallState.IDLE
    caller: str = ""
    callee: str = ""
    start_time: float | None = None
    transcript_buffer: str = ""
    pending_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class CallAdapter:
    """Handles voice calls with agent-framework agents.

    This adapter manages real-time voice conversations over telephony
    connections (e.g., Twilio). It uses streaming STT/TTS for low-latency
    responses.

    Example:
        agent = MyAgent(mcp_server_path="path/to/server.py")
        adapter = CallAdapter(
            agent=agent,
            on_call_started=lambda session: print(f"Call started: {session.call_sid}"),
            on_call_ended=lambda session: print(f"Call ended: {session.call_sid}"),
        )

        # In your Twilio webhook handler:
        await adapter.handle_media_stream(websocket, call_sid)
    """

    def __init__(
        self,
        agent: Agent,
        *,
        voice_id: str = "79a125e8-cd45-4c13-8a67-188112f4dd22",  # British Lady
        silence_threshold_ms: int = 700,  # End of speech detection
        greeting: str | None = None,  # Optional greeting when call connects
        on_call_started: Callable[[CallSession], None] | None = None,
        on_call_ended: Callable[[CallSession], None] | None = None,
        on_user_speech: Callable[[CallSession, str], None] | None = None,
        on_agent_response: Callable[[CallSession, str], None] | None = None,
        on_error: Callable[[CallSession, Exception], None] | None = None,
    ) -> None:
        """Initialize the call adapter.

        Args:
            agent: An agent-framework Agent instance to handle conversations.
            voice_id: Cartesia voice ID for TTS.
            silence_threshold_ms: Milliseconds of silence to detect end of speech.
            greeting: Optional greeting message when call connects.
            on_call_started: Callback when a call is established.
            on_call_ended: Callback when a call ends.
            on_user_speech: Callback with transcribed user speech.
            on_agent_response: Callback with agent's response text.
            on_error: Callback when an error occurs during the call.
        """
        self.agent = agent
        self.voice_id = voice_id
        self.silence_threshold_ms = silence_threshold_ms
        self.greeting = greeting

        # Callbacks
        self.on_call_started = on_call_started or (lambda _: None)
        self.on_call_ended = on_call_ended or (lambda _: None)
        self.on_user_speech = on_user_speech or (lambda _, __: None)
        self.on_agent_response = on_agent_response or (lambda _, __: None)
        self.on_error = on_error or (lambda _, __: None)

        # Service clients
        self.deepgram = DeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY"))
        self.cartesia = AsyncCartesia(api_key=os.getenv("CARTESIA_API_KEY"))

        # Active sessions
        self._sessions: dict[str, CallSession] = {}

    async def handle_media_stream(
        self,
        websocket: Any,  # WebSocket connection (e.g., from FastAPI/Starlette)
        call_sid: str,
        caller: str = "",
        callee: str = "",
    ) -> None:
        """Handle a Twilio Media Stream WebSocket connection.

        This is the main entry point for handling incoming calls. Connect
        your Twilio webhook to call this method with the WebSocket.

        Args:
            websocket: WebSocket connection from your web framework.
            call_sid: Twilio Call SID.
            caller: Caller phone number (optional).
            callee: Called phone number (optional).
        """
        session = CallSession(
            call_sid=call_sid,
            caller=caller,
            callee=callee,
            state=CallState.RINGING,
        )
        self._sessions[call_sid] = session

        try:
            await self._run_call_loop(websocket, session)
        except Exception as e:
            logger.exception(f"Error in call {call_sid}")
            self.on_error(session, e)
        finally:
            session.state = CallState.ENDED
            self.on_call_ended(session)
            del self._sessions[call_sid]

    async def _run_call_loop(
        self,
        websocket: Any,
        session: CallSession,
    ) -> None:
        """Main call loop handling bidirectional audio streaming."""
        import time

        # Initialize Deepgram live transcription
        dg_connection = self.deepgram.listen.asyncwebsocket.v("1")

        transcript_queue: asyncio.Queue[str] = asyncio.Queue()
        audio_out_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        # Deepgram event handlers
        async def on_transcript(
            _self: Any, result: Any, **_kwargs: Any
        ) -> None:
            """Handle incoming transcription results."""
            transcript = result.channel.alternatives[0].transcript
            if transcript.strip():
                # Check if this is a final result
                if result.is_final:
                    await transcript_queue.put(transcript)
                    session.transcript_buffer = ""
                else:
                    session.transcript_buffer = transcript

        async def on_error(_self: Any, error: Any, **_kwargs: Any) -> None:
            """Handle Deepgram errors."""
            logger.error(f"Deepgram error: {error}")

        dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        dg_connection.on(LiveTranscriptionEvents.Error, on_error)

        # Connect to Deepgram
        options = LiveOptions(
            model="nova-2",
            language="en-US",
            encoding="mulaw",
            sample_rate=TWILIO_SAMPLE_RATE,
            channels=1,
            interim_results=True,
            utterance_end_ms=str(self.silence_threshold_ms),
            vad_events=True,
            endpointing=self.silence_threshold_ms,
        )
        await dg_connection.start(options)

        session.state = CallState.CONNECTED
        session.start_time = time.time()
        self.on_call_started(session)

        # Send greeting if configured
        if self.greeting:
            await self._generate_and_send_tts(
                self.greeting, websocket, session, audio_out_queue
            )

        # Create tasks for handling different streams
        async def receive_audio() -> None:
            """Receive audio from Twilio and forward to Deepgram."""
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    event = data.get("event")

                    if event == "start":
                        session.stream_sid = data.get("streamSid")
                        logger.info(f"Stream started: {session.stream_sid}")

                    elif event == "media":
                        payload = data.get("media", {}).get("payload")
                        if payload:
                            audio_bytes = base64.b64decode(payload)
                            await dg_connection.send(audio_bytes)

                    elif event == "stop":
                        logger.info(f"Stream stopped: {session.stream_sid}")
                        break

            except Exception as e:
                logger.error(f"Error receiving audio: {e}")

        async def process_transcripts() -> None:
            """Process transcribed speech and generate responses."""
            while True:
                try:
                    transcript = await asyncio.wait_for(
                        transcript_queue.get(), timeout=0.5
                    )
                    if transcript:
                        self.on_user_speech(session, transcript)
                        await self._process_user_input(
                            transcript, websocket, session, audio_out_queue
                        )
                except TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error processing transcript: {e}")
                    break

        async def send_audio() -> None:
            """Send TTS audio back to Twilio."""
            while True:
                try:
                    audio_chunk = await asyncio.wait_for(
                        audio_out_queue.get(), timeout=0.5
                    )
                    if audio_chunk is None:
                        continue
                    await self._send_audio_to_twilio(
                        websocket, session, audio_chunk
                    )
                except TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error sending audio: {e}")
                    break

        # Run all tasks concurrently
        await asyncio.gather(
            receive_audio(),
            process_transcripts(),
            send_audio(),
            return_exceptions=True,
        )

        # Cleanup
        await dg_connection.finish()

    async def _process_user_input(
        self,
        transcript: str,
        websocket: Any,
        session: CallSession,
        audio_out_queue: asyncio.Queue[bytes | None],
    ) -> None:
        """Process user speech and generate agent response."""
        try:
            # Get response from agent
            response_text = await self.agent.process_message(transcript)
            self.on_agent_response(session, response_text)

            # Generate and send TTS
            await self._generate_and_send_tts(
                response_text, websocket, session, audio_out_queue
            )

        except Exception as e:
            logger.exception(f"Error processing input: {e}")
            self.on_error(session, e)

    async def _generate_and_send_tts(
        self,
        text: str,
        websocket: Any,
        session: CallSession,
        audio_out_queue: asyncio.Queue[bytes | None],
    ) -> None:
        """Generate TTS audio and queue it for sending."""
        try:
            # Use Cartesia async streaming
            async for chunk in self.cartesia.tts.sse(
                model_id="sonic-2",
                transcript=text,
                voice={"id": self.voice_id},
                output_format={
                    "container": "raw",
                    "encoding": "pcm_mulaw",  # Twilio-compatible format
                    "sample_rate": TWILIO_SAMPLE_RATE,
                },
            ):
                if hasattr(chunk, "audio") and chunk.audio:
                    await audio_out_queue.put(chunk.audio)

        except Exception as e:
            logger.exception(f"TTS error: {e}")

    async def _send_audio_to_twilio(
        self,
        websocket: Any,
        session: CallSession,
        audio_bytes: bytes,
    ) -> None:
        """Send audio bytes to Twilio Media Stream."""
        if not session.stream_sid:
            return

        # Encode audio as base64 and send as Twilio media message
        payload = base64.b64encode(audio_bytes).decode("utf-8")
        message = json.dumps({
            "event": "media",
            "streamSid": session.stream_sid,
            "media": {
                "payload": payload,
            },
        })
        await websocket.send_text(message)

    async def end_call(self, call_sid: str) -> None:
        """End an active call.

        Args:
            call_sid: The Twilio Call SID to end.
        """
        session = self._sessions.get(call_sid)
        if session:
            session.state = CallState.ENDED

    def get_active_calls(self) -> list[CallSession]:
        """Get all active call sessions.

        Returns:
            List of active CallSession objects.
        """
        return list(self._sessions.values())

    def get_call(self, call_sid: str) -> CallSession | None:
        """Get a specific call session.

        Args:
            call_sid: The Twilio Call SID.

        Returns:
            CallSession if found, None otherwise.
        """
        return self._sessions.get(call_sid)
