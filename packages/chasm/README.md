# Chasm - Voice Interface for Agent-Framework Agents

Chasm provides voice capabilities for agent-framework agents, enabling both local voice conversations and telephony-based voice calling.

## Features

- **Local Voice Interface**: Push-to-talk voice conversations using your microphone and speakers
- **Voice Calling**: Make and receive phone calls with AI agents via Twilio
- **Streaming Audio**: Real-time speech-to-text and text-to-speech for natural conversations
- **Agent Integration**: Works with any agent-framework Agent subclass

## Installation

```bash
# Basic installation (local voice interface)
uv sync --group voice

# With telephony support (Twilio calling)
pip install chasm[telephony]
```

**System Requirements:**
- PortAudio library (for local audio): `apt install portaudio19-dev` or `brew install portaudio`
- Python 3.12+

## Quick Start

### Local Voice Interface (Push-to-Talk)

```bash
# Set API keys
export ANTHROPIC_API_KEY=your_key
export DEEPGRAM_API_KEY=your_key
export CARTESIA_API_KEY=your_key

# Run the GUI
uv run python -m chasm.gui
```

### Voice Calling Server

```bash
# Set additional Twilio credentials
export TWILIO_ACCOUNT_SID=your_account_sid
export TWILIO_AUTH_TOKEN=your_auth_token
export TWILIO_PHONE_NUMBER=+1234567890
export WEBHOOK_BASE_URL=https://your-domain.com

# Run the call server
uv run python -m chasm.call_server
```

## Architecture

### Local Voice Interface

```
User speaks → PyAudio → Deepgram STT → Agent → Cartesia TTS → PyAudio → Speaker
```

### Voice Calling

```
Phone Call → Twilio → WebSocket Media Stream → CallAdapter
                                                    ↓
                                            Deepgram STT (streaming)
                                                    ↓
                                            Agent.process_message()
                                                    ↓
                                            Cartesia TTS (streaming)
                                                    ↓
                                            Twilio ← Audio response
```

## Components

### VoiceAdapter

Wraps any agent-framework Agent with local voice I/O:

```python
from agent_framework import Agent
from chasm import VoiceAdapter

class MyAgent(Agent):
    def get_system_prompt(self) -> str:
        return "You are a helpful assistant."

agent = MyAgent()
adapter = VoiceAdapter(
    agent=agent,
    on_user_transcript=lambda text: print(f"You: {text}"),
    on_assistant_response=lambda text: print(f"Agent: {text}"),
)

# Push-to-talk style
adapter.start_recording()
# ... user speaks ...
adapter.stop_recording()  # Triggers STT → Agent → TTS pipeline
```

### CallAdapter

Handles telephony-based voice calls:

```python
from chasm import CallAdapter, CallSession

adapter = CallAdapter(
    agent=agent,
    greeting="Hello! How can I help you today?",
    on_call_started=lambda s: print(f"Call started: {s.call_sid}"),
    on_call_ended=lambda s: print(f"Call ended: {s.call_sid}"),
    on_user_speech=lambda s, text: print(f"User: {text}"),
    on_agent_response=lambda s, text: print(f"Agent: {text}"),
)

# Handle incoming Twilio Media Stream
await adapter.handle_media_stream(websocket, call_sid="...")
```

### TwilioCallHandler

FastAPI-compatible webhook handler for Twilio:

```python
from fastapi import FastAPI, WebSocket, Request, Response
from chasm.telephony import TwilioCallHandler
from chasm.telephony.twilio_handler import TwilioConfig

app = FastAPI()

config = TwilioConfig.from_env("https://your-domain.com")
handler = TwilioCallHandler(call_adapter, config)

@app.post("/voice/incoming")
async def incoming_call(request: Request):
    twiml = await handler.handle_incoming_call(request)
    return Response(content=twiml, media_type="application/xml")

@app.websocket("/voice/stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    await handler.handle_media_stream(websocket)

# Make outbound calls
result = await handler.make_outbound_call("+1234567890")
```

## Twilio Setup

1. Create a Twilio account at https://www.twilio.com
2. Get a phone number with Voice capabilities
3. Configure your webhook URLs in the Twilio Console:
   - Go to Phone Numbers > Manage > Active numbers
   - Select your number
   - Under "Voice & Fax", set:
     - **A CALL COMES IN**: Webhook, `https://your-domain.com/voice/incoming`, POST

4. For local development, use ngrok:
   ```bash
   ngrok http 8000
   # Use the ngrok URL as your WEBHOOK_BASE_URL
   ```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `DEEPGRAM_API_KEY` | Yes | Deepgram STT API key |
| `CARTESIA_API_KEY` | Yes | Cartesia TTS API key |
| `TWILIO_ACCOUNT_SID` | For calling | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | For calling | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | For calling | Your Twilio phone number |
| `WEBHOOK_BASE_URL` | For calling | Public URL for webhooks |
| `MCP_SERVER_PATH` | Optional | Path to MCP server for tools |

## API Reference

### CallAdapter

```python
CallAdapter(
    agent: Agent,
    voice_id: str = "...",           # Cartesia voice ID
    silence_threshold_ms: int = 700,  # End-of-speech detection
    greeting: str | None = None,      # Greeting when call connects
    on_call_started: Callable[[CallSession], None] | None = None,
    on_call_ended: Callable[[CallSession], None] | None = None,
    on_user_speech: Callable[[CallSession, str], None] | None = None,
    on_agent_response: Callable[[CallSession, str], None] | None = None,
    on_error: Callable[[CallSession, Exception], None] | None = None,
)
```

### CallSession

```python
@dataclass
class CallSession:
    call_sid: str           # Twilio Call SID
    stream_sid: str | None  # Twilio Stream SID
    state: CallState        # IDLE, RINGING, CONNECTED, ON_HOLD, ENDED
    caller: str             # Caller phone number
    callee: str             # Called phone number
    start_time: float | None
    metadata: dict[str, Any]
```

### REST API Endpoints

The call server exposes these endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/voice/incoming` | Twilio incoming call webhook |
| POST | `/voice/outbound` | Twilio outbound call webhook |
| WS | `/voice/stream` | Twilio Media Stream WebSocket |
| POST | `/call` | Initiate outbound call (`{"to": "+1234567890"}`) |
| GET | `/calls` | List active calls |
| DELETE | `/calls/{call_sid}` | End a call |

## Tips for Voice-Optimized Agents

When creating agents for voice:

1. Keep responses short (1-3 sentences)
2. Avoid markdown, lists, and code blocks
3. Spell out numbers and abbreviations
4. Use natural, conversational language
5. Handle transcription errors gracefully

Example system prompt:

```python
def get_system_prompt(self) -> str:
    return """You are a helpful AI assistant on a phone call.

Keep responses SHORT (1-3 sentences max).
Speak naturally - no lists, bullets, or markdown.
Spell out numbers: say "three hundred dollars" not "$300".
Be patient with transcription errors."""
```

## Troubleshooting

### No audio input/output
- Check that PortAudio is installed
- Verify your default audio devices with `pactl list sources/sinks`

### Twilio connection fails
- Ensure your webhook URL is publicly accessible
- Check Twilio Console for error logs
- Verify all environment variables are set

### High latency
- Use a server closer to your users
- Reduce response length in your agent's system prompt
- Consider using Deepgram's faster models for STT

## License

MIT
