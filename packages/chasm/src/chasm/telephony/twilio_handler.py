"""Twilio integration for voice calling.

This module provides a FastAPI-compatible handler for Twilio voice webhooks
and Media Streams. It integrates with the CallAdapter to handle voice
conversations with AI agents.

Setup:
    1. Create a Twilio account and get a phone number
    2. Configure your webhook URLs in Twilio console
    3. Set environment variables:
       - TWILIO_ACCOUNT_SID
       - TWILIO_AUTH_TOKEN
       - TWILIO_PHONE_NUMBER

Security:
    - Request signature validation is ALWAYS enabled in production
    - Set CHASM_ENVIRONMENT=development to disable validation for local testing
    - Stream tokens are used to authenticate WebSocket connections

Example usage with FastAPI:
    from fastapi import FastAPI, WebSocket, Request
    from chasm.telephony import TwilioCallHandler
    from chasm.call_adapter import CallAdapter
    from my_agent import MyAgent

    app = FastAPI()
    agent = MyAgent()
    call_adapter = CallAdapter(agent=agent, greeting="Hello, how can I help you?")
    twilio_handler = TwilioCallHandler(call_adapter)

    @app.post("/voice/incoming")
    async def incoming_call(request: Request):
        return twilio_handler.handle_incoming_call(request)

    @app.websocket("/voice/stream")
    async def media_stream(websocket: WebSocket):
        await twilio_handler.handle_media_stream(websocket)
"""

import base64
import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Environment check for validation
_ENVIRONMENT = os.getenv("CHASM_ENVIRONMENT", "production").lower()
_IS_DEVELOPMENT = _ENVIRONMENT in ("development", "dev", "local", "test")


@dataclass
class TwilioConfig:
    """Configuration for Twilio integration."""

    account_sid: str
    auth_token: str
    phone_number: str
    webhook_base_url: str
    stream_url: str | None = None  # Defaults to {webhook_base_url}/voice/stream

    @classmethod
    def from_env(cls, webhook_base_url: str) -> "TwilioConfig":
        """Create config from environment variables.

        Args:
            webhook_base_url: Base URL for webhooks (e.g., https://your-domain.com)

        Returns:
            TwilioConfig instance.

        Raises:
            ValueError: If required environment variables are missing.
        """
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        phone_number = os.getenv("TWILIO_PHONE_NUMBER")

        if not account_sid:
            raise ValueError("TWILIO_ACCOUNT_SID environment variable required")
        if not auth_token:
            raise ValueError("TWILIO_AUTH_TOKEN environment variable required")
        if not phone_number:
            raise ValueError("TWILIO_PHONE_NUMBER environment variable required")

        return cls(
            account_sid=account_sid,
            auth_token=auth_token,
            phone_number=phone_number,
            webhook_base_url=webhook_base_url,
        )


class TwilioCallHandler:
    """Handles Twilio voice webhooks and Media Streams.

    This class provides the webhook handlers needed to receive and process
    voice calls from Twilio. It integrates with CallAdapter for the actual
    voice conversation handling.

    Security:
        - Request signature validation is enabled by default
        - Set CHASM_ENVIRONMENT=development to disable for local testing
        - Stream tokens authenticate WebSocket connections

    Example:
        from fastapi import FastAPI, WebSocket, Request, Response
        from chasm.telephony import TwilioCallHandler
        from chasm.call_adapter import CallAdapter

        handler = TwilioCallHandler(
            call_adapter=call_adapter,
            config=TwilioConfig.from_env("https://your-domain.com"),
        )

        @app.post("/voice/incoming")
        async def incoming(request: Request):
            twiml = handler.handle_incoming_call(request)
            return Response(content=twiml, media_type="application/xml")

        @app.websocket("/voice/stream")
        async def stream(websocket: WebSocket):
            await websocket.accept()
            await handler.handle_media_stream(websocket)
    """

    def __init__(
        self,
        call_adapter: Any,  # CallAdapter - avoiding circular import
        config: TwilioConfig | None = None,
        webhook_base_url: str | None = None,
    ) -> None:
        """Initialize the Twilio handler.

        Args:
            call_adapter: CallAdapter instance for handling voice conversations.
            config: TwilioConfig instance. If None, created from env vars.
            webhook_base_url: Base URL for webhooks. Required if config is None.

        Note:
            Request signature validation is controlled by CHASM_ENVIRONMENT:
            - production (default): Always validate signatures
            - development/dev/local/test: Skip validation for easier testing
        """
        self.call_adapter = call_adapter

        if config:
            self.config = config
        elif webhook_base_url:
            self.config = TwilioConfig.from_env(webhook_base_url)
        else:
            raise ValueError("Either config or webhook_base_url must be provided")

        # Log validation mode
        if _IS_DEVELOPMENT:
            logger.warning(
                "SECURITY WARNING: Running in development mode - "
                "Twilio request signature validation is DISABLED. "
                "Set CHASM_ENVIRONMENT=production for production deployments."
            )
        else:
            logger.info("Twilio request signature validation enabled")

        # Default stream URL if not specified
        if not self.config.stream_url:
            # Convert https:// to wss:// for WebSocket
            base = self.config.webhook_base_url.replace("https://", "wss://")
            base = base.replace("http://", "ws://")
            self.config.stream_url = urljoin(base, "/voice/stream")

    def validate_twilio_signature(
        self,
        url: str,
        params: dict[str, str],
        signature: str,
    ) -> bool:
        """Validate Twilio request signature.

        Args:
            url: The full URL of the request.
            params: POST parameters from the request.
            signature: X-Twilio-Signature header value.

        Returns:
            True if signature is valid, False otherwise.
        """
        # Build the data string for validation
        data = url
        if params:
            sorted_params = sorted(params.items())
            data += "".join(f"{k}{v}" for k, v in sorted_params)

        # Compute expected signature
        expected = hmac.new(
            self.config.auth_token.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha1,
        ).digest()

        expected_b64 = base64.b64encode(expected).decode("utf-8")

        return hmac.compare_digest(expected_b64, signature)

    async def handle_incoming_call(
        self,
        request: Any,  # FastAPI/Starlette Request
    ) -> str:
        """Handle incoming voice call webhook from Twilio.

        This returns TwiML that instructs Twilio to:
        1. Play a connection message (optional)
        2. Connect to our WebSocket for Media Streams

        Args:
            request: The incoming HTTP request from Twilio.

        Returns:
            TwiML response as XML string.
        """
        # Extract call info from Twilio request
        form = await request.form()
        call_sid = form.get("CallSid", "")
        caller = form.get("From", "")
        callee = form.get("To", "")

        logger.info(f"Incoming call: {call_sid} from {caller} to {callee}")

        # Validate request signature (skip in development mode)
        if not _IS_DEVELOPMENT:
            signature = request.headers.get("X-Twilio-Signature", "")
            url = str(request.url)
            params = dict(form)

            if not self.validate_twilio_signature(url, params, signature):
                logger.warning(f"Invalid Twilio signature for call {call_sid}")
                return self._generate_reject_twiml()

        # Generate stream token for WebSocket authentication
        stream_token = self.call_adapter.generate_stream_token(call_sid)

        # Generate TwiML response with token
        return self._generate_connect_twiml(call_sid, caller, callee, stream_token)

    def _generate_connect_twiml(
        self,
        call_sid: str,
        caller: str,
        callee: str,
        stream_token: str,
    ) -> str:
        """Generate TwiML to connect call to Media Stream.

        Args:
            call_sid: Twilio Call SID.
            caller: Caller phone number.
            callee: Called phone number.
            stream_token: Authentication token for WebSocket.

        Returns:
            TwiML XML string.
        """
        # Build WebSocket URL with query params for call context and token
        stream_url = self.config.stream_url
        params = f"callSid={call_sid}&caller={caller}&callee={callee}&token={stream_token}"
        if "?" in stream_url:
            stream_url += f"&{params}"
        else:
            stream_url += f"?{params}"

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="callSid" value="{call_sid}"/>
            <Parameter name="caller" value="{caller}"/>
            <Parameter name="callee" value="{callee}"/>
        </Stream>
    </Connect>
</Response>"""

    def _generate_reject_twiml(self) -> str:
        """Generate TwiML to reject a call.

        Returns:
            TwiML XML string.
        """
        return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Sorry, this call cannot be connected. Goodbye.</Say>
    <Hangup/>
</Response>"""

    async def handle_media_stream(
        self,
        websocket: Any,  # WebSocket connection
    ) -> None:
        """Handle Media Stream WebSocket connection.

        This is called when Twilio establishes the WebSocket connection
        for streaming audio. Validates the stream token and delegates
        to CallAdapter for processing.

        Args:
            websocket: WebSocket connection from your web framework.

        Raises:
            ValueError: If stream token validation fails.
        """
        # Extract call info from query params
        query_params = dict(websocket.query_params)
        call_sid = query_params.get("callSid", "unknown")
        caller = query_params.get("caller", "")
        callee = query_params.get("callee", "")
        stream_token = query_params.get("token")

        logger.info(f"Media stream connected for call {call_sid}")

        # Delegate to CallAdapter with token validation
        await self.call_adapter.handle_media_stream(
            websocket=websocket,
            call_sid=call_sid,
            caller=caller,
            callee=callee,
            stream_token=stream_token,
        )

    async def make_outbound_call(
        self,
        to_number: str,
        from_number: str | None = None,
    ) -> dict[str, Any]:
        """Initiate an outbound call.

        Uses Twilio API to make an outbound call that will connect
        to our Media Stream handler.

        Args:
            to_number: Phone number to call (E.164 format: +1234567890).
            from_number: Caller ID. Defaults to configured Twilio number.

        Returns:
            Dict with call details (sid, status, etc.).

        Raises:
            Exception: If the call fails to initiate.
        """
        try:
            from twilio.rest import Client

            client = Client(self.config.account_sid, self.config.auth_token)

            webhook_url = urljoin(self.config.webhook_base_url, "/voice/outbound")

            call = client.calls.create(
                to=to_number,
                from_=from_number or self.config.phone_number,
                url=webhook_url,
            )

            logger.info(f"Outbound call initiated: {call.sid} to {to_number}")

            return {
                "sid": call.sid,
                "status": call.status,
                "to": call.to,
                "from_": call.from_,
            }

        except Exception:
            logger.exception(f"Failed to initiate call to {to_number}")
            raise

    def handle_outbound_call(self, call_sid: str) -> str:
        """Handle outbound call webhook.

        Called by Twilio when the outbound call is answered.

        Args:
            call_sid: Twilio Call SID.

        Returns:
            TwiML response as XML string.
        """
        # Generate stream token for the outbound call
        stream_token = self.call_adapter.generate_stream_token(call_sid)
        return self._generate_connect_twiml(call_sid, "", "", stream_token)

    async def end_call(self, call_sid: str) -> bool:
        """End an active call.

        Args:
            call_sid: Twilio Call SID to end.

        Returns:
            True if call was ended, False if call not found.
        """
        try:
            from twilio.rest import Client

            client = Client(self.config.account_sid, self.config.auth_token)

            client.calls(call_sid).update(status="completed")
            logger.info(f"Call ended: {call_sid}")

            return True

        except Exception:
            logger.exception(f"Failed to end call {call_sid}")
            return False
