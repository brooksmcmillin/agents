"""Chasm - Voice interface for agent-framework agents.

This package provides voice capabilities for agent-framework agents:

Local Voice Interface:
    - VoiceAdapter: Push-to-talk voice interface using local microphone/speakers
    - create_gui: tkinter-based GUI for voice conversations

Voice Calling (requires 'telephony' extras):
    - CallAdapter: Handle voice calls over telephony connections
    - TwilioCallHandler: Twilio integration for PSTN calling

Install telephony support:
    pip install chasm[telephony]
    # or with uv:
    uv pip install chasm[telephony]
"""

__version__ = "0.2.0"

from .call_adapter import CallAdapter, CallSession, CallState
from .voice_adapter import VoiceAdapter

__all__ = [
    "VoiceAdapter",
    "CallAdapter",
    "CallSession",
    "CallState",
]
