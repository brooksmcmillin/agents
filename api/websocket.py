"""WebSocket endpoint for Claude Code interactive sessions.

Contains the WebSocket handler for real-time Claude Code interaction,
including bidirectional event streaming and command processing.
"""

import asyncio
import logging
import secrets

from fastapi import WebSocket, WebSocketDisconnect

from .auth import authenticate_websocket_connection
from .claude_code_sessions import ClaudeCodeSessionManager

logger = logging.getLogger(__name__)


async def claude_code_websocket_handler(
    websocket: WebSocket,
    session_id: str,
    claude_code_mgr: ClaudeCodeSessionManager,
    dummy_session_token: str,
) -> None:
    """WebSocket endpoint for real-time Claude Code interaction.

    Events sent from server:
    - {"type": "output", "data": "...", "timestamp": "..."}
    - {"type": "permission_request", "data": {...}, "timestamp": "..."}
    - {"type": "state_change", "data": {"state": "..."}, "timestamp": "..."}
    - {"type": "error", "data": "...", "timestamp": "..."}
    - {"type": "completed", "data": {"exit_code": ...}, "timestamp": "..."}

    Commands from client:
    - {"type": "input", "text": "..."}
    - {"type": "permission", "approved": true/false}
    - {"type": "resize", "rows": 40, "cols": 120}
    - {"type": "abort"}

    Authentication (when API_KEY is configured):
    The first message after connecting MUST be:
        {"type": "auth", "api_key": "...", "session_token": "<token from POST /claude-code/sessions>"}
    If auth fails or times out (10s), the connection is closed with code 4001.
    When API_KEY is not configured, only the session_token is required:
        {"type": "auth", "session_token": "<token>"}
    The session_token proves ownership of the specific session and prevents any
    other authenticated caller from connecting to sessions they did not create.
    """
    await websocket.accept()

    auth_data = await authenticate_websocket_connection(websocket)
    if auth_data is None:
        await websocket.close(code=4001, reason="Invalid or missing API key")
        return

    session = claude_code_mgr.get_session(session_id)

    # Verify session ownership via per-session token before revealing whether
    # the session exists.  Returning the same close code for "session not found"
    # and "wrong token" prevents authenticated callers from enumerating valid
    # session IDs by observing differential responses.
    #
    # Always run compare_digest to avoid timing side-channels: use
    # dummy_session_token so the work done when the session doesn't exist is
    # indistinguishable from a real wrong-token check.
    stored_token = session.session_token if session is not None else dummy_session_token
    provided_token = auth_data.get("session_token")
    candidate = provided_token if isinstance(provided_token, str) else ""
    digest_ok = secrets.compare_digest(
        candidate.encode("utf-8"),
        stored_token.encode("utf-8"),
    )
    if session is None or not digest_ok:
        await websocket.close(code=4003, reason="Session not found or invalid token")
        return

    async def send_events() -> None:
        """Send session events to WebSocket client."""
        try:
            async for event in session.events():
                await websocket.send_json(event.to_dict())
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error sending events: {e}")

    async def receive_commands() -> None:
        """Receive and process commands from WebSocket client."""
        try:
            while True:
                data = await websocket.receive_json()
                cmd_type = data.get("type")

                if cmd_type == "input":
                    text = data.get("text", "")
                    await session.send_input(text)

                elif cmd_type == "permission":
                    approved = data.get("approved", False)
                    await session.respond_permission(approved)

                elif cmd_type == "resize":
                    rows = data.get("rows", 40)
                    cols = data.get("cols", 120)
                    await session.resize_terminal(rows, cols)

                elif cmd_type == "abort":
                    await session.terminate()
                    break

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error receiving commands: {e}")

    # Run both tasks concurrently
    send_task = asyncio.create_task(send_events())
    receive_task = asyncio.create_task(receive_commands())

    try:
        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [send_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Don't terminate session on disconnect - it might be intentional
        # to reconnect later
        pass
