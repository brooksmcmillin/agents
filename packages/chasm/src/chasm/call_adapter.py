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

Security Features:
- Stream token validation for WebSocket authentication
- Max concurrent call limits to prevent resource exhaustion
- Audio payload size limits to prevent memory attacks
- Session timeouts to clean up stale connections
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
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

# Security limits
MAX_CONCURRENT_CALLS = int(os.getenv("CHASM_MAX_CONCURRENT_CALLS", "20"))
MAX_AUDIO_CHUNK_SIZE = 2048  # Max bytes per audio chunk (mulaw at 8kHz)
MAX_TRANSCRIPT_BUFFER_SIZE = 10000  # Max characters in transcript buffer
SESSION_TIMEOUT_SECONDS = 3600  # 1 hour max call duration
AUDIO_OUT_QUEUE_SIZE = 100  # Max queued audio chunks


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
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def set_transcript_buffer(self, value: str) -> None:
        """Set transcript buffer with size limit."""
        if len(value) > MAX_TRANSCRIPT_BUFFER_SIZE:
            # Keep the most recent part
            self.transcript_buffer = value[-MAX_TRANSCRIPT_BUFFER_SIZE:]
        else:
            self.transcript_buffer = value


class CallAdapter:
    """Handles voice calls with agent-framework agents.

    This adapter manages real-time voice conversations over telephony
    connections (e.g., Twilio). It uses streaming STT/TTS for low-latency
    responses.

    Security Features:
    - Stream token validation to prevent unauthorized WebSocket connections
    - Maximum concurrent call limits
    - Audio payload size validation
    - Session timeouts

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
        max_concurrent_calls: int = MAX_CONCURRENT_CALLS,
        stream_token_secret: str | None = None,
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
            max_concurrent_calls: Maximum number of concurrent calls allowed.
            stream_token_secret: Secret for generating/validating stream tokens.
                If not provided, uses CHASM_STREAM_TOKEN_SECRET env var.
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
        self.max_concurrent_calls = max_concurrent_calls

        # Stream token secret for WebSocket authentication
        self._stream_token_secret = (
            stream_token_secret
            or os.getenv("CHASM_STREAM_TOKEN_SECRET")
            or secrets.token_urlsafe(32)
        )

        # Callbacks
        self.on_call_started = on_call_started or (lambda _: None)
        self.on_call_ended = on_call_ended or (lambda _: None)
        self.on_user_speech = on_user_speech or (lambda _, __: None)
        self.on_agent_response = on_agent_response or (lambda _, __: None)
        self.on_error = on_error or (lambda _, __: None)

        # Service clients
        self.deepgram = DeepgramClient(api_key=os.getenv("DEEPGRAM_API_KEY"))
        self.cartesia = AsyncCartesia(api_key=os.getenv("CARTESIA_API_KEY"))

        # Active sessions with lock for thread safety
        self._sessions: dict[str, CallSession] = {}
        self._sessions_lock = asyncio.Lock()

    def generate_stream_token(self, call_sid: str) -> str:
        """Generate a one-time token for WebSocket stream authentication.

        This token should be included in the TwiML <Stream> URL parameters.
        It prevents unauthorized connections to the WebSocket endpoint.

        Args:
            call_sid: The Twilio Call SID.

        Returns:
            A signed token string.
        """
        timestamp = str(int(time.time()))
        data = f"{call_sid}:{timestamp}"
        signature = hmac.new(
            self._stream_token_secret.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        return f"{timestamp}:{signature}"

    def validate_stream_token(self, call_sid: str, token: str, max_age_seconds: int = 300) -> bool:
        """Validate a stream token.

        Args:
            call_sid: The Twilio Call SID.
            token: The token to validate.
            max_age_seconds: Maximum token age in seconds (default 5 minutes).

        Returns:
            True if token is valid, False otherwise.
        """
        try:
            parts = token.split(":")
            if len(parts) != 2:
                return False

            timestamp_str, provided_signature = parts
            timestamp = int(timestamp_str)

            # Check token age
            if time.time() - timestamp > max_age_seconds:
                logger.warning(f"Stream token expired for call {call_sid}")
                return False

            # Verify signature
            data = f"{call_sid}:{timestamp_str}"
            expected_signature = hmac.new(
                self._stream_token_secret.encode(),
                data.encode(),
                hashlib.sha256,
            ).hexdigest()[:32]

            if not hmac.compare_digest(expected_signature, provided_signature):
                logger.warning(f"Invalid stream token signature for call {call_sid}")
                return False

            return True

        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to validate stream token: {e}")
            return False

    async def handle_media_stream(
        self,
        websocket: Any,  # WebSocket connection (e.g., from FastAPI/Starlette)
        call_sid: str,
        caller: str = "",
        callee: str = "",
        stream_token: str | None = None,
    ) -> None:
        """Handle a Twilio Media Stream WebSocket connection.

        This is the main entry point for handling incoming calls. Connect
        your Twilio webhook to call this method with the WebSocket.

        Args:
            websocket: WebSocket connection from your web framework.
            call_sid: Twilio Call SID.
            caller: Caller phone number (optional).
            callee: Called phone number (optional).
            stream_token: Authentication token for this stream.

        Raises:
            ValueError: If max concurrent calls exceeded or invalid token.
        """
        # Validate stream token if provided
        if stream_token is not None and not self.validate_stream_token(call_sid, stream_token):
            logger.warning(f"Rejected stream with invalid token for call {call_sid}")
            raise ValueError("Invalid stream token")

        # Check concurrent call limit
        async with self._sessions_lock:
            if len(self._sessions) >= self.max_concurrent_calls:
                logger.warning(
                    f"Rejected call {call_sid}: max concurrent calls "
                    f"({self.max_concurrent_calls}) reached"
                )
                raise ValueError("Maximum concurrent calls exceeded")

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
            async with self._sessions_lock:
                self._sessions.pop(call_sid, None)

    async def _run_call_loop(
        self,
        websocket: Any,
        session: CallSession,
    ) -> None:
        """Main call loop handling bidirectional audio streaming."""
        # Initialize Deepgram live transcription
        dg_connection = self.deepgram.listen.asyncwebsocket.v("1")

        transcript_queue: asyncio.Queue[str] = asyncio.Queue()
        # Bounded queue to prevent memory exhaustion
        audio_out_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=AUDIO_OUT_QUEUE_SIZE)

        # Deepgram event handlers
        async def on_transcript(_self: Any, result: Any, **_kwargs: Any) -> None:
            """Handle incoming transcription results."""
            transcript = result.channel.alternatives[0].transcript
            if transcript.strip():
                # Check if this is a final result
                if result.is_final:
                    await transcript_queue.put(transcript)
                    session.transcript_buffer = ""
                else:
                    session.set_transcript_buffer(transcript)

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

        try:
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
                        # Check session timeout
                        if session.start_time and (
                            time.time() - session.start_time > SESSION_TIMEOUT_SECONDS
                        ):
                            logger.info(f"Session timeout for call {session.call_sid}")
                            break

                        # Check if session was cancelled
                        if session._cancel_event.is_set():
                            break

                        data = json.loads(message)
                        event = data.get("event")

                        if event == "start":
                            session.stream_sid = data.get("streamSid")
                            logger.info(f"Stream started: {session.stream_sid}")

                        elif event == "media":
                            payload = data.get("media", {}).get("payload")
                            if payload:
                                # Validate payload size before decoding
                                if len(payload) > MAX_AUDIO_CHUNK_SIZE * 2:
                                    logger.warning(
                                        f"Oversized audio payload rejected: {len(payload)} bytes"
                                    )
                                    continue

                                audio_bytes = base64.b64decode(payload)

                                # Double-check decoded size
                                if len(audio_bytes) > MAX_AUDIO_CHUNK_SIZE:
                                    logger.warning(
                                        f"Oversized decoded audio rejected: "
                                        f"{len(audio_bytes)} bytes"
                                    )
                                    continue

                                await dg_connection.send(audio_bytes)

                        elif event == "stop":
                            logger.info(f"Stream stopped: {session.stream_sid}")
                            break

                except Exception as e:
                    logger.error(f"Error receiving audio: {e}")

            async def process_transcripts() -> None:
                """Process transcribed speech and generate responses."""
                while not session._cancel_event.is_set():
                    try:
                        # Use wait with cancel event for clean shutdown
                        transcript = await asyncio.wait_for(
                            transcript_queue.get(),
                            timeout=1.0,
                        )
                        if transcript:
                            self.on_user_speech(session, transcript)
                            await self._process_user_input(
                                transcript, websocket, session, audio_out_queue
                            )
                    except TimeoutError:
                        # Check if we should exit
                        if session._cancel_event.is_set():
                            break
                        continue
                    except Exception as e:
                        logger.error(f"Error processing transcript: {e}")
                        break

            async def send_audio() -> None:
                """Send TTS audio back to Twilio."""
                while not session._cancel_event.is_set():
                    try:
                        audio_chunk = await asyncio.wait_for(
                            audio_out_queue.get(),
                            timeout=1.0,
                        )
                        if audio_chunk is None:
                            continue
                        await self._send_audio_to_twilio(websocket, session, audio_chunk)
                    except TimeoutError:
                        # Check if we should exit
                        if session._cancel_event.is_set():
                            break
                        continue
                    except Exception as e:
                        logger.error(f"Error sending audio: {e}")
                        break

            # Run all tasks concurrently
            tasks = [
                asyncio.create_task(receive_audio()),
                asyncio.create_task(process_transcripts()),
                asyncio.create_task(send_audio()),
            ]

            # Wait for receive_audio to complete (indicates call ended)
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Signal other tasks to stop
            session._cancel_event.set()

            # Cancel remaining tasks
            for task in pending:
                task.cancel()

            # Wait for cleanup
            await asyncio.gather(*pending, return_exceptions=True)

        finally:
            # Always cleanup Deepgram connection
            try:
                await dg_connection.finish()
            except Exception as e:
                logger.warning(f"Error closing Deepgram connection: {e}")

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
            await self._generate_and_send_tts(response_text, websocket, session, audio_out_queue)

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
                    try:
                        # Use put_nowait with bounded queue
                        audio_out_queue.put_nowait(chunk.audio)
                    except asyncio.QueueFull:
                        logger.warning("Audio output queue full, dropping chunk")

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
        message = json.dumps(
            {
                "event": "media",
                "streamSid": session.stream_sid,
                "media": {
                    "payload": payload,
                },
            }
        )
        await websocket.send_text(message)

    async def end_call(self, call_sid: str) -> None:
        """End an active call.

        Args:
            call_sid: The Twilio Call SID to end.
        """
        async with self._sessions_lock:
            session = self._sessions.get(call_sid)
            if session:
                session.state = CallState.ENDED
                session._cancel_event.set()

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
