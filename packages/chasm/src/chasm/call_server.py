"""Example FastAPI server for voice calling.

This module provides a complete FastAPI server that handles voice calls
with AI agents. It can be used as-is or as a reference for building
custom voice calling applications.

Usage:
    # Set environment variables
    export TWILIO_ACCOUNT_SID=your_account_sid
    export TWILIO_AUTH_TOKEN=your_auth_token
    export TWILIO_PHONE_NUMBER=+1234567890
    export DEEPGRAM_API_KEY=your_deepgram_key
    export CARTESIA_API_KEY=your_cartesia_key
    export ANTHROPIC_API_KEY=your_anthropic_key
    export WEBHOOK_BASE_URL=https://your-domain.com

    # Run the server
    uv run python -m chasm.call_server

    # Or with uvicorn directly
    uvicorn chasm.call_server:app --host 0.0.0.0 --port 8000

Configure Twilio:
    1. In your Twilio Console, go to Phone Numbers
    2. Select your number and configure:
       - Voice & Fax > A CALL COMES IN:
         Webhook: https://your-domain.com/voice/incoming (POST)
    3. Make sure your server is publicly accessible (use ngrok for testing)

Security:
    - WebSocket connections are authenticated using stream tokens
    - HTTP webhooks validate Twilio request signatures
    - Set CHASM_ENVIRONMENT=development only for local testing
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> Any:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI application instance.
    """
    try:
        from fastapi import FastAPI, Request, Response, WebSocket, WebSocketException
        from fastapi.responses import HTMLResponse
    except ImportError as err:
        raise ImportError(
            "FastAPI is required for the call server. Install with: pip install chasm[telephony]"
        ) from err

    from agent_framework import Agent

    from .call_adapter import CallAdapter
    from .telephony import TwilioCallHandler
    from .telephony.twilio_handler import TwilioConfig

    # Voice-optimized agent for phone calls
    class PhoneAgent(Agent):
        """Agent optimized for phone conversations."""

        def get_system_prompt(self) -> str:
            return """You are a helpful AI assistant on a phone call.

IMPORTANT GUIDELINES FOR PHONE CONVERSATIONS:
- Keep responses SHORT and conversational (1-3 sentences max)
- Speak naturally as if on the phone - no lists, bullet points, or formatting
- Never use markdown, code blocks, or special characters
- Spell out numbers and abbreviations (say "three hundred dollars" not "$300")
- If you need to communicate complex information, break it into multiple exchanges
- Ask clarifying questions if the user's request is unclear
- Be patient with transcription errors - try to understand intent
- Sound warm and personable, not robotic

You have access to tools but use them sparingly in phone calls.
Focus on quick, helpful responses that work well when spoken aloud."""

        def get_greeting(self) -> str:
            return "Hello! How can I help you today?"

    # Application state
    app_state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan handler."""
        # Get configuration
        webhook_base_url = os.getenv("WEBHOOK_BASE_URL")
        if not webhook_base_url:
            logger.warning(
                "WEBHOOK_BASE_URL not set. Using http://localhost:8000. "
                "Set this to your public URL for production."
            )
            webhook_base_url = "http://localhost:8000"

        # Create agent and adapters
        mcp_server_path = os.getenv("MCP_SERVER_PATH")
        agent = PhoneAgent(mcp_server_path=mcp_server_path)

        call_adapter = CallAdapter(
            agent=agent,
            greeting="Hello! Thanks for calling. How can I help you today?",
            on_call_started=lambda s: logger.info(f"Call started: {s.call_sid} from {s.caller}"),
            on_call_ended=lambda s: logger.info(f"Call ended: {s.call_sid}"),
            on_user_speech=lambda s, t: logger.info(f"User ({s.call_sid}): {t}"),
            on_agent_response=lambda s, t: logger.info(f"Agent ({s.call_sid}): {t}"),
        )

        try:
            config = TwilioConfig.from_env(webhook_base_url)
            twilio_handler = TwilioCallHandler(
                call_adapter=call_adapter,
                config=config,
            )
        except ValueError as e:
            logger.warning(f"Twilio not configured: {e}")
            twilio_handler = None

        app_state["agent"] = agent
        app_state["call_adapter"] = call_adapter
        app_state["twilio_handler"] = twilio_handler

        logger.info("Voice call server started")
        if twilio_handler:
            logger.info(f"Webhook URL: {webhook_base_url}/voice/incoming")
            logger.info(f"Stream URL: {config.stream_url}")

        yield

        logger.info("Voice call server shutting down")

    app = FastAPI(
        title="Chasm Voice Call Server",
        description="AI voice calling powered by Claude and Twilio",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Health check and info page."""
        active_calls = []
        if app_state.get("call_adapter"):
            active_calls = app_state["call_adapter"].get_active_calls()

        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Chasm Voice Call Server</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
        h1 {{ color: #333; }}
        .status {{ padding: 1rem; background: #e8f5e9; border-radius: 8px; margin: 1rem 0; }}
        .call {{ padding: 0.5rem; background: #fff3e0; border-radius: 4px; margin: 0.5rem 0; }}
        code {{ background: #f5f5f5; padding: 0.2rem 0.4rem; border-radius: 4px; }}
    </style>
</head>
<body>
    <h1>Chasm Voice Call Server</h1>
    <div class="status">
        <strong>Status:</strong> Running<br>
        <strong>Active Calls:</strong> {len(active_calls)}
    </div>
    {"".join(f'<div class="call">Call {c.call_sid} from {c.caller} - {c.state.value}</div>' for c in active_calls)}
    <h2>Endpoints</h2>
    <ul>
        <li><code>POST /voice/incoming</code> - Twilio incoming call webhook</li>
        <li><code>POST /voice/outbound</code> - Twilio outbound call webhook</li>
        <li><code>WebSocket /voice/stream</code> - Twilio Media Stream</li>
        <li><code>POST /call</code> - Initiate outbound call</li>
        <li><code>GET /calls</code> - List active calls</li>
        <li><code>DELETE /calls/{{call_sid}}</code> - End a call</li>
    </ul>
    <h2>Configuration</h2>
    <p>Configure Twilio webhook to: <code>{os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")}/voice/incoming</code></p>
</body>
</html>
"""

    @app.post("/voice/incoming")
    async def incoming_call(request: Request):
        """Handle incoming call webhook from Twilio."""
        handler = app_state.get("twilio_handler")
        if not handler:
            return Response(
                content="""<?xml version="1.0" encoding="UTF-8"?>
<Response><Say>Twilio is not configured. Goodbye.</Say><Hangup/></Response>""",
                media_type="application/xml",
            )

        twiml = await handler.handle_incoming_call(request)
        return Response(content=twiml, media_type="application/xml")

    @app.post("/voice/outbound")
    async def outbound_call(request: Request):
        """Handle outbound call webhook from Twilio."""
        handler = app_state.get("twilio_handler")
        if not handler:
            return Response(
                content="""<?xml version="1.0" encoding="UTF-8"?>
<Response><Say>Twilio is not configured. Goodbye.</Say><Hangup/></Response>""",
                media_type="application/xml",
            )

        form = await request.form()
        call_sid = form.get("CallSid", "")
        twiml = handler.handle_outbound_call(call_sid)
        return Response(content=twiml, media_type="application/xml")

    @app.websocket("/voice/stream")
    async def media_stream(websocket: WebSocket):
        """Handle Twilio Media Stream WebSocket.

        Security: WebSocket connections are authenticated using stream tokens
        generated during the incoming call webhook. This prevents unauthorized
        connections from consuming API resources.
        """
        handler = app_state.get("twilio_handler")
        if not handler:
            # Reject connection if Twilio not configured
            await websocket.close(code=1008, reason="Twilio not configured")
            return

        # Accept the connection first (required for WebSocket protocol)
        await websocket.accept()

        try:
            # Handle the stream - token validation happens in CallAdapter
            await handler.handle_media_stream(websocket)
        except ValueError as e:
            # Token validation failed or max calls exceeded
            logger.warning(f"WebSocket rejected: {e}")
            await websocket.close(code=1008, reason=str(e))
        except WebSocketException:
            # Client disconnected
            logger.info("WebSocket client disconnected")
        except Exception as e:
            logger.exception(f"WebSocket error: {e}")
            await websocket.close(code=1011, reason="Internal error")

    @app.post("/call")
    async def initiate_call(request: Request):
        """Initiate an outbound call.

        Body:
            {"to": "+1234567890"}
        """
        handler = app_state.get("twilio_handler")
        if not handler:
            return {"error": "Twilio not configured"}

        data = await request.json()
        to_number = data.get("to")
        if not to_number:
            return {"error": "Missing 'to' phone number"}

        try:
            result = await handler.make_outbound_call(to_number)
            return result
        except Exception as e:
            return {"error": str(e)}

    @app.get("/calls")
    async def list_calls():
        """List active calls."""
        adapter = app_state.get("call_adapter")
        if not adapter:
            return {"calls": []}

        calls = adapter.get_active_calls()
        return {
            "calls": [
                {
                    "sid": c.call_sid,
                    "state": c.state.value,
                    "caller": c.caller,
                    "callee": c.callee,
                }
                for c in calls
            ]
        }

    @app.delete("/calls/{call_sid}")
    async def end_call(call_sid: str):
        """End an active call."""
        handler = app_state.get("twilio_handler")
        if not handler:
            return {"error": "Twilio not configured"}

        success = await handler.end_call(call_sid)
        return {"success": success}

    return app


# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run(
        "chasm.call_server:app",
        host=host,
        port=port,
        reload=True,
    )
